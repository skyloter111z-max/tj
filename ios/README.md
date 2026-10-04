# 구독모아 아이폰 앱

아이폰은 다른 앱의 알림(카톡 알림톡·카드사 앱 푸시)을 읽을 수 없다. 대신 **단축어 "메시지" 자동화**가
문자를 앱에 넘겨줄 수 있어서, 카드 알림을 **문자로** 받는 사람은 안드로이드처럼 자동으로 쌓인다.

```
카드 승인 문자
  → 단축어 자동화 (사용자가 한 번 만들어 둠)
  → SaveCardAlertIntent        구독모아 › 결제 알림 저장
  → AlertFilter                카드 결제 문자가 아니면 즉시 버림
  → AlertStore                 앱 컨테이너에만 보관 (서버 전송 없음)
  → WebViewController          window.SubmoaBridge로 웹에 건넴
  → lib/card-alerts/bridge.ts → parse.ts → detector.ts
```

## 구조

| 경로 | 내용 | 검증 |
|---|---|---|
| `SubmoaCore/` | AlertFilter · AlertStore · WebAssets (UIKit 의존 없음) | 리눅스에서 `swift test` 9개 통과 |
| `Submoa/` | SwiftUI 앱, WKWebView, 번들 파일 서버, App Intent | **Mac에서 아직 빌드하지 않음** |

## 빌드 (Mac)

```bash
npm run export                 # 저장소 루트: 웹 앱 → out/
brew install xcodegen
cd ios && xcodegen             # project.yml → Submoa.xcodeproj
open Submoa.xcodeproj          # Signing & Capabilities에서 Team 지정 후 실행
```

```bash
cd ios/SubmoaCore && swift test   # 순수 로직 테스트 (Mac·리눅스 공통)
```

## 사용자가 한 번 하는 설정

1. 단축어 앱 → 자동화 → ＋ → **메시지**
2. "메시지에 포함"에 `원` → **즉시 실행** 선택
3. 동작 추가 → **구독모아 › 결제 알림 저장** → "문자 내용"에 **단축어 입력**

`원`이 들어간 문자마다 동작이 돌지만, 카드 결제 문자가 아니면 AlertFilter가 버린다.

## 아직 확인하지 않은 것

- Mac 빌드 자체 (Xcode 미보유 환경에서 작성)
- 메시지 자동화의 "단축어 입력"이 String 파라미터에 문자 본문으로 들어가는지
- 잠금 상태에서도 자동화가 돌아 App Intent가 실행되는지
- 사용자 지정 스킴(submoa://)에서 localStorage가 앱 재실행 뒤에도 남는지 — 안 남으면 온보딩 선택만 사라진다
