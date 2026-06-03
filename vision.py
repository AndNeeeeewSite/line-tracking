import base64
import threading
import tkinter as tk
import cv2
import time

from robot import send_command_async

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
forward_speed = 170
turn_speed = 130


def process_frame(frame):
    global last_command_time, movement_state, movement_speed
    
    height, width = frame.shape[:2]

    center_width_percent = 0.25
    screen_center_x = width // 2
    zone_offset = int((width * center_width_percent) / 2)

    left_boundary = screen_center_x - zone_offset
    right_boundary = screen_center_x + zone_offset

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 150, 255, cv2.THRESH_BINARY_INV)#налаштувати маску птм

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(frame, contours, -1, (0, 255, 0), 2)

    left_zone = thresh[0:height, 0:left_boundary]
    center_zone = thresh[0:height, left_boundary:right_boundary]
    right_zone = thresh[0:height, right_boundary:width]

    left_pixels = cv2.countNonZero(left_zone) #рахує білу площу
    center_pixels = cv2.countNonZero(center_zone)
    right_pixels = cv2.countNonZero(right_zone)

    min_pixel_threshold = 50 
    total_pixels = left_pixels + center_pixels + right_pixels

    position_text = "No line"
    text_color = (255, 255, 255)
    current_command = "stop"
    desired_speed = movement_speed

    current_time = time.time()

    if total_pixels > min_pixel_threshold: #ліня є
        if center_pixels >= left_pixels and center_pixels >= right_pixels:
            position_text = "CENTER"
            text_color = (0, 255, 0)
            current_command = "forward"
            desired_speed = forward_speed

        elif left_pixels > right_pixels:
            position_text = "LEFT"
            text_color = (255, 0, 0)
            current_command = "left"
            desired_speed = turn_speed

        elif right_pixels > left_pixels:
            position_text = "RIGHT"
            text_color = (0, 0, 255)
            current_command = "right"
            desired_speed = turn_speed

        speed_changed = desired_speed != movement_speed
        if speed_changed:
            send_command_async(f"speed:{desired_speed}")
            movement_speed = desired_speed

        if current_command != movement_state or current_time - last_command_time >= command_cooldown:
            send_command_async(current_command)
            movement_state = current_command
            last_command_time = current_time
        
    else:
        position_text = "No line"
        current_time = time.time()
        if current_time - last_command_time >= command_cooldown:
            send_command_async("stop")
            last_command_time = current_time
        movement_state = None
        movement_speed = None

    # Рисуем границы зон <-- фу москальська жах
    cv2.line(frame, (left_boundary, 0), (left_boundary, height), (255, 255, 0), 1)
    cv2.line(frame, (right_boundary, 0), (right_boundary, height), (255, 255, 0), 1)
    cv2.putText(frame, f"Status: {position_text}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1, text_color, 2)

    cv2.putText(frame, f"L:{left_pixels} C:{center_pixels} R:{right_pixels}", (20, height - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    return frame

def video_loop(video_canvas, root, stream_url) -> None:
    global video_running

    video = cv2.VideoCapture(stream_url)
    if not video.isOpened():
        video_running = False
        root.after(0, print, "Не вдалося відкрити відеопотік")
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
    root.after(0, print, "Відео зупинено")


def start_video(video_canvas, root, stream_url) -> None:
    global video_running, video_thread

    if video_running:
        return

    video_running = True
    video_thread = threading.Thread(target=video_loop, args=(video_canvas, root, stream_url), daemon=True)
    video_thread.start()
    print("Відео запущено")


def stop_video() -> None:
    global video_running
    video_running = False