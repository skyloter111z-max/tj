# 구독모아 안드로이드 앱

카드 결제 알림을 읽는 얇은 네이티브 껍데기다. 화면과 판정 로직은 웹 앱(저장소 루트의 Next.js)이 맡는다.

```
알림 (카톡 알림톡 · 문자 · 카드사 앱 · 토스)
  → AlertListenerService      알림 접근 권한으로 수신
  → AlertFilter               카드 결제 알림이 아니면 즉시 버림
  → AlertStore                앱 내부 저장소에만 보관 (서버 전송 없음)
  → MainActivity의 WebView    window.SubmoaBridge.getAlerts()
  → lib/card-alerts/bridge.ts → parse.ts → detector.ts
```

## 실행

웹 앱을 정적 파일로 뽑아 APK 안에 넣는다. 서버가 필요 없어서 실기기에 바로 깔 수 있다.

```bash
npm run export                       # 저장소 루트: 웹 앱 → out/
cd android
ANDROID_HOME=~/Android/Sdk ./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk
```

APK는 out/을 `https://appassets.androidplatform.net/`으로 서빙한다(WebAssets). 확장자 없는
`/onboarding`은 `onboarding.html`로 찾는다. 앱은 홈(`/`)으로 열리고, 알림 읽기 설정을 마치지 않았으면
홈이 온보딩으로 보낸다.

개발 중 `npm run dev`에 바로 붙이려면(에뮬레이터):

```bash
./gradlew installDebug -Psubmoa.webUrl=http://10.0.2.2:3000/
```

## 테스트

```bash
./gradlew :app:testDebugUnitTest   # AlertFilter(결제 알림만 통과), WebAssets(경로 해석)

# APK에 웹 앱 CSS·JS가 다 들어갔는지 (저장소 루트에서)
node scripts/verify-apk-assets.mjs android/app/build/outputs/apk/debug/app-debug.apk
```

aapt는 기본값으로 `_`로 시작하는 폴더를 APK에서 뺀다. Next의 CSS·JS는 전부 `_next/`에 있어서,
기본값이면 HTML만 들어가 화면이 깨지고 버튼이 눌리지 않는다. `ignoreAssetsPattern`으로 막아 두었고,
빌드는 성공해도 이 문제가 생길 수 있으니 APK를 만든 뒤 위 확인을 돌린다.

## 실기기에서 아직 확인하지 않은 것

- 카톡 알림이 MessagingStyle로 오는지, 본문이 잘리지 않고 3줄 전체가 들어오는지
- 카톡 "메시지 미리보기"가 꺼져 있으면 본문 대신 "새 메시지"만 온다 — 이 경우 읽을 수 없다
- 일부 제조사(삼성 절전 등)가 알림 리스너를 종료시키는지
