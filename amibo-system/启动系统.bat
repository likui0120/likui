@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0backend"

rem 已经装好过：直接启动（依赖不全时补装）
if exist ".venv\Scripts\python.exe" goto check_deps

rem 第一次运行：找 Python（不在 PATH 里也能找到）
set "PY="
call :try python
if not defined PY call :try py -3
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "C:\Python3*") do if not defined PY call :try "%%~D\python.exe"
if not defined PY goto no_python

echo 第一次运行，正在安装依赖，需要联网，请稍等……
echo 使用的 Python：%PY%
%PY% -m venv .venv
if errorlevel 1 goto fail

:check_deps
.venv\Scripts\python -c "import fastapi, uvicorn, sqlalchemy, openpyxl, python_multipart" >nul 2>nul
if not errorlevel 1 goto run
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fail

:run
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
exit /b

rem 试一个 Python 命令：能运行且版本不低于 3.10 就用它
:try
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b 0

:no_python
echo.
echo   没找到 Python 3.10 或更高版本。
echo   请到 https://www.python.org/downloads/ 下载安装，装好后再双击本文件。
pause
exit /b 1

:fail
echo.
echo   安装依赖失败，请确认这台电脑能上网，然后再双击本文件重试。
echo   如果还不行，把 backend\.venv 文件夹删掉再试。
pause
exit /b 1
