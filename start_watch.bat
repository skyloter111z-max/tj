@echo off
rem fib_watch.py 실시간 감시 시작 (PC 켤 때 자동 실행용)
cd /d %~dp0
title fib_watch
where python >nul 2>nul && (python fib_watch.py) || (py fib_watch.py)
pause
