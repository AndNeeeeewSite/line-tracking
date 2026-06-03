from websocket import create_connection
import threading

robot = None
robot_lock = threading.Lock()

get_ip_req = 0

if get_ip_req:
    get_ip = input("Введіть IP-адресу робота: ")
else:
    get_ip = "10.1.66.72".strip()


def get_stream_url() -> str:
    return f"http://{get_ip}:81/stream"


def get_ws_url() -> str:
    return f"ws://{get_ip}/ws"


def connect_robot() -> None:
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

def send_command_async(command: str) -> None:
    """Надсилання команди в окремому потоці, щоб вікно Tkinter не зависало."""

    # WebSocket може чекати мережеву відповідь, тому команда запускається не в головному потоці.
    threading.Thread(target=send_command, args=(command,), daemon=True).start()

def set_speed() -> None:
    """Взяти значення з повзунка і надіслати команду швидкості."""

    # Повзунок повертає число, яке додається до текстової команди speed:<value>.
    speed = 170
    send_command_async(f"speed:{speed}")

def close_robot() -> None:
    global robot
    with robot_lock:
        if robot is not None:
            robot.close()
            robot = None

set_speed()