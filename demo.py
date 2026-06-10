"""Мінімальний демонстраційний приклад для KPI Robot Vision Car.

Запуск:
    python simple_robot_demo.py

У цьому файлі показано базовий програмний інтерфейс API робота:
WebSocket-команди для керування і MJPEG-потік для відео.
"""

from __future__ import annotations

# base64 потрібний для передавання кадру у tk.PhotoImage.
import base64

# threading потрібний для обробки команд і відео, щоб головне вікно Tkinter не зависало.
import threading

# time потрібний для створення короткої паузи між повторним надсиланням команд руху.
import time

# tkinter входить до стандартної бібліотеки Python і створює просте графічне вікно.
import tkinter as tk

# OpenCV читає MJPEG-відеопотік і кодує кадри у форматі PNG для відображення в Tkinter.
import cv2

# create_connection відкриває просте WebSocket-з'єднання з ESP32-CAM.
from websocket import create_connection


# Початкові налаштування програми.
# IP можна змінити у цьому рядку або вже у полі введення після запуску.
DEFAULT_IP = "192.168.31.210"

# Початкова швидкість двигунів. Робот очікує значення у діапазоні 85...255.
DEFAULT_SPEED = 170

# Команди руху повторюються раз на 0,2 секунди.
# Це дає роботу регулярно отримувати підтвердження, що рух ще потрібний.
MOVE_REPEAT_SECONDS = 0.2

# Змінна robot зберігає один відкритий WebSocket-зв'язок для надсилання команд.
# Значення None означає, що WebSocket ще не створено або вже закрито.
robot = None

# Блокування потрібне, бо команди можуть надсилатися з різних потоків.
# Воно не дає двом командам одночасно потрапляти в один WebSocket.
robot_lock = threading.Lock()

# Прапорець video_running керує циклом читання відео.
# Коли значення False, відеопотік має завершитись.
video_running = False

# Змінна video_thread зберігає посилання на відеопотік, який читає кадри з камери.
video_thread = None

# active_move_command зберігає поточну команду руху, яку треба повторювати.
# Значення None означає, що жодна кнопка руху зараз не утримується.
active_move_command = None

# Окреме блокування потоку команд потрібне для читання і зміни active_move_command.
move_lock = threading.Lock()

# move_thread зберігає фоновий потік, який регулярно повторює команду руху.
move_thread = None


def get_ip() -> str:
    """Повернути IP-адресу ESP32-CAM з поля введення."""

    # strip() прибирає випадкові пробіли на початку і в кінці IP-адреси.
    return ip_entry.get().strip()


def get_ws_url() -> str:
    """Зібрати WebSocket-адресу для надсилання команд роботу."""

    # Команди керування надсилаються на шлях /ws основного HTTP-сервера ESP32-CAM.
    return f"ws://{get_ip()}/ws"


def get_stream_url() -> str:
    """Зібрати HTTP-адресу MJPEG-відеопотоку."""

    # Відео з ESP32-CAM доступне окремо на порту 81 за посиланням /stream.
    return f"http://{get_ip()}:81/stream"


def set_status(text: str) -> None:
    """Показати коротке повідомлення в нижньому рядку стану."""

    # Рядок стану використовується для відображення відповідей робота і повідомлень про помилки.
    status_label.config(text=text)


def connect_robot() -> None:
    """Підключитися до робота через WebSocket і перевірити зв'язок командою ping."""

    global robot

    try:
        # Усі операції з WebSocket виконуються під блокуванням.
        with robot_lock:
            # Якщо старе з'єднання вже було, спочатку закриваємо його.
            if robot is not None:
                robot.close()

            # Створюємо WebSocket-з'єднання з коротким таймаутом підключення.
            robot = create_connection(get_ws_url(), timeout=2)

            # ping є простою перевіркою, що робот приймає команди і відповідає (відповідь має бути "PONG").
            robot.send("ping")
            answer = robot.recv()

        # Відповідь робота показується у рядку стану.
        set_status(f"Підключено: {answer}")
    except Exception as error:
        # Для цього прикладу достатньо показати текст помилки у вікні.
        set_status(f"Помилка підключення: {error}")


