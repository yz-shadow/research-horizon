@echo off
setlocal
if not exist "%~dp0.runtime\ollama\ollama.exe" (
    echo Please run setup_local.py first.
    exit /b 1
)
set "OLLAMA_HOST=127.0.0.1:11434"
set "OLLAMA_MODELS=%~dp0.runtime\models"
set "USERPROFILE=%~dp0.runtime\profile"
"%~dp0.runtime\ollama\ollama.exe" %*
