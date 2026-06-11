# line_follower.py
import threading
import queue
import cv2
import argparse
from robot_client import Esp32RobotClient
import time
from config import DEFAULT_IP, BASE_SPEED, MIN_SPEED, MAX_SPEED, TURN_SPEED, KP, DEAD_ZONE, LOOP_DELAY

MAX_LOOP_DELAY = 0.03

# === НАСТРОЙКИ ПОВЫШЕННОЙ ОТЗЫВЧИВОСТИ И БОЛЬШОГО ЗАПАСА РЕКАВЕРИ ===

# Настройки поиска линии
NO_LINE_KEEP_SEARCH = 5    # Быстрый скана по сторонам на месте
# !!! БОЛЬШОЙ ЗАПАС КАДРОВ ДЛЯ УВЕРЕННОГО ОТКАТА НАЗАД !!!
NO_LINE_BACKUP = 45        # Было 25. Даем роботу гораздо больше времени катиться назад в поисках линии
NO_LINE_RECOVER_SPEED = MAX_SPEED 

# Настройки детекции буксования
SLIP_THRESHOLD = 0.6       
SLIP_FRAME_COUNT = 4       
# !!! УВЕЛИЧЕННЫЙ ВРЕМЕННОЙ ЗАПАС ИМПУЛЬСА ОТКАТА !!!
BACKOFF_DURATION = 0.45    # Было 0.22. Робот дольше и глубже отскакивает назад на MAX_SPEED при буксе

# Настройки динамического ускорения на прямых
STRAIGHT_ACCEL_STEP = 4    
STRAIGHT_THRESHOLD = 6.0   

def video_capture_thread(url, frame_queue, stop_event):
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        return
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.005)
            continue
        if frame_queue.full():
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                pass
        frame_queue.put(frame)
    cap.release()

