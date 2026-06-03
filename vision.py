import base64
import threading
import tkinter as tk
import cv2

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


import time

last_command_time = 0
command_cooldown = 0.1
smoothed_line_x = None
movement_state = None
movement_speed = None
forward_speed = 170
turn_speed = 100


def process_frame(frame):
    global last_command_time, smoothed_line_x, movement_state, movement_speed
    
    height, width = frame.shape[:2]

    center_width_percent = 0.25
    screen_center_x = width // 2
    zone_offset = int((width * center_width_percent) / 2)

    left_boundary = screen_center_x - zone_offset
    right_boundary = screen_center_x + zone_offset

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 60, 255, cv2.THRESH_BINARY_INV)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    position_text = "No line"
    text_color = (255, 255, 255)

    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest_contour) > 600:
            x, y, w, h = cv2.boundingRect(largest_contour)
            line_center_x = x + (w // 2)
            line_center_y = y + (h // 2)

            if smoothed_line_x is None:
                smoothed_line_x = line_center_x
            else:
                smoothed_line_x = int(0.3 * line_center_x + 0.7 * smoothed_line_x)

            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (smoothed_line_x, line_center_y), 5, (0, 0, 255), -1)

            if smoothed_line_x < left_boundary:
                position_text = "LEFT"
                text_color = (255, 0, 0)
                current_command = "right"
            elif smoothed_line_x > right_boundary:
                position_text = "RIGHT"
                text_color = (0, 0, 255)
                current_command = "left"
            else:
                position_text = "CENTER"
                text_color = (0, 255, 0)
                current_command = "forward"

            desired_speed = turn_speed if current_command in ("left", "right") else forward_speed

            current_time = time.time()
            if current_time - last_command_time > command_cooldown:
                speed_changed = desired_speed != movement_speed
                if speed_changed:
                    send_command_async(f"speed:{desired_speed}")
                    movement_speed = desired_speed

                if current_command != movement_state or speed_changed:
                    send_command_async(current_command)
                    movement_state = current_command

                last_command_time = current_time

            cv2.putText(frame, position_text, (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)
        else:
            smoothed_line_x = None
            movement_state = None
            movement_speed = None
    else:
        smoothed_line_x = None
        movement_state = None
        movement_speed = None

    # Рисуем границы зон
    cv2.line(frame, (left_boundary, 0), (left_boundary, height), (255, 255, 0), 1)
    cv2.line(frame, (right_boundary, 0), (right_boundary, height), (255, 255, 0), 1)
    cv2.putText(frame, f"Status: {position_text}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1, text_color, 2)

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
