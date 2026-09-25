@echo off
chcp 65001 >nul
echo === 아침: 원래 전원 설정으로 (FibTrader는 계속 돌아갑니다) ===
echo.
rem 절전·화면 꺼짐 모두 "안 함", CPU 최대 100% (24시간 자동매매)
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0
powercfg /change disk-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 100
powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMIN 5
powercfg /setactive SCHEME_CURRENT
tasklist /fi "imagename eq pythonw.exe" | find /i "pythonw.exe" >nul || (start "" pythonw "C:\fib\fibtrader.pyw" & echo FibTrader가 꺼져 있어서 켰습니다.)
echo 설정 완료: 화면 꺼짐 없음 / CPU 최대 100%% / 절전 안 함
timeout /t 5 >nul
