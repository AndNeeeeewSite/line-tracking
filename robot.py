from websocket import create_connection
import threading

robot = None
robot_lock = threading.Lock()
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


def close_robot() -> None:
    global robot
    with robot_lock:
        if robot is not None:
            robot.close()
            robot = None
