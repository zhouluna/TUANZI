@echo off
setlocal
cd /d "%~dp0"
if not exist ".build-venv\Scripts\python.exe" (
    python -m venv .build-venv
    if errorlevel 1 goto failed
)
".build-venv\Scripts\python.exe" -m pip install -r packaging\requirements-build.txt --index-url https://pypi.org/simple
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" scripts\build_release.py
if errorlevel 1 goto failed
echo.
echo Release packages are ready in the release folder.
pause
exit /b 0
:failed
echo Build failed. See the error above. Python 3.10 or newer is required on the BUILD computer.
pause
exit /b 1
