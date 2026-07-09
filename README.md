# Smart Mouse Clicker V2

A Windows utility that clicks the mouse at a configurable interval.

## Features

- Start and stop from a simple desktop window
- Default click interval of five minutes
- Optional random timing jitter
- Left, right, middle, and double-click options
- Optional fixed screen position
- Multi-monitor, full-screen crosshair overlay for choosing the click location
- Optional idle-only mode
- Persistent settings stored privately in Windows app data
- `F8` toggles start/stop
- `F9` exits
- Moving the cursor to the top-left corner stops the clicker

## Run From Source

```powershell
py scripts\smart_mouse_clicker.py
```

If `py` is unavailable:

```powershell
python scripts\smart_mouse_clicker.py
```

## Build The Windows App

```powershell
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean --onefile --windowed --name "Smart Mouse Clicker V2" --icon "assets\clicker.ico" --add-data "assets\clicker-title-256.ico;assets" "scripts\smart_mouse_clicker.py"
```

The built app is created at:

```text
dist\Smart Mouse Clicker V2.exe
```

## Settings

The app saves timing and click preferences to `%LOCALAPPDATA%\Smart Mouse Clicker V2\config.json`, so no settings file appears beside the EXE.
The selected X,Y coordinate is intentionally not saved, so choose a fresh location each time the app opens.

## Included Files

- `scripts\smart_mouse_clicker.py` - main Python app
- `scripts\run_smart_mouse_clicker.bat` - convenience launcher
- `assets\clicker.ico` - original pointer-clicker app icon
- `assets\clicker-title-256.ico` - original 256px pointer-clicker title-bar icon
- `dist\Smart Mouse Clicker V2.exe` - built Windows executable
- `dist\Smart Mouse Clicker V2.zip` - zipped executable
