@echo off
setlocal
cd /d "%~dp0"
if not exist "shadow server\backend\.venv\Scripts\python.exe" python -m venv "shadow server\backend\.venv"
if errorlevel 1 exit /b 1
"shadow server\backend\.venv\Scripts\python.exe" -m pip install -r "shadow server\backend\requirements.txt" -r "shadow server\backend\requirements-services.txt" -r "repo server\requirements.txt"
if errorlevel 1 exit /b 1
"shadow server\backend\.venv\Scripts\python.exe" "shadow server\backend\setup\configure_env.py"
if errorlevel 1 exit /b 1
"shadow server\backend\.venv\Scripts\python.exe" "shadow server\backend\setup\configure_gateway.py"
if errorlevel 1 exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "shadow server\backend\setup\proxy_setup.ps1" -InstallRoot "%CD%\proxy-runtime" -Python "%CD%\shadow server\backend\.venv\Scripts\python.exe"
if errorlevel 1 exit /b 1
pushd "shadow server\frontend"
call npm.cmd ci
if errorlevel 1 exit /b 1
popd
pushd "repo server\frontend"
call npm.cmd ci
if errorlevel 1 exit /b 1
popd
echo Setup complete. Run start.bat.
