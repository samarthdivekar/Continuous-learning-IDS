@echo off
rem Runs the cyber-range demo in a visible window so you can watch all 4 phases.
rem Double-click this. Needs Docker Desktop running and the stack started.
title GNN-IDS Cyber Range Demo
cd /d "%~dp0.."
echo ================================================================
echo   GNN-IDS CYBER RANGE  -  attacker VM vs the IDS, self-contained
echo ================================================================
echo.
echo This runs for about 2 minutes. Watch the 4 phases below, and
echo open the console (http://localhost:8080  -^>  Live sites) to see
echo the graph light up and incidents appear.
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "demo\cyber_range.py" --server http://localhost:8000
) else (
  python "demo\cyber_range.py" --server http://localhost:8000
)
echo.
echo ================================================================
echo   Finished. Leave this window; open the console Live sites tab.
echo ================================================================
pause >nul
