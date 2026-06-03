import os
import cv2
import tkinter as tk
import vision
from vision import process_frame
vision.send_command_async = lambda cmd: print(f"Отримано команду: {cmd}")

def test_on_images():
    img_dir = os.path.join("line_test(img)")
    test_files = ["forward_line.jpg", "left_line.jpg", "right_line.jpg"]

    print("Тетс алгоритму")

    for file_name in test_files:
        img_path = os.path.join(img_dir, file_name)
        
        if not os.path.exists(img_path):
            img_path = file_name
            if not os.path.exists(img_path):
                print(f"Файл {file_name} не знайдено")
                continue

        frame = cv2.imread(img_path)
        if frame is None:
            print(f"Не вдалося завантажити {file_name}")
            continue

        frame = cv2.resize(frame, (640, 480))

        processed_frame = frame.copy()

        result_frame = process_frame(processed_frame)

        cv2.imshow("Test Vision Algorithm", result_frame)
        
        key = cv2.waitKey(0) & 0xFF
        if key == ord('q'):
            break

    cv2.destroyAllWindows()
 
if __name__ == "__main__":
    test_on_images()