def send_command(command: str) -> None:
    """Надіслати одну текстову команду роботу і показати відповідь."""

    global robot

    try:
        # Блокування потоку гарантує послідовне надсилання команд.
        with robot_lock:
            # Якщо WebSocket-канал ще не відкритий, створюємо його перед першою командою.
            if robot is None:
                robot = create_connection(get_ws_url(), timeout=2)

            # API робота приймає прості рядки: forward, stop, led:on, ping тощо.
            robot.send(command)

            # Після кожної команди очікується коротка текстова відповідь.
            answer = robot.recv()

        # Статус у форматі "команда -> відповідь" показує, що саме було відправлено.
        set_status(f"{command} -> {answer}")

    except Exception as error:
        # Помилка не зупиняє програму, а тільки виводиться у рядок стану.
        set_status(f"Помилка: {error}")


def send_command_async(command: str) -> None:
    """Надсилання команди в окремому потоці, щоб вікно Tkinter не зависало."""

    # WebSocket може чекати мережеву відповідь, тому команда запускається не в головному потоці.
    threading.Thread(target=send_command, args=(command,), daemon=True).start()


def set_speed() -> None:
    """Взяти значення з повзунка і надіслати команду швидкості."""

    # Повзунок повертає число, яке додається до текстової команди speed:<value>.
    speed = speed_scale.get()
    send_command_async(f"speed:{speed}")


def repeat_move_loop() -> None:
    """Регулярно надсилати команду руху, доки вона лишається активною."""

    while True:
        # Беремо поточну команду з включеним блокуванням, щоб зміна зі stop_move() була коректною.
        with move_lock:
            command = active_move_command

        # Значення None означає, що кнопка руху відпущена і цикл можна завершити.
        if command is None:
            break

        # Повторне надсилання команди не дає роботу зупинити двигуни.
        send_command(command)

        # Коротка пауза обмежує частоту команд і залишає запас до аварійної зупинки.
        time.sleep(MOVE_REPEAT_SECONDS)


def start_move(command: str) -> None:
    """Почати рух у вибраному напрямку."""

    global active_move_command
    global move_thread

    # Напрямок зберігається як активна команда: forward, backward, left або right.
    with move_lock:
        active_move_command = command
        need_new_thread = move_thread is None or not move_thread.is_alive()

        # Новий потік потрібний тільки тоді, коли цикл повторення команд ще не працює.
        if need_new_thread:
            move_thread = threading.Thread(target=repeat_move_loop, daemon=True)
            move_thread.start()


def stop_move() -> None:
    """Зупинити робота командою stop."""

    global active_move_command

    # Значення None зупиняє цикл повторення команд руху.
    with move_lock:
        active_move_command = None

    # Команда stop надсилається при відпусканні кнопки руху або при натисканні кнопки "Стоп".
    send_command_async("stop")


def show_frame(frame) -> None:
    """Показати один відеокадр на полотні Tkinter."""

    # OpenCV повертає кадр як масив пікселів, а Tkinter напряму такий масив не показує.
    # Тому кадр спочатку кодується у PNG-зображення у пам'яті.
    ok, png = cv2.imencode(".png", frame)

    # Якщо кодування не вдалося, кадр пропускається без зупинки відео.
    if not ok:
        return

    # Метод PhotoImage приймає байти PNG у форматі base64.
    data = base64.b64encode(png.tobytes())
    image = tk.PhotoImage(data=data)

    # frame.shape має формат: висота, ширина, кількість каналів кольору. Зберігаємо висоту і ширину кадру
    height, width = frame.shape[:2]

    # Розмір полотна підлаштовується під реальну роздільну здатність відео.
    # Завдяки цьому кадр не обрізається і не стискається.
    video_canvas.config(width=width, height=height, scrollregion=(0, 0, width, height))

    # Старий кадр видаляється, після чого новий кадр малюється з лівого верхнього кута.
    video_canvas.delete("all")
    video_canvas.create_image(0, 0, anchor="nw", image=image)

    # Зберігаємо посилання, інакше Tkinter може прибрати зображення з пам'яті.
    video_canvas.image = image