def process_frame_and_get_error(frame):
    """
    Анализирует 5 горизонтальных зон (ROI) от горизонта до бампера робота.
    """
    if frame is None:
        return 0.0, False, False, frame
        
    height, width = frame.shape[:2]
    center_screen = width / 2
    
    small_frame = cv2.resize(frame, (int(width/2), int(height/2)), interpolation=cv2.INTER_NEAREST)
    gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)
    
    zones = [
        (int(height/2 * 0.50), int(height/2 * 0.60), 0.35), 
        (int(height/2 * 0.60), int(height/2 * 0.70), 0.25), 
        (int(height/2 * 0.70), int(height/2 * 0.80), 0.15), 
        (int(height/2 * 0.80), int(height/2 * 0.90), 0.15), 
        (int(height/2 * 0.90), int(height/2 * 1.00), 0.10)  
    ]
    
    total_error = 0.0
    valid_zones = 0
    all_zones_straight = True
    
    colors = [(255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 165, 255), (0, 0, 255)]
    
    for i, (y_start, y_end, weight) in enumerate(zones):
        roi_thresh = thresh[y_start:y_end, 0:int(width/2)]
        M = cv2.moments(roi_thresh)
        
        if M["m00"] > 0:
            cx_small = int(M["m10"] / M["m00"])
            cx_original = cx_small * 2
            
            zone_error = ((cx_original - center_screen) / center_screen) * 100
            total_error += zone_error * weight
            valid_zones += weight
            
            if abs(zone_error) > STRAIGHT_THRESHOLD:
                all_zones_straight = False
            
            y_center_orig = int((y_start + y_end) * 2 / 2)
            cv2.circle(frame, (cx_original, y_center_orig), 5, colors[i], -1)
            cv2.line(frame, (int(center_screen), y_center_orig), (cx_original, y_center_orig), colors[i], 1)
        else:
            if i < 2: 
                all_zones_straight = False

    if valid_zones > 0:
        final_error = total_error / valid_zones
        return final_error, True, all_zones_straight, frame

    return 0.0, False, False, frame

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--ip", type=str, default=DEFAULT_IP)
    args = parser.parse_args()
    
    robot = Esp32RobotClient(ip=args.ip)
    if not robot.connect():
        return

    robot.send_command_async("led:on")

    stream_url = f"http://{args.ip}:81/stream"
    frame_queue = queue.Queue(maxsize=2)
    stop_event = threading.Event()
    
    reader_thread = threading.Thread(
        target=video_capture_thread, 
        args=(stream_url, frame_queue, stop_event), 
        daemon=True
    )
    reader_thread.start()
    
    loop_delay = min(LOOP_DELAY, MAX_LOOP_DELAY)
    fps_counter = 0
    fps_timer = time.time()
    current_fps = 0
    
    last_error = 0.0
    lost_frames = 0
    
    robot_active = False       
    stuck_frames_counter = 0  
    prev_error = 0.0          
    current_cruise_speed = BASE_SPEED 
    
    # Таймер для реализации НЕблокирующего отката назад
    recovery_until_time = 0.0

    print("\n=== УПРАВЛЕНИЕ РОБОТОМ ===")
    print("Пробел (SPACE) — СТАРТ / СТОП движения")
    print("ESC           — Выход из программы\n")

    try:
        while True:
            try:
                frame = frame_queue.get(timeout=0.02)
            except queue.Empty:
                continue
            
            current_time = time.time()
            fps_counter += 1
            if current_time - fps_timer >= 1.0:
                current_fps = fps_counter
                fps_counter = 0
                fps_timer = current_time
            
            error, line_found, is_straight, processed = process_frame_and_get_error(frame)
            
            status_text = "RUNNING" if robot_active else "PAUSED (PRESS SPACE)"
            status_color = (0, 255, 0) if robot_active else (0, 0, 255)
            cv2.putText(processed, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)
            cv2.imshow("Processed camera", processed)
            
            if robot_active:
                # --- ОБРАБОТКА АКТИВНОГО НЕБЛОКИРУЮЩЕГО ОТКАТА ---
                if current_time < recovery_until_time:
                    direction_label = "SLIP-REVERSE"
                    printed_error = error if line_found else float('nan')
                    print(f"FPS: {current_fps} | Error: {printed_error:6.2f} | Action: {direction_label}      ", end="\r")
                    
                    key = cv2.waitKey(1) & 0xFF
                    if key == 32: robot_active = False; robot.stop()
                    if key == 27: break
                    if loop_delay > 0: time.sleep(loop_delay)
                    continue

                if line_found:
                    lost_frames = 0
                    abs_error = abs(error)
                    
                    # --- УЛЬТРА-ДЕТЕКЦИЯ БУКСОВАНИЯ ---
                    if abs_error > DEAD_ZONE and abs(error - prev_error) < SLIP_THRESHOLD:
                        stuck_frames_counter += 1
                        if stuck_frames_counter >= SLIP_FRAME_COUNT:
                            print("\n[!] БУКС! Глубокий откат назад со стратегическим запасом...")
                            
                            robot.move_backward(MAX_SPEED) 
                            
                            recovery_until_time = time.time() + BACKOFF_DURATION
                            stuck_frames_counter = 0
                            current_cruise_speed = BASE_SPEED 
                            prev_error = error
                            continue
                    else:
                        stuck_frames_counter = 0
                    
                    prev_error = error
                    # -------------------------------------

                    # --- АДАПТИВНЫЙ КРУИЗ (УСКОРЕНИЕ НА ПРЯМОЙ) ---
                    if is_straight and abs_error <= DEAD_ZONE:
                        current_cruise_speed = min(MAX_SPEED, current_cruise_speed + STRAIGHT_ACCEL_STEP)
                        target_speed = int(current_cruise_speed)
                        robot.move_forward(target_speed)
                        direction_label = f"FORWARD-FAST ({target_speed})"
                    else:
                        current_cruise_speed = BASE_SPEED
                        
                        if abs_error <= DEAD_ZONE:
                            robot.move_forward(BASE_SPEED)
                            direction_label = "FORWARD"
                        else:
                            # П-регулятор
                            target_speed = int(BASE_SPEED + (abs_error * KP))
                            target_speed = max(MIN_SPEED, min(target_speed, MAX_SPEED))
                            
                            if error > 0:
                                target_speed = TURN_SPEED
                                robot.move_right(target_speed)
                                direction_label = f"RIGHT ({target_speed})"
                            else:
                                target_speed = TURN_SPEED
                                robot.move_left(target_speed)
                                direction_label = f"LEFT  ({target_speed})"
                    
                    last_error = error
                else:
                    # Линия утеряна — Увеличенные фазы восстановления
                    lost_frames += 1
                    stuck_frames_counter = 0
                    current_cruise_speed = BASE_SPEED
                    
                    if lost_frames <= NO_LINE_KEEP_SEARCH:
                        target_speed = int(MAX_SPEED - (lost_frames * 6))
                        target_speed = max(MIN_SPEED, target_speed)
                        if last_error > 0:
                            robot.move_right(target_speed)
                            direction_label = "SCAN-RIGHT"
                        else:
                            robot.move_left(target_speed)
                            direction_label = "SCAN-LEFT"
                    elif lost_frames <= NO_LINE_BACKUP:
                        # Продолжительный и глубокий откат назад на MAX_SPEED
                        robot.move_backward(NO_LINE_RECOVER_SPEED)
                        direction_label = f"RECOVER-BACK ({lost_frames}/{NO_LINE_BACKUP})"
                    else:
                        target_speed = 0
                        robot.stop()
                        direction_label = "LOST-STOPPED"
            else:
                robot.stop()
                direction_label = "HOLD"
                current_cruise_speed = BASE_SPEED
                stuck_frames_counter = 0
            
            printed_error = error if line_found else float('nan')
            print(f"FPS: {current_fps} | Error: {printed_error:6.2f} | Action: {direction_label}      ", end="\r")
            
            key = cv2.waitKey(1) & 0xFF
            if key == 27: 
                break
            elif key == 32: 
                robot_active = not robot_active
                if not robot_active:
                    robot.stop()
            
            if loop_delay > 0:
                time.sleep(loop_delay)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        reader_thread.join(timeout=1)
        robot.stop()
        robot.disconnect()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()