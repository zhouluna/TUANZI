@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt --index-url https://pypi.org/simple
if errorlevel 1 goto failed
call start-pet.cmd
exit /b 0
:failed
echo Setup failed. See the error above.
pause
exit /b 1
