# robot_client.py
import threading
import queue
import time
from websocket import create_connection
from config import DEFAULT_IP, COMMAND_REPEAT_INTERVAL

class Esp32RobotClient:
    def __init__(self, ip: str = DEFAULT_IP):
        self.ip = ip
        self.ws_url = f"ws://{ip}/ws"
        self.robot = None
        self.lock = threading.Lock()
        
        self.cmd_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread = None
        
        self.current_speed = None
        self.last_move_command = None
        self.current_move_command = None
        self.last_move_command_time = 0.0

    def connect(self) -> bool:
        with self.lock:
            try:
                if self.robot is not None:
                    self.robot.close()
                print(f"Подключение к {self.ws_url}...")
                self.robot = create_connection(self.ws_url, timeout=2)
                self.robot.send("ping")
                answer = self.robot.recv()
                print(f"Ответ робота: {answer}")
                
                self.stop_event.clear()
                self.worker_thread = threading.Thread(target=self._queue_worker, daemon=True)
                self.worker_thread.start()
                return True
            except Exception as e:
                print(f"Ошибка подключения: {e}")
                self.robot = None
                return False

    def _queue_worker(self):
        while not self.stop_event.is_set():
            try:
                command = self.cmd_queue.get(timeout=0.05)
            except queue.Empty:
                command = None

            now = time.time()
            if command is None:
                with self.lock:
                    if self.robot is not None and self.current_move_command is not None:
                        if now - self.last_move_command_time >= COMMAND_REPEAT_INTERVAL:
                            try:
                                self.robot.send(self.current_move_command)
                                _ = self.robot.recv()
                                self.last_move_command_time = now
                            except:
                                pass
                continue
                
            with self.lock:
                if self.robot is not None:
                    try:
                        self.robot.send(command)
                        _ = self.robot.recv()
                        if command in ("forward", "left", "right", "backward"):
                            self.current_move_command = command
                            self.last_move_command_time = now
                        elif command == "stop":
                            self.current_move_command = None
                    except:
                        pass
            self.cmd_queue.task_done()

    def send_command_async(self, command: str):
        self.cmd_queue.put(command)

    def set_speed(self, speed: int):
        target_speed = max(85, min(int(speed), 255))
        if self.current_speed != target_speed:
            self.current_speed = target_speed
            self.send_command_async(f"speed:{target_speed}")

    def move_forward(self, speed: int):
        self.set_speed(speed)
        if self.last_move_command != "forward":
            self.last_move_command = "forward"
            self.send_command_async("forward")

    def move_left(self, speed: int):
        self.set_speed(speed)
        if self.last_move_command != "left":
            self.last_move_command = "left"
            self.send_command_async("left")

    def move_right(self, speed: int):
        self.set_speed(speed)
        if self.last_move_command != "right":
            self.last_move_command = "right"
            self.send_command_async("right")

    def move_backward(self, speed: int):
        self.set_speed(speed)
        if self.last_move_command != "backward":
            self.last_move_command = "backward"
            self.send_command_async("backward")

    def stop(self):
        self.last_move_command = "stop"
        self.current_speed = None
        while not self.cmd_queue.empty():
            try: self.cmd_queue.get_nowait()
            except: pass
        self.send_command_async("stop")

    def disconnect(self):
        self.stop_event.set()
        if self.worker_thread:
            self.worker_thread.join(timeout=1)
        with self.lock:
            if self.robot:
                try:
                    self.robot.send("stop")
                    _ = self.robot.recv()
                except: pass
                self.robot.close()
                self.robot = None   