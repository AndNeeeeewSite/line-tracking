import cv2
import numpy as np
import argparse
from robot_client import Esp32RobotClient
import time
from config import DEFAULT_IP, BASE_SPEED, MIN_SPEED, MAX_SPEED, KP, DEAD_ZONE, LOOP_DELAY


def process_frame_and_get_error(frame):
    if frame is None:
        return 0.0, frame

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 80, 255, cv2.THRESH_BINARY_INV)
    height, width = thresh.shape
    roi = thresh[int(height * 0.6):height, 0:width]
    M = cv2.moments(roi)
    if M["m00"] > 0:
        cx = int(M["m10"] / M["m00"])
        center_screen = width / 2
        error = cx - center_screen
        normalized_error = (error / center_screen) * 100
        cv2.circle(frame, (cx, int(height * 0.8)), 5, (0, 0, 255), -1)
        cv2.line(frame, (int(center_screen), int(height * 0.6)), (cx, int(height * 0.8)), (0, 255, 0), 2)
        return normalized_error, frame

    return 0.0, frame

def main():
    parser = argparse.ArgumentParser(description="KPI Robot Vision Car - Line Follower")
    parser.add_argument("-i", "--ip", type=str, default=DEFAULT_IP, help="IP-адрес ESP32-CAM")
    args = parser.parse_args()
    robot = Esp32RobotClient(ip=args.ip)
    if not robot.connect():
        print("Не подключено к роботу.")
        return
    stream_url = f"http://{args.ip}:81/stream"
    print(f"Видео: {stream_url}")
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        print("Поток камеры не открыт.")
        robot.disconnect()
        return
    print("\nСтарт. Следование по линии.")
    print("Ctrl+C для остановки.")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Пропуск кадра...")
                continue
            raw_frame = frame.copy()
            error, processed = process_frame_and_get_error(frame)
            cv2.imshow("Raw camera", raw_frame)
            cv2.imshow("Processed camera", processed)
            adjustment = abs(error) * KP
            if abs(error) > DEAD_ZONE:
                target_speed = int(BASE_SPEED + adjustment)
                target_speed = max(MIN_SPEED, min(target_speed, MAX_SPEED))
                robot.set_speed(target_speed)
                if error > 0:
                    robot.move_right()
                    direction_label = "RIGHT"
                else:
                    robot.move_left()
                    direction_label = "LEFT "
            else:
                robot.set_speed(BASE_SPEED)
                robot.move_forward()
                direction_label = "FORWARD"
            print(f"Error: {error:6.2f} | Action: {direction_label} | Speed: {robot.current_speed}", end="\r")
            if cv2.waitKey(1) & 0xFF == 27:
                break
            time.sleep(LOOP_DELAY)
    except KeyboardInterrupt:
        print("\nОстановка...")
    finally:
        robot.stop()
        robot.disconnect()
        cap.release()
        cv2.destroyAllWindows()
        print("Завершено.")

if __name__ == "__main__":
    main()