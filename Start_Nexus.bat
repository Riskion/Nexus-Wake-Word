@echo off
setlocal
title Desktop Sticky Note
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py -3 note.py
    if not errorlevel 1 goto :end
)

where python >nul 2>nul
if not errorlevel 1 (
    python note.py
    if not errorlevel 1 goto :end
)

echo.
echo Python 3 was not found. Install Python 3 from https://www.python.org/downloads/windows/
echo Then run this file again.
pause

:end
endlocal
