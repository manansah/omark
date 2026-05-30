@echo off
setlocal

cd /d "%~dp0"

if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links" (
    set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
    goto :end
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 app.py
    goto :end
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python app.py
    goto :end
)

echo Python 3 was not found.
echo Install Python 3.10 or newer, then run this file again.
pause

:end
endlocal
