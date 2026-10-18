@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0g3m_battery.py" %*
if "%~1"=="" pause
