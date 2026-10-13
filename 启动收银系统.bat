@echo off
cd /d "%~dp0app"
set "DATA_DIR=%~dp0data"
if exist "node\node.exe" (
  "node\node.exe" --no-warnings server.js --open
) else (
  node --no-warnings server.js --open
  if errorlevel 9009 (
    echo.
    echo   Node.js not found. Install the LTS version from https://nodejs.org/zh-cn
  )
)
pause
