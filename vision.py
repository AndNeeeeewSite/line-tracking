import base64
import threading
import tkinter as tk
import cv2
import time
import math
from collections import deque
import numpy as np

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
command_cooldown = 0.2
movement_state = None
movement_speed = None
forward_speed = 120
turn_speed = 120
line_roi_top = 0.45
line_min_pixels = 600
error_history = deque(maxlen=6)


def process_frame(frame):
    global last_command_time, movement_state, movement_speed

    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)
    thresh = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        11,
        2,
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

    roi_top = int(height * line_roi_top)
    roi = thresh[roi_top:height, :]

    band_count = 4
    band_height = max(1, (height - roi_top) // band_count)
    line_points = []
    for band_index in range(band_count):
        y1 = band_index * band_height
        y2 = min(roi.shape[0], y1 + band_height)
        band = roi[y1:y2, :]
        nonzero = cv2.findNonZero(band)
        if nonzero is None or len(nonzero) < 30:
            continue

        xs = nonzero[:, 0, 0]
        mean_x = int(np.mean(xs))
        line_points.append((mean_x, roi_top + y1 + (y2 - y1) // 2))

    target_x = width // 2
    curve = 0
    status = "No line"
    command = "stop"
    desired_speed = movement_speed

xs = np.array([p[0] for p in line_points], dtype=np.float32)
        ys = np.array([p[1] for p in line_points], dtype=np.float32)
        weights = np.linspace(1.0, 2.0, len(xs))
        target_x = int(np.average(xs, weights=weights))

        if len(xs) > 1:
            curve = int(xs[-1] - xs[0])
        else:
            curve = 0

        error_x = target_x - width // 2
        error_history.append(error_x)
        smoothed_error = int(np.mean(error_history)) if error_history else error_x

        angle = 0.0
        if len(xs) > 1:
            slope = np.polyfit(ys, xs, 1)[0]
            angle = math.degrees(math.atan(slope))

        center_threshold = width * 0.08
        strong_turn_threshold = width * 0.18
        curve_threshold = width * 0.06

        if abs(smoothed_error) < center_threshold and abs(curve) < curve_threshold:
            status = "FORWARD"
            command = "forward"
            desired_speed = forward_speed
        else:
            if abs(smoothed_error) > strong_turn_threshold:
                command = "left" if smoothed_error < 0 else "right"
            elif len(line_points) >= 3:
                command = "left" if smoothed_error < 0 else "right"
            else:
                command = movement_state or "forward"

            if command == "left":
                status = "LEFT"
                desired_speed = turn_speed
            elif command == "right":
                status = "RIGHT"
                desired_speed = turn_speed
            else:
                status = "FORWARD"
                desired_speed = forward_speed

        for px, py in line_points:
            cv2.circle(frame, (px, py), 6, (0, 255, 255), -1)
        cv2.line(frame, (width // 2, roi_top), (target_x, height - 1), (0, 255, 255), 2)
        cv2.rectangle(frame, (0, roi_top), (width - 1, height - 1), (255, 255, 0), 2)
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
        (0, 255, 0) if status != "No line" else (0, 0, 255),
        2,
    )

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