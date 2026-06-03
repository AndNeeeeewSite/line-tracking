from robot import connect_robot, send_command, close_robot, get_stream_url
from ui import build_window
from vision import start_video, stop_video


def close_app(root):
    stop_video()

    try:
        send_command("stop")
    except Exception:
        pass

    close_robot()
    root.destroy()


def main():
    root, video_canvas = build_window()
    root.protocol("WM_DELETE_WINDOW", lambda: close_app(root))

    connect_robot()
    start_video(video_canvas, root, get_stream_url())

    root.mainloop()


if __name__ == "__main__":
    main()
