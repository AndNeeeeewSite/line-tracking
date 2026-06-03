import tkinter as tk


def build_window():
    root = tk.Tk()
    root.title("Line Track Demo")

    video_canvas = tk.Canvas(
        root,
        width=640,
        height=480,
        bg="black",
        highlightthickness=0,
    )
    video_canvas.pack(padx=10, pady=10)

    return root, video_canvas
