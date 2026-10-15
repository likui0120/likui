@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   没找到 Python。请先安装 Python 3.11 或更高版本：https://www.python.org/downloads/
  echo   安装时勾选 "Add python.exe to PATH"。
  pause
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  echo 第一次运行，正在安装依赖，需要联网，请稍等……
  python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
if not exist "..\data\amibo.db" (
  echo 正在初始化数据库……
  .venv\Scripts\python -m app.seed
)
echo.
echo   系统已启动。本机打开 http://127.0.0.1:8000
echo   平板或其他电脑用这台电脑的局域网 IP 打开，例如 http://192.168.1.10:8000
echo   关闭这个窗口即停止系统。
echo.
start "" http://127.0.0.1:8000
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
