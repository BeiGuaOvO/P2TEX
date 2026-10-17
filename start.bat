@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo.
echo   错题 LaTeX 已启动
echo   本机访问: http://localhost:8000
echo   关闭此窗口即停止服务
echo.
uvicorn app.main:app --host 0.0.0.0 --port 8000
pause