@echo off
setlocal
cd /d "%~dp0"
set "LITTERBOX_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "LITTERBOX_PYTHON=.venv\Scripts\python.exe"
"%LITTERBOX_PYTHON%" -m PyInstaller --noconfirm LitterBox.spec
if errorlevel 1 goto failed
echo.
echo Built: %CD%\dist\LitterBox\LitterBox.exe
if /i not "%~1"=="--no-pause" pause
exit /b 0
:failed
echo.
echo Build failed!
echo Install the dependencies first!!! (python -m pip install -r requirements.txt)
if /i not "%~1"=="--no-pause" pause
exit /b 1
