@echo off
rem Double-click this file to start the dashboard. No virtual environment needed.
cd /d "%~dp0"
set "AGENTGIT_HOME=%~dp0data"
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
%PY% -m agentgit.cli doctor
echo.
%PY% -m agentgit.cli web --open
pause
