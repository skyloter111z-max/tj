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

```bash
# 1. 개발 PC에서 웹 앱
npm run dev

# 2. 에뮬레이터용 디버그 APK (기본 주소 http://10.0.2.2:3000/onboarding)
cd android
ANDROID_HOME=~/Android/Sdk ./gradlew installDebug

# 실기기나 배포 주소로 빌드할 때
./gradlew assembleRelease -Psubmoa.webUrl=https://배포주소/onboarding
```

## 테스트

```bash
./gradlew :app:testDebugUnitTest   # AlertFilter: 결제 알림은 통과, 일상 대화·광고는 차단
```

## 실기기에서 아직 확인하지 않은 것

- 카톡 알림이 MessagingStyle로 오는지, 본문이 잘리지 않고 3줄 전체가 들어오는지
- 카톡 "메시지 미리보기"가 꺼져 있으면 본문 대신 "새 메시지"만 온다 — 이 경우 읽을 수 없다
- 일부 제조사(삼성 절전 등)가 알림 리스너를 종료시키는지
