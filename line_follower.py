# line_follower.py
import threading
import queue
import cv2
import argparse
from robot_client import Esp32RobotClient
import time
from config import DEFAULT_IP, BASE_SPEED, MIN_SPEED, MAX_SPEED, KP, DEAD_ZONE, LOOP_DELAY

MAX_LOOP_DELAY = 0.03

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
        return 0.0, frame
        
    height, width = frame.shape[:2]
    roi = frame[int(height * 0.6):height, 0:width]
    
    # Сжатие картинки в 2 раза для ускорения OpenCV на 400%
    roi_small = cv2.resize(roi, (int(width/2), int((height*0.4)/2)), interpolation=cv2.INTER_NEAREST)
    
    gray = cv2.cvtColor(roi_small, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)
    
    M = cv2.moments(thresh)
    if M["m00"] > 0:
        cx_small = int(M["m10"] / M["m00"])
        cx = cx_small * 2  
        
        center_screen = width / 2
        error = cx - center_screen
        normalized_error = (error / center_screen) * 100
        
        cv2.circle(frame, (cx, int(height * 0.8)), 5, (0, 0, 255), -1)
        cv2.line(frame, (int(center_screen), int(height * 0.6)), (cx, int(height * 0.8)), (0, 255, 0), 2)
        return normalized_error, frame
        
    return 0.0, frame

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
            
            error, processed = process_frame_and_get_error(frame)
            cv2.imshow("Processed camera", processed)
            
            adjustment = abs(error) * KP
            
            if abs(error) > DEAD_ZONE:
                target_speed = int(BASE_SPEED + adjustment)
                target_speed = max(MIN_SPEED, min(target_speed, MAX_SPEED))
                if error > 0:
                    robot.move_right(target_speed)
                    direction_label = "RIGHT"
                else:
                    robot.move_left(target_speed)
                    direction_label = "LEFT "
            else:
                robot.move_forward(BASE_SPEED)
                direction_label = "FORWARD"
            
            print(f"FPS: {current_fps} | Error: {error:6.2f} | Action: {direction_label} | Speed: {robot.current_speed}      ", end="\r")
            
            if cv2.waitKey(1) & 0xFF == 27:
                break
            
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