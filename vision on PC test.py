import base64
import threading
import tkinter as tk
import cv2
import time
import math
import numpy as np

def send_command_async(command):
    print(f"Відправлено команду: {command}")


video_running = False
video_thread = None


def show_frame(frame, video_canvas) -> None:
    ok, png = cv2.imencode(".png", frame)
    if not ok:
        return

    data = base64.b64encode(png.tobytes())
    image = tk.PhotoImage(data=data)

    height, width = frame.shape[:2]
    video_canvas.config(width=width, height=height, scrollregion=(0, 0, width, height))

    video_canvas.delete("all")
    video_canvas.create_image(0, 0, anchor="nw", image=image)
    video_canvas.image = image


last_command_time = 0
command_cooldown = 0.1
movement_state = None
movement_speed = None
forward_speed = 150
turn_speed = 150
line_roi_top = 0.45
line_min_pixels = 600


def process_frame(frame):
    global last_command_time, movement_state, movement_speed

    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    
    main_contour = None
    if contours:
        main_contour = max(contours, key=cv2.contourArea)
        cv2.drawContours(frame, [main_contour], -1, (0, 255, 0), 2)

    band_count = 5  
    band_height = height // band_count
    
    line_points = []
    
    for band_index in range(band_count):
        y1 = band_index * band_height
        y2 = (band_index + 1) * band_height if band_index != band_count - 1 else height
        mid_y = y1 + (y2 - y1) // 2

        cv2.line(frame, (0, y2), (width - 1, y2), (255, 255, 0), 1)

        if main_contour is not None:
            in_band_points = main_contour[(main_contour[:, 0, 1] >= y1) & (main_contour[:, 0, 1] < y2)]
            
            if len(in_band_points) > 0:
                xs_contour = in_band_points[:, 0, 0]
                min_x = np.min(xs_contour)
                max_x = np.max(xs_contour)
                
                mean_x = int((min_x + max_x) / 2)
                
                line_points.append((mean_x, mid_y))
                cv2.circle(frame, (mean_x, mid_y), 6, (0, 255, 255), -1)

    target_x = width // 2
    curve = 0
    angle = 0.0
    status = "No line"
    command = "stop"
    desired_speed = movement_speed

    if line_points:
        xs = np.array([p[0] for p in line_points], dtype=np.float32)
        ys = np.array([p[1] for p in line_points], dtype=np.float32)
        
        weights = np.linspace(1.0, 2.0, len(xs))
        target_x = int(np.average(xs, weights=weights))

        if len(xs) > 1:
            curve = int(xs[0] - xs[-1])
            
            slope = np.polyfit(ys, xs, 1)[0]
            angle = math.degrees(math.atan(slope))
        else:
            curve = 0
            angle = 0.0

        error_x = target_x - width // 2

        if abs(error_x) < width * 0.08 and abs(curve) < width * 0.05:
            status = "FORWARD"
            command = "forward"
            desired_speed = forward_speed
        elif error_x < 0 or curve < 0:
            status = "LEFT"
            command = "left"
            desired_speed = turn_speed
        else:
            status = "RIGHT"
            command = "right"
            desired_speed = turn_speed

        cv2.line(frame, (width // 2, 0), (target_x, height - 1), (0, 165, 255), 2)
        
        cv2.putText(
            frame,
            f"Error: {error_x} Curve: {curve} Angle: {angle:.1f}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )
    else:
        desired_speed = None

    current_time = time.time()
    if line_points and len(line_points) >= 1:
        if desired_speed is not None and desired_speed != movement_speed:
            send_command_async(f"speed:{desired_speed}")
            movement_speed = desired_speed

        if command != movement_state or current_time - last_command_time >= command_cooldown:
            send_command_async(command)
            movement_state = command
            last_command_time = current_time
    else:
        if current_time - last_command_time >= command_cooldown:
            send_command_async("stop")
            movement_state = None
            movement_speed = None
            last_command_time = current_time

    cv2.putText(
        frame,
        f"Status: {status}",
        (20, height - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0) if status == "FORWARD" else ((255, 255, 255) if status == "No line" else (0, 0, 255)),
        2,
    )

    return frame


def video_loop(video_canvas, root, stream_url) -> None:
    global video_running

    video = cv2.VideoCapture(1) 
    
    if not video.isOpened():
        video_running = False
        root.after(0, print, "Не вдалося відкрити веб-камеру комп'ютера")
        return

    while video_running:
        ok, frame = video.read()
        if not ok:
            break

        try:
            frame = process_frame(frame)
        except Exception as e:
            print(f"Помилка в алгоритмі обробки: {e}")

        root.after(0, show_frame, frame, video_canvas)

    video.release()
    video_running = False
    root.after(0, print, "Відео з веб-камери зупинено")


def start_video(video_canvas, root, stream_url=None) -> None:
    global video_running, video_thread

    if video_running:
        return

    video_running = True
    video_thread = threading.Thread(target=video_loop, args=(video_canvas, root, None), daemon=True)
    video_thread.start()
    print("Відеопотік з веб-камери запущено")


def stop_video() -> None:
    global video_running
    video_running = False


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Тест алгоритму секторів")
    
    canvas = tk.Canvas(root, width=640, height=480, bg="black")
    canvas.pack(padx=10, pady=10)
    
    btn_frame = tk.Frame(root)
    btn_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=5)
    
    tk.Button(btn_frame, text="СТАРТ КАМЕРА", command=lambda: start_video(canvas, root), bg="green", fg="white").pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="СТОП", command=stop_video, bg="red", fg="white").pack(side=tk.LEFT, padx=5)
    
    root.mainloop()