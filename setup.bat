@echo off
chcp 65001 >nul
rem Setup launcher for Windows. Double-click to open the setup window.
rem The first run creates the virtual environment and installs the libraries.
cd /d "%~dp0"

echo Preparing the Moodle Assistant setup...

rem --- find Python (prefer the py launcher) ---
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY goto no_python

rem --- virtual environment ---
if exist "venv\Scripts\python.exe" goto venv_ok
echo First-time setup. This can take a few minutes...
%PY% -m venv venv
if errorlevel 1 goto venv_failed
:venv_ok
set "VENV_PY=%CD%\venv\Scripts\python.exe"

rem --- libraries (delete the venv folder to force a reinstall) ---
if exist "venv\.requirements-stamp" goto deps_ok
echo Installing the required libraries...
"%VENV_PY%" -m pip install -q --upgrade pip
"%VENV_PY%" -m pip install -q -r requirements.txt
if errorlevel 1 goto deps_failed
echo done> "venv\.requirements-stamp"
:deps_ok

echo Opening the setup window.
"%VENV_PY%" setup_gui.py
echo.
pause
exit /b 0

:no_python
echo.
echo Python was not found.
echo Install it from https://www.python.org/downloads/
echo During installation, be sure to tick "Add Python to PATH".
echo.
pause
exit /b 1

:venv_failed
echo Could not create the virtual environment.
pause
exit /b 1

:deps_failed
echo Installation failed.
pause
exit /b 1
