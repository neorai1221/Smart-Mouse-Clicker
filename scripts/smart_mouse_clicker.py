import ctypes
import json
import os
import sys
import random
import subprocess
import threading
import time
import tkinter as tk
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
PICKER_ARGUMENT = "--pick-location"
PICKER_MODE = PICKER_ARGUMENT in sys.argv


def enable_dpi_awareness():
    """Use stable DPI for the app and pixel-accurate DPI for the picker helper."""
    awareness_context = -4 if PICKER_MODE else -2
    shcore_awareness = 2 if PICKER_MODE else 1
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(awareness_context)):
            return
    except (AttributeError, OSError):
        pass

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(shcore_awareness)
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


enable_dpi_awareness()

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

VK_F8 = 0x77
VK_F9 = 0x78

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

APP_NAME = "Smart Mouse Clicker V2"
LEGACY_APP_NAME = "Smart Mouse Clicker"
WINDOW_PREFERRED_WIDTH = 430
WINDOW_WIDTH_RATIO = 0.14
WINDOW_MIN_WIDTH = 400
WINDOW_EDGE_MARGIN = 48
WINDOW_BOTTOM_MARGIN = 96
MONITOR_DEFAULTTONEAREST = 2

DEFAULT_CONFIG = {
    "interval_minutes": 5,
    "jitter_seconds": 15,
    "idle_only": True,
    "idle_seconds": 30,
    "click_button": "Left",
    "double_click": False,
}

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


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


def get_app_data_root():
    local_app_data = os.environ.get("LOCALAPPDATA")
    return Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"


def get_config_path():
    """Store preferences in the user's private Windows app-data folder."""
    return get_app_data_root() / APP_NAME / "config.json"


def get_legacy_config_paths():
    """Find previous settings locations so the V2 update keeps user preferences."""
    legacy_paths = [get_app_data_root() / LEGACY_APP_NAME / "config.json"]
    if getattr(sys, "frozen", False):
        legacy_paths.append(Path(sys.executable).resolve().with_name("config.json"))
    else:
        legacy_paths.append(Path(__file__).resolve().with_name("config.json"))
    return legacy_paths


def get_resource_path(relative_path):
    """Locate bundled files both in source mode and in a PyInstaller EXE."""
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_path / relative_path


def normalize_config(loaded):
    if not isinstance(loaded, dict):
        return DEFAULT_CONFIG.copy()

    config = DEFAULT_CONFIG.copy()
    for key in DEFAULT_CONFIG:
        if key in loaded:
            config[key] = loaded[key]
    return config


def read_config(config_path):
    if not config_path.exists():
        return None

    try:
        with config_path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    return normalize_config(loaded)


def write_config(config_path, config):
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as file:
            json.dump(config, file, indent=2)
    except OSError:
        return False
    return True


def load_config():
    config_path = get_config_path()
    saved_config = read_config(config_path)
    if saved_config is not None:
        return saved_config

    legacy_config_paths = get_legacy_config_paths()
    for legacy_config_path in legacy_config_paths:
        legacy_config = read_config(legacy_config_path)
        if legacy_config is None:
            continue

        # Move existing preferences out of old app locations after a successful copy.
        if write_config(config_path, legacy_config):
            for old_config_path in legacy_config_paths:
                try:
                    old_config_path.unlink()
                except OSError:
                    pass
        return legacy_config

    return DEFAULT_CONFIG.copy()


