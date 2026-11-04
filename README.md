# AutoClicker ⚡

A fast, lightweight auto-clicker for Windows. Single 12 MB portable executable, no runtime dependencies
(everything is handled natively through the Win32 API).

## Run it

Just double-click **`dist\AutoClicker.exe`** — no installation, no Python required.

## What it does

| Feature | Details |
| --- | --- |
| Click interval | Hours / minutes / seconds / milliseconds, down to 1 ms, with optional random jitter (± ms) |
| Mouse button | Left, right, or middle |
| Click type | Single or double click |
| Click repeat | Until you stop it, or a fixed number of clicks |
| Cursor position | Current cursor position, or a fixed screen coordinate (captured with the "Capture cursor position in 3 s" button) |
| Global hotkey | Start/stop from *any* application (default **F6**). Configure your own — function keys, or anything combined with Ctrl/Alt/Shift |
| Always on top | Toggleable, so the window stays visible while you work |
| Session counter | Live click counter with a reset button |
| Settings | Saved automatically to `%APPDATA%\AutoClicker\settings.json` |
| Single instance | Launching a second copy just focuses the existing window |

## Using it

1. Set your interval, button, click type, repeat mode and cursor position.
2. Press **START** (or hit the global hotkey, default `F6`). The **STOP** button activates while clicks are running; **START** re-enables when they stop.
3. The button turns into **STOP**, the status indicator goes green, and clicks are injected at the OS level.
4. Press the hotkey again (or **STOP**) to stop.

### Choosing a fixed position

Select **Fixed position**, then click *“Capture cursor position in 3 s”*. Move the mouse to where you want the
clicks to land before the countdown ends — the coordinates are captured automatically.

### Changing the hotkey

Click the hotkey button. Press any function key (`F1`–`F24`), `Pause`, `ScrollLock` or `PrtSc`,
or any key combined with `Ctrl`/`Alt`/`Shift`. Bare letter/number keys are rejected so the hotkey
can never swallow your normal typing. If a combination is already taken by another app, you'll be notified.

## Build from source

Requires Python 3.x on Windows.

```bat
build.bat
```

This regenerates `icon.ico`, then runs PyInstaller and produces `dist\AutoClicker.exe`.
(`build.bat` assumes `pyinstaller` is installed: `pip install pyinstaller`)

Manual build:

```bat
python generate_icon.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoClicker --icon icon.ico --add-data "icon.ico;." autoclicker.py
```

## Notes

- Clicks are injected with `SendInput`, i.e. identical to real hardware input.
- 1 ms intervals run as fast as the OS and target application will consume them.
- Please respect the terms of service of the software/games you use it on.
