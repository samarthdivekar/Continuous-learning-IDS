@echo off
rem Launch the GNN-IDS Control Center (double-click this file).
rem Runs with a visible console so any error is shown instead of failing silently.
title GNN-IDS Control Center
cd /d "%~dp0.."
echo Starting GNN-IDS Control Center...
echo Keep this black window open while you use the app; closing it quits the app.
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "desktop\control_center.py"
) else (
  python "desktop\control_center.py"
)
echo.
echo ----------------------------------------------------------------
echo The app window has closed. If there is an error message above,
echo copy it and send it to Claude. Press a key to close this window.
pause >nul
