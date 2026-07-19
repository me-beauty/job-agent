@echo off
chcp 65001 >nul
echo ================================
echo    🚀 日报Agent 一键启动
echo ================================
echo.
echo 📋 启动完成后，请输入：
echo    /read 一键搜索.md
echo.
echo ================================
echo.

cd /d "%~dp0"
claude

pause