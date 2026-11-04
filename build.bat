@echo off
setlocal
cd /d "%~dp0"

echo === Generating icon ===
python generate_icon.py || goto :fail

echo === Building AutoClicker.exe ===
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name AutoClicker ^
  --icon icon.ico ^
  --add-data "icon.ico;." ^
  autoclicker.py || goto :fail

echo.
echo Done! Executable is at: %~dp0dist\AutoClicker.exe
exit /b 0

:fail
echo Build failed.
exit /b 1
