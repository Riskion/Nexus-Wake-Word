@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Speech recognition is not installed yet.
  echo Please run Install_Nexus_Speech.bat first.
  pause
  exit /b 1
)
rem Add pip-installed CUDA runtime DLL folders to PATH for faster-whisper.
for /d %%D in ("%CD%\.venv\Lib\site-packages\nvidia\cublas\bin") do if exist "%%~D" set "PATH=%%~D;%PATH%"
for /d %%D in ("%CD%\.venv\Lib\site-packages\nvidia\cudnn\bin") do if exist "%%~D" set "PATH=%%~D;%PATH%"
".venv\Scripts\python.exe" note.py
if errorlevel 1 (
  echo.
  echo Nexus closed with an error. Check the message above.
  pause
)
