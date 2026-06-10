# robot_client.py
import threading
from websocket import create_connection
from config import DEFAULT_IP

class Esp32RobotClient:
    def __init__(self, ip: str = DEFAULT_IP):
        self.ip = ip
        self.ws_url = f"ws://{ip}/ws"
        self.robot = None
        self.lock = threading.Lock()
        self.current_speed = None
        
        # Храним последнюю отправленную команду движения, чтобы не спамить сокет
        self.last_move_command = None 

    def connect(self) -> bool:
        """Синхронное подключение при старте приложения"""
        with self.lock:
            try:
                if self.robot is not None:
                    self.robot.close()
                print(f"Подключение к {self.ws_url}...")
                self.robot = create_connection(self.ws_url, timeout=2)
                self.robot.send("ping")
                answer = self.robot.recv()
                print(f"Ответ робота: {answer}")
                return True
            except Exception as e:
                print(f"Ошибка подключения: {e}")
                self.robot = None
                return False

    def _send_command_sync(self, command: str):
        """Внутренний метод для отправки. Вызывается ТОЛЬКО внутри отдельного потока."""
        if self.robot is None:
            return
        
        # Блокировка нужна, чтобы разные потоки не писали в сокет одновременно
        with self.lock:
            try:
                self.robot.send(command)
                # Вычитываем ответ, чтобы очистить буфер сокета, 
                # но теперь это происходит в фоне и не вешает главный поток управления
                _ = self.robot.recv() 
            except Exception as e:
                print(f"[Ошибка отправки в потоке]: {e}")

    def send_command_async(self, command: str):
        """Асинхронный запуск отправки команды в отдельном независимом потоке"""
        threading.Thread(target=self._send_command_sync, args=(command,), daemon=True).start()

    def set_speed(self, speed: int):
        """Установка скорости робота (85-255) без блокировки"""
        target_speed = max(85, min(int(speed), 255))
        if self.current_speed != target_speed:
            self.current_speed = target_speed
            self.send_command_async(f"speed:{target_speed}")

    def move_forward(self):
        if self.last_move_command != "forward":
            self.last_move_command = "forward"
            self.send_command_async("forward")

    def move_left(self):
        if self.last_move_command != "left":
            self.last_move_command = "left"
            self.send_command_async("left")

    def move_right(self):
        if self.last_move_command != "right":
            self.last_move_command = "right"
            self.send_command_async("right")

    def move_backward(self):
        if self.last_move_command != "backward":
            self.last_move_command = "backward"
            self.send_command_async("backward")

    def stop(self):
        if self.last_move_command != "stop":
            self.last_move_command = "stop"
            self.send_command_async("stop")

    def disconnect(self):
        """Корректное закрытие сокета"""
        # Сбрасываем флаг команд
        self.last_move_command = None
        with self.lock:
            if self.robot:
                try:
                    self.robot.send("stop")
                    _ = self.robot.recv()
                except: pass
                self.robot.close()
                self.robot = None
                print("[WS] Соединение закрыто.")