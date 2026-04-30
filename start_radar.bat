@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Razgrom Sonic Radar - Accessibility Overlay
color 0A
cls

echo.
if exist "%~dp0assets\banner.txt" (
    type "%~dp0assets\banner.txt"
) else (
    echo RAZGROM SONIC RADAR
)
echo.
echo   [Accessibility mode] No injection, no game memory access.
echo   Select OUTPUT LOOPBACK for game audio isolation.
echo.

cd /d "%~dp0"

if not exist "Overlay\main_overlay.py" (
    echo [ERROR] Overlay\main_overlay.py was not found.
    echo Run this file from the Razgrom-Sonic-Radar folder.
    pause
    exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
    goto :finish
)

where python >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=python"
    goto :finish
)

echo [ERROR] Python was not found in PATH.
echo Install Python 3.10+ or run the packaged EXE from dist.
pause
exit /b 1

:finish
echo Checking Python dependencies...
%PYTHON_CMD% -c "import tkinter, numpy, soundcard, scipy" >nul 2>nul
if not %errorlevel%==0 (
    echo Installing missing dependencies from requirements.txt...
    %PYTHON_CMD% -m pip install --user -r requirements.txt
    if not %errorlevel%==0 (
        echo.
        echo [ERROR] Dependency installation failed.
        echo Try manually: %PYTHON_CMD% -m pip install --user -r requirements.txt
        pause
        exit /b 1
    )
)

echo Starting overlay...
%PYTHON_CMD% Overlay\main_overlay.py
if not %errorlevel%==0 (
    echo.
    echo [ERROR] Overlay exited with an error.
    if exist "overlay_debug.txt" (
        echo.
        echo Last debug log lines:
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Tail 20 'overlay_debug.txt'"
    )
)

echo.
echo Razgrom Sonic Radar closed.
pause
