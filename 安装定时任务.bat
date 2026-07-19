@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File 安装定时任务.ps1
pause