def video_loop() -> None:
    """Читати MJPEG-відеопотік через OpenCV і передавати кадри у Tkinter."""

    global video_running

    # OpenCV сам читає MJPEG-потік за HTTP.
    # Це найкоротший варіант: передати URL у VideoCapture і читати кадри методом read().
    video = cv2.VideoCapture(get_stream_url())

    # Якщо потік не відкрився, прапорець відео вимикається і показується повідомлення.
    if not video.isOpened():
        video_running = False
        root.after(0, set_status, "Не вдалося відкрити відео")
        return

    while video_running:
        # Метод read() повертає прапорець успіху і поточний кадр відео.
        ok, frame = video.read()

        # Якщо кадр не прочитався, цикл завершується.
        if not ok:
            break

        # root.after(...) передає оновлення інтерфейсу назад у головний потік Tkinter.
        root.after(0, show_frame, frame)

    # Після зупинки звільняємо ресурс камери або HTTP-потоку.
    video.release()

    # Стан відео синхронізуємо з кнопками і повідомленням у вікні.
    video_running = False
    root.after(0, set_status, "Відео зупинено")


def start_video() -> None:
    """Запустити читання відео в окремому потоці."""

    global video_running
    global video_thread

    # Повторний запуск не потрібний, якщо відео вже читається.
    if video_running:
        return

    # Вмикаємо прапорець активного відео, створюємо фоновий потік і запускаємо цикл читання кадрів.
    video_running = True
    video_thread = threading.Thread(target=video_loop, daemon=True)
    video_thread.start()
    set_status("Відео запущено")


def stop_video() -> None:
    """Попросити відеопотік зупинитися."""

    global video_running

    # Сам цикл video_loop побачить False і завершиться після поточного read().
    video_running = False
    set_status("Відео зупинено")


def close_app() -> None:
    """Зупинити робота, закрити WebSocket і завершити програму."""

    global active_move_command
    global robot
    global video_running

    # Вимикаємо цикл повторного надсилання команд руху.
    with move_lock:
        active_move_command = None

    # Спочатку зупиняємо читання відео, щоб фоновий потік завершився.
    video_running = False

    try:
        # При закритті вікна намагаємось зупинити двигуни робота.
        send_command("stop")
    except Exception:
        # Закриття програми має продовжитись навіть якщо stop не вдалося надіслати.
        pass

    with robot_lock:
        # Закриваємо WebSocket-канал, якщо він був відкритий.
        if robot is not None:
            robot.close()
            robot = None

    # Після звільнення ресурсів закриваємо головне вікно.
    root.destroy()


# Створення головного вікна Tkinter.
root = tk.Tk()
root.title("Simple Robot Demo")

# Верхній рядок: IP-адреса робота, підключення і керування статусом відео.
top_frame = tk.Frame(root)
top_frame.pack(padx=10, pady=10, fill="x")

# Напис перед полем введення пояснює, яку адресу потрібно ввести.
tk.Label(top_frame, text="IP ESP32-CAM:").pack(side="left")

# Поле введення містить DEFAULT_IP, але значення можна змінити перед підключенням.
ip_entry = tk.Entry(top_frame, width=18)
ip_entry.insert(0, DEFAULT_IP)
ip_entry.pack(side="left", padx=5)

# Кнопка підключення створює WebSocket і перевіряє його командою ping.
connect_button = tk.Button(top_frame, text="Підключитися", command=connect_robot)
connect_button.pack(side="left", padx=5)

# Окремі кнопки запускають і зупиняють читання MJPEG-потоку.
video_button = tk.Button(top_frame, text="Запустити відео", command=start_video)
video_button.pack(side="left", padx=5)

stop_video_button = tk.Button(top_frame, text="Зупинити відео", command=stop_video)
stop_video_button.pack(side="left", padx=5)

