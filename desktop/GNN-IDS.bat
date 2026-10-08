@echo off
rem Launch the GNN-IDS Control Center. No console window - the app window opens on its own
rem and comes to the front. If it fails to start, the error log opens automatically.
cd /d "%~dp0.."
set "PYW=.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
del "desktop\last_run.log" >nul 2>&1
start "" "%PYW%" "desktop\control_center.py"
rem if nothing is running a few seconds later, it crashed - show the log
timeout /t 4 /nobreak >nul
tasklist /fi "imagename eq pythonw.exe" 2>nul | find /i "pythonw.exe" >nul
if errorlevel 1 (
  if exist "desktop\last_run.log" start "" notepad "desktop\last_run.log"
)
