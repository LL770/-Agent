@echo off
chcp 65001 >nul
title 停止美嘉监工

echo [INFO] 关闭美嘉监工...
taskkill /F /IM python.exe 2>nul
echo [OK] 已停止
pause