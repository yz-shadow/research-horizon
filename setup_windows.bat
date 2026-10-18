@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" setup_local.py
if errorlevel 1 goto failed
echo Setup complete. Open launch.py in PyCharm or run run.bat.
pause
exit /b 0
:failed
echo Setup failed. See the messages above. Python 3.10+ is required.
pause
exit /b 1
