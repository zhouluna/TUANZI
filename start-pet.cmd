@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run setup-pet.cmd first.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" -m desktop_pet
