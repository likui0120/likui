@echo off
rem Allow phones/tablets on the shop WiFi to reach the cashier system (Windows firewall).
net session >nul 2>&1
if not errorlevel 1 goto admin
powershell -NoProfile -Command "Start-Process -FilePath $env:ComSpec -ArgumentList '/c','\"%~f0\"' -Verb RunAs"
exit /b
:admin
set "NODE=%~dp0app\node\node.exe"
netsh advfirewall firewall delete rule name=all program="%NODE%" >nul 2>&1
netsh advfirewall firewall delete rule name=TaoxiPOS >nul 2>&1
set "R=ok"
netsh advfirewall firewall add rule name=TaoxiPOS dir=in action=allow protocol=TCP localport=3000 profile=any enable=yes >nul
if errorlevel 1 set "R=fail"
netsh advfirewall firewall add rule name=TaoxiPOS dir=in action=allow program="%NODE%" profile=any enable=yes >nul 2>&1
if not exist "%NODE%" goto plain
"%NODE%" "%~dp0app\fwmsg.js" %R%
goto end
:plain
echo %R%
:end
pause
