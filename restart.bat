@echo off
echo Stopping any running instance...
taskkill /f /im python.exe /t 2>nul
taskkill /f /im pythonw.exe /t 2>nul
timeout /t 2 /nobreak >nul
echo Starting Interview Assistant Pro...
cd /d %~dp0
call venv\Scripts\activate.bat
python src/main.py
