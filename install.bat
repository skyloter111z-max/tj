@echo off
chcp 65001 >nul
echo === FibTrader 설치/업데이트 ===
if not exist C:\fib mkdir C:\fib
cd /d C:\fib
set U=https://raw.githubusercontent.com/skyloter111z-max/tj/claude/fib-plan-upbit-recalc-ynzvut
for %%f in (fib_recalc.py fib_orders.py fib_check.py fibtrader_core.py fibtrader.pyw) do (
  curl -s -f -o %%f %U%/%%f || (echo [실패] %%f 다운로드 & pause & exit /b 1)
  echo 받음: %%f
)
echo.
echo 라이브러리 설치 중...
python -m pip install -q pystray pillow
echo.
echo 바탕화면 아이콘과 자동 실행 등록 중...
powershell -NoProfile -Command "$py=(Get-Command pythonw).Source; foreach($f in 'Desktop','Startup'){ $d=[Environment]::GetFolderPath($f); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'FibTrader.lnk')); $s.TargetPath=$py; $s.Arguments='\"C:\fib\fibtrader.pyw\"'; $s.WorkingDirectory='C:\fib'; $s.Save() }"
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\start_watch.bat" 2>nul
echo.
echo 완료! 바탕화면의 FibTrader 아이콘을 더블클릭하세요.
echo (예전 트레이 감시 fib_tray 아이콘이 떠 있으면 오른쪽 클릭 - 종료 하세요)
pause
