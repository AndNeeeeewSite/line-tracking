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