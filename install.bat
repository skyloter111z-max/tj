@echo off
chcp 65001 >nul
echo === FibTrader 설치/업데이트 ===
if not exist C:\fib mkdir C:\fib
cd /d C:\fib
set B=https://raw.githubusercontent.com/skyloter111z-max/tj
set BR=claude/fib-plan-upbit-recalc-ynzvut
rem 최신 커밋 번호로 받아서 모든 파일을 같은 버전으로 맞춘다 (브랜치 주소는 캐시 때문에 옛 파일이 섞일 수 있음)
set SHA=
for /f "usebackq delims=" %%s in (`powershell -NoProfile -Command "try{(Invoke-RestMethod -UseBasicParsing https://api.github.com/repos/skyloter111z-max/tj/commits/%BR%).sha}catch{}"`) do set SHA=%%s
if defined SHA (set U=%B%/%SHA%) else (set U=%B%/%BR%)
echo 버전: %SHA%
curl -s -f -o files.txt %U%/files.txt || (echo [실패] 파일 목록 다운로드 & pause & exit /b 1)
for /f "usebackq delims=" %%f in ("files.txt") do (
  curl -s -f -o %%f %U%/%%f || (echo [실패] %%f 다운로드 & pause & exit /b 1)
  echo 받음: %%f
)
echo.
echo 글꼴(Barlow) 받는 중...
if not exist C:\fib\fonts mkdir C:\fib\fonts
set G=https://raw.githubusercontent.com/google/fonts/main/ofl
curl -s -f -o C:\fib\fonts\Barlow-Regular.ttf %G%/barlow/Barlow-Regular.ttf && echo 받음: Barlow-Regular.ttf || echo [참고] Barlow-Regular.ttf 글꼴을 못 받았습니다. 기본 글꼴로 표시됩니다.
curl -s -f -o C:\fib\fonts\Barlow-Bold.ttf %G%/barlow/Barlow-Bold.ttf && echo 받음: Barlow-Bold.ttf || echo [참고] Barlow-Bold.ttf 글꼴을 못 받았습니다. 기본 글꼴로 표시됩니다.
curl -s -f -o C:\fib\fonts\BarlowCondensed-SemiBold.ttf %G%/barlowcondensed/BarlowCondensed-SemiBold.ttf && echo 받음: BarlowCondensed-SemiBold.ttf || echo [참고] BarlowCondensed-SemiBold.ttf 글꼴을 못 받았습니다. 기본 글꼴로 표시됩니다.
echo.
echo 라이브러리 설치 중...
python -m pip install -q pystray pillow
echo.
echo 설치 확인 중...
python -c "import fibtrader_core, fibtrader_theme, fibtrader_widgets, fib_orders, fib_check; print('확인 완료: 모든 파일 정상')" || (echo [실패] 파일이 빠졌거나 깨졌습니다. 이 화면을 캡처해 보내 주세요. & pause & exit /b 1)
echo.
echo 바탕화면 아이콘과 자동 실행 등록 중...
powershell -NoProfile -Command "$py=(Get-Command pythonw).Source; foreach($f in 'Desktop','Startup'){ $d=[Environment]::GetFolderPath($f); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'FibTrader.lnk')); $s.TargetPath=$py; $s.Arguments='\"C:\fib\fibtrader.pyw\"'; $s.WorkingDirectory='C:\fib'; $s.Save() }"
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\start_watch.bat" 2>nul
echo.
echo 완료! 바탕화면의 FibTrader 아이콘을 더블클릭하세요.
echo (FibTrader가 이미 켜져 있었다면 트레이 F 아이콘 - 종료 후 다시 실행하세요)
pause
rem install.bat 자신도 최신으로 교체 (한 줄에서 끝내야 실행 중인 파일을 바꿔도 안전)
curl -s -f -o install.new %U%/install.bat && move /y install.new install.bat >nul & exit /b 0
