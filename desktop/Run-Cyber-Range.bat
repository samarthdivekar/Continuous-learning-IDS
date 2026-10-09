@echo off
rem Runs the cyber-range demo in a visible window so you can watch all 7 phases.
rem Double-click this. Needs Docker Desktop running and the stack started.
title GNN-IDS Cyber Range Demo
cd /d "%~dp0.."
echo ================================================================
echo   GNN-IDS CYBER RANGE  -  isolated containers: attacker vs the IDS
echo ================================================================
echo.
echo This runs for about 6 minutes. Watch the 7 phases below, and
echo open the console (http://127.0.0.1:8080  -^>  Live sites) to see
echo the graph light up and incidents appear.
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "demo\cyber_range.py" --server http://127.0.0.1:8000
) else (
  python "demo\cyber_range.py" --server http://127.0.0.1:8000
)
echo.
echo ================================================================
echo   Finished. Leave this window; open the console Live sites tab.
echo ================================================================
pause >nul
