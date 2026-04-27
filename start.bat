@echo off
chcp 65001 >nul
title 美嘉监工

echo [INFO] 启动美嘉监工...
python main.py > agent.log 2>&1 &

echo [OK] 已启动，日志: agent.log
pause