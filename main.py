from __future__ import annotations
import base64
import threading
import time
import tkinter as tk
import cv2
import numpy as np
from websocket import create_connection

# Глобальні змінні
robot = None
robot_lock = threading.Lock()
video_running = False
video_thread = None
active_move_command = None
move_lock = threading.Lock()
move_thread = None

# Створення головного вікна програми
root = tk.Tk()
root.title("Line Track Demo")

# IP-адреса вашого робота (ESP32-CAM)
get_ip = '10.1.66.72'.strip()

def get_stream_url() -> str:
    return f"http://{get_ip}:81/stream"

def get_ws_url() -> str:
    """Зібрати WebSocket-адресу для надсилання команд роботу."""
    return f"ws://{get_ip}/ws"

def connect_robot() -> None:
    """Підключитися до робота через WebSocket і перевірити зв'язок командою ping."""
    global robot
    try:
        with robot_lock:
            if robot is not None:
                robot.close()
            robot = create_connection(get_ws_url(), timeout=2)
            robot.send("ping")
            answer = robot.recv()
        print(f"Підключено: {answer}")
    except Exception as error:
        print(f"Помилка підключення: {error}")

def send_command(command: str) -> None:
    """Надіслати одну текстову команду роботу і показати відповідь."""
    global robot
    try:
        with robot_lock:
            if robot is None:
                robot = create_connection(get_ws_url(), timeout=2)
            robot.send(command)
            answer = robot.recv()
        print(f"{command} -> {answer}")
    except Exception as error:
        print(f"Помилка надсилання команди: {error}")

def show_frame(frame) -> None:
    """Показати один відеокадр на полотні Tkinter."""
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

def process_frame(frame):
    """Обробка кадру: пошук лінії та малювання меж (без відправки команд)."""
    height, width, _ = frame.shape

    # Налаштування центральної зони (20% від ширини екрана)
    center_width_percent = 0.20
    screen_center_x = width // 2
    zone_offset = int((width * center_width_percent) / 2)

    left_boundary = screen_center_x - zone_offset
    right_boundary = screen_center_x + zone_offset

    # Перетворення в чорно-біле для виділення лінії
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 60, 255, cv2.THRESH_BINARY_INV)

    # Пошук контурів
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    position_text = "No line"
    text_color = (255, 255, 255)

    if contours:
        largest_contour = max(contours, key=cv2.contourArea)
        
        # Фільтрація шумів за площею
        if cv2.contourArea(largest_contour) > 400:
            x, y, w, h = cv2.boundingRect(largest_contour)

            # Центр знайденої лінії
            line_center_x = x + (w // 2)
            line_center_y = y + (h // 2)

            # Малюємо рамку та точку центру лінії
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (line_center_x, line_center_y), 5, (0, 0, 255), -1)

            # Визначаємо позицію лінії відносно меж
            if line_center_x < left_boundary:
                position_text = "LEFT"
                text_color = (255, 0, 0)
            elif line_center_x > right_boundary:
                position_text = "RIGHT"
                text_color = (0, 0, 255)
            else:
                position_text = "CENTER"
                text_color = (0, 255, 0)

            # Малюємо статус над лінією
            cv2.putText(frame, position_text, (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, text_color, 2)

    # Малюємо жовто-сині лінії меж коридору руху
    cv2.line(frame, (left_boundary, 0), (left_boundary, height), (255, 255, 0), 1)
    cv2.line(frame, (right_boundary, 0), (right_boundary, height), (255, 255, 0), 1)
    
    # Виводимо загальний статус у лівий верхній кут екрана
    cv2.putText(frame, f"Status: {position_text}", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1, text_color, 2)

    return frame

def video_loop() -> None:
    """Читати MJPEG-відеопотік через OpenCV, обробляти та передавати у Tkinter."""
    global video_running

    video = cv2.VideoCapture(get_stream_url())

    if not video.isOpened():
        video_running = False
        root.after(0, print, "Не вдалося відкрити відеопотік")
        return

    while video_running:
        ok, frame = video.read()
        if not ok:
            break

        # Обробка поточного кадру
        try:
            frame = process_frame(frame)
        except Exception as e:
            print(f"Помилка в алгоритмі обробки: {e}")

        # Передаємо оброблений кадр з графікою в Tkinter
        root.after(0, show_frame, frame)

    video.release()
    video_running = False
    root.after(0, print, "Відео зупинено")

def start_video() -> None:
    """Запустити читання відео в окремому потоці."""
    global video_running
    global video_thread

    if video_running:
        return

    video_running = True
    video_thread = threading.Thread(target=video_loop, daemon=True)
    video_thread.start()
    print("Відео запущено")

def stop_video() -> None:
    """Попросити відеопотік зупинитися."""
    global video_running
    video_running = False

def close_app() -> None:
    """Зупинити робота, закрити WebSocket і завершити програму."""
    global active_move_command
    global robot
    global video_running

    with move_lock:
        active_move_command = None

    video_running = False

    try:
        send_command("stop")
    except Exception:
        pass

    with robot_lock:
        if robot is not None:
            robot.close()
            robot = None

    root.destroy()

# Ініціалізація підключень
connect_robot()
start_video()

# Створення Tkinter інтерфейсу для відео
video_canvas = tk.Canvas(
    root,
    width=640,
    height=480,
    bg="black",
    highlightthickness=0,
)
video_canvas.pack(padx=10, pady=10)

root.protocol("WM_DELETE_WINDOW", close_app)
root.mainloop()