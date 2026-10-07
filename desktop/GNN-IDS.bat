@echo off
rem Launch the GNN-IDS Control Center (double-click this file).
setlocal
cd /d "%~dp0\.."
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "desktop\control_center.py"
) else (
  start "" pythonw "desktop\control_center.py"
)
endlocal
