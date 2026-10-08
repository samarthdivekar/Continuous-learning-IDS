@echo off
rem Troubleshooting launcher: runs with a visible console so any error is shown.
rem Use this only if GNN-IDS.bat does not open the app window.
title GNN-IDS Control Center (debug)
cd /d "%~dp0.."
echo Launching with a visible console. Any error will appear below.
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "desktop\control_center.py"
) else (
  python "desktop\control_center.py"
)
echo.
echo ----------------------------------------------------------------
echo The app has closed. If there is an error above, copy it to Claude.
pause >nul