def get_monitor_bounds():
    """Return the actual bounds of every connected monitor in desktop pixels."""
    monitors = []
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(RECT),
        ctypes.c_void_p,
    )

    @callback_type
    def collect_monitor(monitor, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.rcMonitor
            monitors.append((rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
        return 1

    user32.EnumDisplayMonitors(None, None, collect_monitor, None)
    if monitors:
        return monitors

    # A conservative fallback for unusual Windows configurations.
    return [
        (
            user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
            user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
        )
    ]


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


class LocationPicker:
    """A short-lived per-monitor-DPI process dedicated to location selection."""

    def __init__(self, result_path):
        self.result_path = Path(result_path)
        self.root = tk.Tk()
        self.root.withdraw()
        self.overlays = []
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self.show_overlays()

    def show_overlays(self):
        for index, (x, y, width, height) in enumerate(get_monitor_bounds()):
            overlay = tk.Toplevel(self.root)
            self.overlays.append(overlay)
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            overlay.attributes("-alpha", 0.35)
            overlay.configure(bg="#6b7280", cursor="crosshair")
            overlay.geometry(f"{width}x{height}{x:+d}{y:+d}")
            overlay.bind("<Button-1>", self.capture_location)
            overlay.bind("<Escape>", self.cancel)

            if index == 0:
                hint = tk.Label(
                    overlay,
                    text="Click anywhere to choose the click location. Press Esc to cancel.",
                    bg="#374151",
                    fg="white",
                    font=("Segoe UI", 14),
                    padx=18,
                    pady=10,
                )
                hint.place(relx=0.5, rely=0.08, anchor="center")
                hint.bind("<Button-1>", self.capture_location)

        if self.overlays:
            self.overlays[0].focus_force()

    def capture_location(self, event):
        self.finish({"x": event.x_root, "y": event.y_root})

    def cancel(self, _event=None):
        self.finish({"cancelled": True})

    def finish(self, result):
        try:
            self.result_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.result_path.with_name(f"{self.result_path.name}.tmp")
            with temporary_path.open("w", encoding="utf-8") as file:
                json.dump(result, file)
            temporary_path.replace(self.result_path)
        except OSError:
            pass
        finally:
            for overlay in self.overlays:
                if overlay.winfo_exists():
                    overlay.destroy()
            self.root.destroy()

    def run(self):
        self.root.mainloop()


class SmartClickerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.config_path = get_config_path()
        self.saved_config = load_config()

        self.running = False
        self.worker = None
        self.stop_event = threading.Event()
        self.next_click_at = None
        self.click_count = 0
        self.last_hotkey_action = 0
        self.picker_process = None
        self.picker_result_path = None
        self.current_monitor = None
        self.monitor_resize_job = None
        self.settings_trace_ids = []

        self.interval_minutes = tk.DoubleVar(value=self.saved_config["interval_minutes"])
        self.jitter_seconds = tk.DoubleVar(value=self.saved_config["jitter_seconds"])
        self.idle_only = tk.BooleanVar(value=self.saved_config["idle_only"])
        self.idle_seconds = tk.DoubleVar(value=self.saved_config["idle_seconds"])
        self.click_button = tk.StringVar(value=self.saved_config["click_button"])
        self.double_click = tk.BooleanVar(value=self.saved_config["double_click"])
        self.use_fixed_position = tk.BooleanVar(value=False)
        self.fixed_x = tk.IntVar(value=0)
        self.fixed_y = tk.IntVar(value=0)
        self.position_text = tk.StringVar(value="No location selected")

        self.status_text = tk.StringVar(value="Ready. F8 starts/stops, F9 quits.")
        self.countdown_text = tk.StringVar(value="Next click: -")
        self.clicks_text = tk.StringVar(value="Clicks: 0")

        self.build_ui()
        self.size_window_to_content()
        self.root.bind("<Configure>", self.handle_monitor_change, add="+")
        self.root.after_idle(self.apply_window_icon, self.root)
        self.bind_setting_saves()
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.tick()

    def build_ui(self):
        self.root.columnconfigure(0, weight=1)
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)

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
        position_frame.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            position_frame,
            text="Always click a fixed position",
            variable=self.use_fixed_position,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(position_frame, text="Selected location").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(position_frame, textvariable=self.position_text).grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="w",
            padx=(12, 0),
            pady=(8, 0),
        )

        ttk.Button(position_frame, text="Choose Location", command=self.choose_location).grid(
            row=2,
            column=0,
            columnspan=3,
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

        ttk.Label(frame, textvariable=self.status_text).grid(row=5, column=0, sticky="w", pady=(10, 0))
        ttk.Label(frame, textvariable=self.countdown_text).grid(row=6, column=0, sticky="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.clicks_text).grid(row=7, column=0, sticky="w", pady=(4, 0))

        for child in frame.winfo_children():
            child.grid_configure(padx=0)

    def size_window_to_content(self):
        """Keep the compact layout within the current screen's usable area."""
        self.root.update_idletasks()
        monitor_width, monitor_height = self.get_current_monitor_size()
        max_width = max(400, monitor_width - WINDOW_EDGE_MARGIN)
        max_height = max(480, monitor_height - WINDOW_BOTTOM_MARGIN)
        preferred_width = min(
            WINDOW_PREFERRED_WIDTH,
            max(WINDOW_MIN_WIDTH, int(monitor_width * WINDOW_WIDTH_RATIO)),
        )
        width = min(max(self.root.winfo_reqwidth(), preferred_width), max_width)
        height = min(self.root.winfo_reqheight(), max_height)
        self.root.geometry(f"{width}x{height}")

    def get_current_monitor_size(self):
        monitor = user32.MonitorFromWindow(self.root.winfo_id(), MONITOR_DEFAULTTONEAREST)
        if monitor:
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                rect = info.rcMonitor
                return rect.right - rect.left, rect.bottom - rect.top
        return self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def handle_monitor_change(self, event):
        if event.widget is not self.root:
            return

        monitor = user32.MonitorFromWindow(self.root.winfo_id(), MONITOR_DEFAULTTONEAREST)
        if monitor == self.current_monitor:
            return

        self.current_monitor = monitor
        if self.monitor_resize_job is not None:
            self.root.after_cancel(self.monitor_resize_job)
        self.monitor_resize_job = self.root.after(200, self.size_window_to_content)

    @staticmethod
    def apply_window_icon(window):
        """Use the original 256px pointer icon without a lower-resolution fallback."""
        icon_path = str(get_resource_path("assets/clicker-title-256.ico"))
        try:
            window.iconbitmap(default=icon_path)
        except tk.TclError:
            pass

    def bind_setting_saves(self):
        for variable in (
            self.interval_minutes,
            self.jitter_seconds,
            self.idle_only,
            self.idle_seconds,
            self.click_button,
            self.double_click,
        ):
            trace_id = variable.trace_add("write", lambda *_: self.save_config())
            self.settings_trace_ids.append((variable, trace_id))

    def save_config(self):
        config = {
            "interval_minutes": self.safe_float(self.interval_minutes, DEFAULT_CONFIG["interval_minutes"]),
            "jitter_seconds": self.safe_float(self.jitter_seconds, DEFAULT_CONFIG["jitter_seconds"]),
            "idle_only": bool(self.idle_only.get()),
            "idle_seconds": self.safe_float(self.idle_seconds, DEFAULT_CONFIG["idle_seconds"]),
            "click_button": self.click_button.get() if self.click_button.get() in ("Left", "Right", "Middle") else "Left",
            "double_click": bool(self.double_click.get()),
        }

        if not write_config(self.config_path, config):
            self.status_text.set("Could not save settings.")

    @staticmethod
    def safe_float(variable, fallback):
        try:
            return float(variable.get())
        except (tk.TclError, ValueError):
            return fallback

    def choose_location(self):
        if self.picker_process is not None:
            return

        self.picker_result_path = Path(tempfile.gettempdir()) / f"smart_mouse_clicker_{uuid.uuid4().hex}.json"
        self.root.withdraw()
        self.status_text.set("Choose a location on any connected monitor.")
        try:
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command.append(str(Path(__file__).resolve()))
            command.extend([PICKER_ARGUMENT, str(self.picker_result_path)])
            self.picker_process = subprocess.Popen(command)
        except OSError:
            self.restore_after_picker()
            self.status_text.set("Could not open the location picker.")
            return

        self.root.after(100, self.poll_location_picker)

    def poll_location_picker(self):
        if self.picker_result_path and self.picker_result_path.exists():
            try:
                with self.picker_result_path.open("r", encoding="utf-8") as file:
                    result = json.load(file)
            except (OSError, json.JSONDecodeError):
                result = {"cancelled": True}
            finally:
                try:
                    self.picker_result_path.unlink()
                except OSError:
                    pass

            self.restore_after_picker()
            if "x" in result and "y" in result:
                self.set_position(int(result["x"]), int(result["y"]))
                self.status_text.set(f"Captured position: {result['x']}, {result['y']}")
            else:
                self.status_text.set("Location selection cancelled.")
            return

        if self.picker_process and self.picker_process.poll() is not None:
            self.restore_after_picker()
            self.status_text.set("Location selection closed without a selection.")
            return

        self.root.after(100, self.poll_location_picker)

    def restore_after_picker(self):
        self.picker_process = None
        self.picker_result_path = None
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def set_position(self, x, y):
        self.fixed_x.set(x)
        self.fixed_y.set(y)
        self.use_fixed_position.set(True)
        self.position_text.set(f"X: {x}   Y: {y}")

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

        self.save_config()

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
        self.save_config()
        self.stop()
        if self.picker_process and self.picker_process.poll() is None:
            self.picker_process.terminate()
        if self.picker_result_path:
            try:
                self.picker_result_path.unlink()
            except OSError:
                pass
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
    if PICKER_MODE:
        argument_index = sys.argv.index(PICKER_ARGUMENT)
        if argument_index + 1 >= len(sys.argv):
            raise SystemExit("Missing location-picker result path.")
        LocationPicker(sys.argv[argument_index + 1]).run()
        return

    root = tk.Tk()
    SmartClickerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