# Окремий рядок для вибору швидкості двигунів.
speed_frame = tk.Frame(root)
speed_frame.pack(padx=10, pady=5, fill="x")

tk.Label(speed_frame, text="Швидкість:").pack(side="left")

# Повзунок обмежує швидкість діапазоном, який очікує прошивка робота.
speed_scale = tk.Scale(
    speed_frame,
    from_=85,
    to=255,
    orient="horizontal",
)
speed_scale.set(DEFAULT_SPEED)
speed_scale.pack(side="left", padx=5)

# Кнопка надсилає поточне значення повзунка як команду speed:<value>.
speed_button = tk.Button(speed_frame, text="Встановити швидкість", command=set_speed)
speed_button.pack(side="left", padx=5)

# Центральний блок кнопок руху.
buttons_frame = tk.Frame(root)
buttons_frame.pack(padx=10, pady=10)

# Кнопки створюються окремо, щоб нижче прив'язати до них натискання і відпускання.
forward_button = tk.Button(buttons_frame, text="Вперед", width=12)
backward_button = tk.Button(buttons_frame, text="Назад", width=12)
left_button = tk.Button(buttons_frame, text="Ліворуч", width=12)
right_button = tk.Button(buttons_frame, text="Праворуч", width=12)
stop_button = tk.Button(buttons_frame, text="Стоп", width=12, command=stop_move)

# Метод grid розміщує кнопки у трьох рядках і трьох колонках.
forward_button.grid(row=0, column=1, padx=5, pady=5)
left_button.grid(row=1, column=0, padx=5, pady=5)
stop_button.grid(row=1, column=1, padx=5, pady=5)
right_button.grid(row=1, column=2, padx=5, pady=5)
backward_button.grid(row=2, column=1, padx=5, pady=5)

# Натискання кнопки запускає регулярне повторення команди руху.
# Відпускання кнопки зупиняє повторення і одразу надсилає stop.
forward_button.bind("<ButtonPress-1>", lambda event: start_move("forward"))
forward_button.bind("<ButtonRelease-1>", lambda event: stop_move())

backward_button.bind("<ButtonPress-1>", lambda event: start_move("backward"))
backward_button.bind("<ButtonRelease-1>", lambda event: stop_move())

left_button.bind("<ButtonPress-1>", lambda event: start_move("left"))
left_button.bind("<ButtonRelease-1>", lambda event: stop_move())

right_button.bind("<ButtonPress-1>", lambda event: start_move("right"))
right_button.bind("<ButtonRelease-1>", lambda event: stop_move())

# Додаткові команди: включення/вимкнення світлодіода і перевірка зв'язку.
extra_frame = tk.Frame(root)
extra_frame.pack(padx=10, pady=5)

# Ці кнопки напряму надсилають короткі WebSocket-команди.
tk.Button(
    extra_frame,
    text="LED ON",
    command=lambda: send_command_async("led:on"),
).pack(side="left", padx=5)
tk.Button(
    extra_frame,
    text="LED OFF",
    command=lambda: send_command_async("led:off"),
).pack(side="left", padx=5)
tk.Button(
    extra_frame,
    text="Ping",
    command=lambda: send_command_async("ping"),
).pack(side="left", padx=5)

# Полотно для відео спочатку має типовий розмір, а потім підлаштовується під розмір кадру.
video_canvas = tk.Canvas(
    root,
    width=640,
    height=480,
    bg="black",
    highlightthickness=0,
)
video_canvas.pack(padx=10, pady=10)

# Початковий напис зникає після появи першого відеокадру.
video_canvas.create_text(320, 240, text="Відео не запущено", fill="white")

# Нижній рядок стану показує останню дію або помилку.
status_label = tk.Label(root, text="Вкажіть IP і натисніть «Підключитися».", anchor="w")
status_label.pack(padx=10, pady=5, fill="x")

# Обробник закриття вікна, який потрібний, щоб надіслати stop перед виходом.
root.protocol("WM_DELETE_WINDOW", close_app)

# mainloop запускає цикл обробки подій Tkinter.
root.mainloop()