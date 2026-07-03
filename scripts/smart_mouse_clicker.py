import ctypes
import random
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

VK_F8 = 0x77
VK_F9 = 0x78


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


@dataclass
class ClickSettings:
    interval_seconds: float
    jitter_seconds: float
    idle_only: bool
    idle_seconds: float
    click_button: str
    double_click: bool
    use_fixed_position: bool
    fixed_x: int
    fixed_y: int


def get_cursor_position():
    point = POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def get_idle_seconds():
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    user32.GetLastInputInfo(ctypes.byref(info))
    elapsed_ms = kernel32.GetTickCount() - info.dwTime
    return max(0, elapsed_ms / 1000)


def key_pressed(vk_code):
    return bool(user32.GetAsyncKeyState(vk_code) & 1)


def perform_click(button_name, double_click=False):
    if button_name == "Left":
        down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif button_name == "Right":
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    else:
        down, up = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP

    repeat = 2 if double_click else 1
    for _ in range(repeat):
        user32.mouse_event(down, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.08)


class SmartClickerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Mouse Clicker")
        self.root.resizable(False, False)

        self.running = False
        self.worker = None
        self.stop_event = threading.Event()
        self.next_click_at = None
        self.click_count = 0
        self.last_hotkey_action = 0

        self.interval_minutes = tk.DoubleVar(value=5)
        self.jitter_seconds = tk.DoubleVar(value=15)
        self.idle_only = tk.BooleanVar(value=True)
        self.idle_seconds = tk.DoubleVar(value=30)
        self.click_button = tk.StringVar(value="Left")
        self.double_click = tk.BooleanVar(value=False)
        self.use_fixed_position = tk.BooleanVar(value=False)
        self.fixed_x = tk.IntVar(value=0)
        self.fixed_y = tk.IntVar(value=0)

        self.status_text = tk.StringVar(value="Ready. F8 starts/stops, F9 quits.")
        self.countdown_text = tk.StringVar(value="Next click: -")
        self.clicks_text = tk.StringVar(value="Clicks: 0")

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.tick()

    def build_ui(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        interval_frame = ttk.LabelFrame(frame, text="Timing", padding=10)
        interval_frame.grid(row=0, column=0, sticky="ew")

        ttk.Label(interval_frame, text="Interval (minutes)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            interval_frame,
            from_=0.1,
            to=240,
            increment=0.5,
            textvariable=self.interval_minutes,
            width=10,
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))

        ttk.Label(interval_frame, text="Random jitter (+/- seconds)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(
            interval_frame,
            from_=0,
            to=300,
            increment=5,
            textvariable=self.jitter_seconds,
            width=10,
        ).grid(row=1, column=1, sticky="e", padx=(12, 0), pady=(8, 0))

        idle_frame = ttk.LabelFrame(frame, text="Safety", padding=10)
        idle_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        ttk.Checkbutton(
            idle_frame,
            text="Click only after the computer has been idle",
            variable=self.idle_only,
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(idle_frame, text="Required idle time (seconds)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(
            idle_frame,
            from_=0,
            to=3600,
            increment=5,
            textvariable=self.idle_seconds,
            width=10,
        ).grid(row=1, column=1, sticky="e", padx=(12, 0), pady=(8, 0))

        click_frame = ttk.LabelFrame(frame, text="Click", padding=10)
        click_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        ttk.Label(click_frame, text="Button").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            click_frame,
            values=("Left", "Right", "Middle"),
            textvariable=self.click_button,
            state="readonly",
            width=12,
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))

        ttk.Checkbutton(click_frame, text="Double click", variable=self.double_click).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 0),
        )

        position_frame = ttk.LabelFrame(frame, text="Position", padding=10)
        position_frame.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        ttk.Checkbutton(
            position_frame,
            text="Always click a fixed position",
            variable=self.use_fixed_position,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(position_frame, text="X").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(position_frame, from_=0, to=9999, textvariable=self.fixed_x, width=8).grid(
            row=1,
            column=1,
            sticky="w",
            padx=(6, 12),
            pady=(8, 0),
        )
        ttk.Label(position_frame, text="Y").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Spinbox(position_frame, from_=0, to=9999, textvariable=self.fixed_y, width=8).grid(
            row=1,
            column=3,
            sticky="w",
            padx=(6, 0),
            pady=(8, 0),
        )

        ttk.Button(position_frame, text="Use current mouse position", command=self.capture_position).grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="ew",
            pady=(10, 0),
        )

        controls = ttk.Frame(frame)
        controls.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)

        self.start_button = ttk.Button(controls, text="Start", command=self.start)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.stop_button = ttk.Button(controls, text="Stop", command=self.stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(frame, textvariable=self.status_text).grid(row=5, column=0, sticky="w", pady=(12, 0))
        ttk.Label(frame, textvariable=self.countdown_text).grid(row=6, column=0, sticky="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.clicks_text).grid(row=7, column=0, sticky="w", pady=(4, 0))

        for child in frame.winfo_children():
            child.grid_configure(padx=0)

    def capture_position(self):
        x, y = get_cursor_position()
        self.fixed_x.set(x)
        self.fixed_y.set(y)
        self.use_fixed_position.set(True)
        self.status_text.set(f"Captured position: {x}, {y}")

    def read_settings(self):
        interval = max(1, float(self.interval_minutes.get()) * 60)
        jitter = max(0, float(self.jitter_seconds.get()))
        idle_seconds = max(0, float(self.idle_seconds.get()))
        return ClickSettings(
            interval_seconds=interval,
            jitter_seconds=jitter,
            idle_only=bool(self.idle_only.get()),
            idle_seconds=idle_seconds,
            click_button=self.click_button.get(),
            double_click=bool(self.double_click.get()),
            use_fixed_position=bool(self.use_fixed_position.get()),
            fixed_x=int(self.fixed_x.get()),
            fixed_y=int(self.fixed_y.get()),
        )

    def start(self):
        if self.running:
            return
        try:
            settings = self.read_settings()
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.running = True
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_text.set("Running. Move mouse to top-left corner to stop.")
        self.worker = threading.Thread(target=self.run_clicker, args=(settings,), daemon=True)
        self.worker.start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.stop_event.set()
        self.next_click_at = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_text.set("Stopped.")
        self.countdown_text.set("Next click: -")

    def quit_app(self):
        self.stop()
        self.root.destroy()

    def run_clicker(self, settings):
        while not self.stop_event.is_set():
            delay = settings.interval_seconds + random.uniform(-settings.jitter_seconds, settings.jitter_seconds)
            delay = max(1, delay)
            self.next_click_at = time.time() + delay

            if self.stop_event.wait(delay):
                break

            if settings.idle_only and get_idle_seconds() < settings.idle_seconds:
                self.root.after(0, self.status_text.set, "Skipped: computer was not idle enough.")
                continue

            x, y = get_cursor_position()
            if x <= 2 and y <= 2:
                self.root.after(0, self.stop)
                self.root.after(0, self.status_text.set, "Stopped by top-left safety corner.")
                break

            if settings.use_fixed_position:
                user32.SetCursorPos(settings.fixed_x, settings.fixed_y)
                time.sleep(0.05)

            perform_click(settings.click_button, settings.double_click)
            self.click_count += 1
            self.root.after(0, self.clicks_text.set, f"Clicks: {self.click_count}")
            self.root.after(0, self.status_text.set, time.strftime("Last click: %H:%M:%S"))

    def tick(self):
        if key_pressed(VK_F8):
            if self.running:
                self.stop()
            else:
                self.start()

        if key_pressed(VK_F9):
            self.quit_app()
            return

        if self.running and self.next_click_at:
            remaining = max(0, int(self.next_click_at - time.time()))
            minutes, seconds = divmod(remaining, 60)
            self.countdown_text.set(f"Next click: {minutes:02d}:{seconds:02d}")

        self.root.after(250, self.tick)


def main():
    root = tk.Tk()
    SmartClickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
