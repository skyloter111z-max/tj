@echo off
chcp 65001 >nul
echo === 잘 때 절전 모드 (FibTrader는 계속 돌아갑니다) ===
echo.
rem 1. FibTrader가 꺼져 있으면 켠다 (이미 켜져 있으면 그대로)
tasklist /fi "imagename eq pythonw.exe" | find /i "pythonw.exe" >nul || (start "" pythonw "C:\fib\fibtrader.pyw" & echo FibTrader가 꺼져 있어서 켰습니다.)
rem 2. 절전·최대 절전은 "안 함" (PC가 잠들면 자동매매가 멈춘다)
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
rem 3. 화면은 1분 뒤 꺼짐, 디스크는 5분 뒤 멈춤
powercfg /change monitor-timeout-ac 1
powercfg /change disk-timeout-ac 5
rem 4. CPU 최대 성능 50%로 제한 (FibTrader는 CPU를 1~2%만 쓴다)
powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX 50
powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMIN 5
powercfg /setactive SCHEME_CURRENT
echo 절전 설정 완료: 절전 안 함 / 화면 1분 / CPU 최대 50%%
echo 3초 뒤 모니터를 끕니다. (마우스를 움직이면 다시 켜집니다)
timeout /t 3 /nobreak >nul
rem 5. 모니터 바로 끄기
powershell -NoProfile -Command "$t=Add-Type -PassThru -Name M -Namespace W -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool PostMessage(int h,int m,int w,int l);'; [void]$t::PostMessage(0xffff,0x0112,0xF170,2)"
