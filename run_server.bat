@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 启动 Web API + 前端（阶段 1）...
echo 浏览器访问: http://127.0.0.1:8000/
echo 手机访问:    http://本机IP:8000/
echo 按 Ctrl+C 停止
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
pause
