
@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Nexus - Install Speech Recognition

echo ============================================================
echo   NEXUS - LOCAL SPEECH RECOGNITION INSTALLER
echo ============================================================
echo.
echo This installs a private local speech recognizer in this folder.
echo First model use downloads the Whisper model (about 1-2 GB).
echo Internet is needed for installation and the first model download.
echo After the model is downloaded, transcription can run offline.
echo.

where py >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python launcher not found. Install Python 3.11 x64 first.
  echo Make sure the Python Launcher is enabled during installation.
  pause
  exit /b 1
)

py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.11 was not found. This app requires Python 3.11 x64.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating a separate virtual environment...
  py -3.11 -m venv .venv
  if errorlevel 1 goto failed
)

echo Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed

echo Installing speech recognition and microphone packages...
".venv\Scripts\python.exe" -m pip install faster-whisper sounddevice numpy pillow pygame nvidia-cublas-cu12 nvidia-cudnn-cu12
if errorlevel 1 goto failed

echo.
echo Adding Nexus to Windows startup...

if not exist "Start_Nexus.vbs" (
  echo ERROR: Start_Nexus.vbs was not found.
  goto failed
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { $startup=[Environment]::GetFolderPath('Startup'); $ws=New-Object -ComObject WScript.Shell; $shortcut=$ws.CreateShortcut((Join-Path $startup 'Nexus.lnk')); $shortcut.TargetPath=(Join-Path $PWD.Path 'Start_Nexus.vbs'); $shortcut.WorkingDirectory=$PWD.Path; $shortcut.Save(); exit 0 } catch { Write-Host $_; exit 1 }"

if errorlevel 1 (
  echo ERROR: Could not add Nexus to Windows startup.
  goto failed
)

echo.
echo ============================================================
echo Installation complete.
echo Nexus will now start automatically when you sign in to Windows.
echo You can also start it manually using Start_Nexus.vbs.
echo ============================================================
pause
exit /b 0

:failed
echo.
echo INSTALLATION FAILED. The error above should indicate the cause.
echo Check your internet connection and try running this file again.
pause
exit /b 1
