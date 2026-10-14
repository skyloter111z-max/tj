@echo off
chcp 65001 >nul
cd /d C:\fib
echo === 텔레그램 연결 확인 ===
python fib_telegram.py
echo.
pause
