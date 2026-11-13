@echo off
rem Starts MyCat without a console window. Needs Python 3.10 or newer, which is free.
where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%~dp0MyCat.pyw"
    exit /b 0
)
rem Python from python.org is not always on the PATH, but its launcher is.
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw "%~dp0MyCat.pyw"
    exit /b 0
)
rem No Python on this computer yet: show how to get it (English, Russian, Uzbek).
if exist "%~dp0HOW TO START.txt" (
    start "" notepad "%~dp0HOW TO START.txt"
    exit /b 1
)
echo Python was not found. Install it from the Microsoft Store or python.org, then try again.
pause
exit /b 1
