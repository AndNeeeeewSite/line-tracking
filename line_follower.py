# line_follower.py
import threading
import queue
import cv2
import argparse
from robot_client import Esp32RobotClient
import time
from config import DEFAULT_IP, BASE_SPEED, MIN_SPEED, MAX_SPEED, KP, DEAD_ZONE, LOOP_DELAY

MAX_LOOP_DELAY = 0.03

# Настройки поиска линии
NO_LINE_KEEP_SEARCH = 15  # Увеличили запас фреймов для активного поиска на месте
NO_LINE_BACKUP = 45       # Увеличили запас для отката назад

# Настройки детекции пробуксовки
SLIP_THRESHOLD = 0.5      # Если ошибка изменилась меньше чем на этот коэффициент за кадр...
SLIP_FRAME_COUNT = 8      # ...в течение стольких кадров подряд, то мы буксуем
SLIP_BOOST_STEP = 4        # Шаг наращивания мощности при пробуксовке

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
    if frame is None:
        return 0.0, False, frame
        
    height, width = frame.shape[:2]
    center_screen = width / 2
    
    small_frame = cv2.resize(frame, (int(width/2), int(height/2)), interpolation=cv2.INTER_NEAREST)
    gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)
    
    zones = [
        (int(height/2 * 0.55), int(height/2 * 0.70), 0.5),  # Дальняя
        (int(height/2 * 0.70), int(height/2 * 0.85), 0.3),  # Средняя
        (int(height/2 * 0.85), int(height/2 * 1.00), 0.2)   # Ближняя
    ]
    
    total_error = 0.0
    valid_zones = 0
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    
    for i, (y_start, y_end, weight) in enumerate(zones):
        roi_thresh = thresh[y_start:y_end, 0:int(width/2)]
        M = cv2.moments(roi_thresh)
        
        if M["m00"] > 0:
            cx_small = int(M["m10"] / M["m00"])
            cx_original = cx_small * 2
            
            zone_error = ((cx_original - center_screen) / center_screen) * 100
            total_error += zone_error * weight
            valid_zones += weight
            
            y_center_orig = int((y_start + y_end) * 2 / 2)
            cv2.circle(frame, (cx_original, y_center_orig), 6, colors[i], -1)
            cv2.line(frame, (int(center_screen), y_center_orig), (cx_original, y_center_orig), colors[i], 2)

    if valid_zones > 0:
        final_error = total_error / valid_zones
        return final_error, True, frame

    return 0.0, False, frame

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--ip", type=str, default=DEFAULT_IP)
    args = parser.parse_args()
    
    robot = Esp32RobotClient(ip=args.ip)
    if not robot.connect():
        return

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
    
    # Системные переменные для новых функций
    robot_active = False       # Флаг старт/стоп режима
    slip_boost = 0            # Добавочная мощность при пробуксовке
    stuck_frames_counter = 0  # Счетчик кадров неподвижности
    prev_error = 0.0          # Ошибка на предыдущем кадре
    
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
            
            error, line_found, processed = process_frame_and_get_error(frame)
            
            # Визуальный индикатор состояния Старт/Стоп на экране
            status_text = "RUNNING" if robot_active else "PAUSED (PRESS SPACE)"
            status_color = (0, 255, 0) if robot_active else (0, 0, 255)
            cv2.putText(processed, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
            cv2.imshow("Processed camera", processed)
            
            if robot_active:
                if line_found:
                    lost_frames = 0
                    abs_error = abs(error)
                    
                    # --- ДЕТЕКЦИЯ ПРОБУКСОВКИ ---
                    # Если мы пытаемся повернуться (ошибка большая), но значение ошибки "застыло"
                    if abs_error > DEAD_ZONE and abs(error - prev_error) < SLIP_THRESHOLD:
                        stuck_frames_counter += 1
                        if stuck_frames_counter >= SLIP_FRAME_COUNT:
                            slip_boost += SLIP_BOOST_STEP
                    else:
                        # Если робот успешно двигается или находится в dead_zone, плавно снижаем или обнуляем буст
                        stuck_frames_counter = 0
                        slip_boost = max(0, slip_boost - 2) 
                    
                    prev_error = error
                    # -----------------------------

                    if abs_error <= DEAD_ZONE:
                        target_speed = BASE_SPEED
                        robot.move_forward(target_speed)
                        direction_label = "FORWARD"
                    else:
                        # Динамическая скорость + компенсатор пробуксовки
                        target_speed = int(BASE_SPEED + (abs_error * KP) + slip_boost)
                        target_speed = max(MIN_SPEED, min(target_speed, MAX_SPEED))
                        
                        if error > 0:
                            robot.move_right(target_speed)
                            direction_label = f"RIGHT (+{slip_boost})"
                        else:
                            robot.move_left(target_speed)
                            direction_label = f"LEFT  (+{slip_boost})"
                    last_error = error
                else:
                    # Линия потеряна
                    lost_frames += 1
                    stuck_frames_counter = 0
                    slip_boost = 0
                    
                    if lost_frames <= NO_LINE_KEEP_SEARCH:
                        # ЭТАП 1: Поиск веером. Доворачиваем в сторону последней ошибки, 
                        # постепенно снижая скорость, чтобы описать дугу-спираль наружу
                        target_speed = int(MAX_SPEED - (lost_frames * 4))
                        target_speed = max(MIN_SPEED, target_speed)
                        
                        if last_error > 0:
                            robot.move_right(target_speed)
                            direction_label = f"SCAN-RIGHT ({target_speed})"
                        else:
                            robot.move_left(target_speed)
                            direction_label = f"SCAN-LEFT ({target_speed})"
                            
                    elif lost_frames <= NO_LINE_BACKUP:
                        # ЭТАП 2: Умный рекавер назад. Откатываемся назад не по прямой, 
                        # а под углом, противоположным утерянной линии, на высокой мощности
                        target_speed = 130
                        if last_error > 0:
                            # Если линия ушла вправо, сдаем назад со смещением влево
                            robot.move_backward(target_speed) # Или специфичный метод левого реверса, если есть
                            direction_label = "RECOVER-BACK-LEFT"
                        else:
                            robot.move_backward(target_speed)
                            direction_label = "RECOVER-BACK-RIGHT"
                    else:
                        target_speed = 0
                        robot.stop()
                        direction_label = "LOST-STOPPED"
            else:
                # Если режим Стоп (пауза)
                robot.stop()
                direction_label = "HOLD"
                target_speed = 0
                slip_boost = 0
                stuck_frames_counter = 0
            
            printed_error = error if line_found else float('nan')
            print(f"FPS: {current_fps} | Error: {printed_error:6.2f} | Action: {direction_label} | Boost: {slip_boost}      ", end="\r")
            
            # Обработка нажатий клавиш
            key = cv2.waitKey(1) & 0xFF
            if key == 27: # ESC
                break
            elif key == 32: # SPACE (Пробел)
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