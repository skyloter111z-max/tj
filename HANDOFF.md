# 구독모아(SubMoa) 작업 인계 — 2026-10-06

> 이 문서를 그대로 새 작업의 프롬프트로 붙여 넣으면 된다. 저장소: `skyloter111z-max/tj`,
> 브랜치 `claude/submoa-adversarial-critique-iwsvjy`, 최신 커밋 `9079a22`(+이 문서). 최신 APK는 사용자가 따로 넘긴다.

## 0. 너의 역할과 지켜야 할 것
- 너는 한국 소비자용 구독 관리 앱 **구독모아**를 이어서 만든다. 사용자는 1인 사업자(연 1,200원 유료 모델).
- **사용자 절대 금지: 구독을 "직접 입력/타이핑"하는 방식은 제안하지도 말 것.** 자동으로 찾는 것만.
- 모든 처리는 **폰 안에서만**(결제·화면 글자를 서버로 보내지 않음).
- 오픈뱅킹/카드 스크래핑(쿠콘·CODEF)은 보안점검 비용(150~600만원) 때문에 제외. 네이버 메일은 읽기 API 없음.
- 구글플레이 정책상 접근성 서비스로 화면 긁기 금지 → **화면 캡처(MediaProjection, 사용자 동의)** 로 읽는다.
- 사용자 스타일: 한국어, 질문을 여러 번 하는 걸 싫어함, 결과·자동화 선호. 확실하지 않은 건 솔직히 말하고, 확인은 실제 기기 결과로.

## 1. 구독을 찾는 경로 (현재 구현, 우선순위 순)
1. **구글플레이 정기결제 화면 1장 캡처 → OCR** (가장 확실, 카톡·카드알림 불필요). 홈/온보딩 맨 앞 버튼 "구글플레이 구독 한 번에 찾기".
2. **서비스 앱 안에서 읽기(GUIDED)**: 고른 서비스(넷플릭스·디즈니+·티빙·웨이브·쿠팡플레이·ChatGPT·Claude·Google One·Perplexity)를 **로그인돼 있는 앱**으로 열고, 위쪽 작은 안내창("마이 → 이용권…", 버튼: 읽기/건너뛰기/그만)을 띄운다. 2.5초마다 화면을 살펴 **구독 상태 화면**이 보이면 자동으로 읽고 다음 앱으로. 앱이 없는 서비스는 건너뜀. 한 번의 캡처 동의로 여러 앱을 차례로.
3. **결제 알림 자동 받기**(NotificationListener) — 앞으로 오는 카드 결제 알림(푸시/문자/알림톡)을 읽음.
4. **카톡 카드알림방 내보내기 공유** — 과거 몇 년치. 사용자 지적대로 어렵고 쓰는 사람이 적어 **맨 뒤 선택(접힘)** 으로 내렸다.
5. 스크린샷 이미지 공유 → OCR.

## 2. 실제 기기에서 확인된 사실 (사용자 폰: 삼성, 2026-10)
- 구글플레이 정기결제: **YouTube Premium ₩14,900/월** (파서 테스트 `real-play.test.ts`).
- 넷플릭스 앱 '계정': 캡처 **됨**(검게 안 나옴). 금액 없음. "광고형 스탠다드 멤버십 / 네이버 멤버십 서비스 추가 옵션을 통해 청구". 사용자는 **네이버 패밀리 멤버 → 본인 부담 0원**.
- 쿠팡플레이 앱 '프로필': 캡처 **됨**. "WOW! 와우회원"만(본인 계정) → **쿠팡 와우 7,890원**, 쿠팡플레이는 와우에 포함.
- **사용자 지출 정답**: 넷플릭스 0원(네이버플러스 포함) / 쿠팡 와우 7,890 / 유튜브 프리미엄 14,900.
- 안드로이드는 앱이 뒤에서 다른 앱을 여는 걸 막는다 → **'다른 앱 위에 표시' 권한 + 떠 있는 안내창**이 있어야 자동 전환된다(사용자 기기에서 첫 화면만 열리고 멈췄던 원인).
- 브라우저로 OTT 계정 페이지를 열면 전부 **로그인 화면**(curl 확인) → 반드시 앱으로 열어야 한다.
- OTT 앱의 **영상 재생 화면은 항상 캡처가 막힌다**(검게). 이용권/계정 화면은 앱마다 다름 → 넷플릭스·쿠팡플레이는 됨, 디즈니·티빙·웨이브는 **미확인**.

## 3. 아직 기기에서 끝까지 검증 안 된 것 (가장 먼저 할 일)
- 넷플릭스+쿠팡플레이 선택 → 동의 → **자동 감지 → 다음 앱 전환 → 앱 복귀** → 홈에 위 '정답'대로 나오는지.
- Android 14+ 수정(세션당 미러 1개)이 실제로 여러 장 캡처되는지.
- 디즈니/티빙/웨이브: 이용권 화면 스크린샷이 정상인지(검으면 그 앱은 캡처 불가 → 결제 알림으로만).

## 4. 코드 지도
**웹** (Next.js 15 정적 export + TypeScript, 앱 WebView 안에서 돈다)
- `app/page.tsx` 홈: `loadHome()`이 카톡 가져오기·알림·스토어 OCR을 합치고 배너 표시(찾음 / 읽었지만 못 찾음 / 글자를 못 읽음).
- `app/onboarding/page.tsx`: 안드로이드는 CapturePicker → 결제 알림 → 카톡(details 접힘).
- `components/CapturePicker.tsx`: "구글플레이 구독 한 번에 찾기" + 다중 선택("선택한 N개 확인하기").
- `components/OttOverview.tsx`, `SubscriptionDetail.tsx`, `MoreSources.tsx`, `AutoCapture.tsx`.
- `lib/capture-targets.ts`: 고를 대상과 큐 `[{id,url,name}]`.
- `lib/store-subs/parse.ts`: 스토어 화면 OCR 파서. `parseStoreScreenshotFor(text,id,{trusted})`, `priceOf`(점·명·회 등 단위가 붙은 숫자는 돈 아님).
- `lib/store-subs/app-screens.ts`: 앱 안 멤버십 화면 → 요금제 가격·묶음(`billedVia`). 넷플릭스(7,000/13,500/17,000, 네이버 경유 시 +0/+6,500/+10,000, **네이버플러스 요금은 넣지 않음**), 쿠팡 와우 7,890.
- `lib/store-subs/bridge.ts`: `ingestPendingOcr` — 네이티브가 쌓은 `[{id,text,trusted}]`를 해석(앱 화면 규칙 → 일반 → 타깃 순).
- `lib/billing.ts`: `viaLabel` → "네이버플러스에 포함" / "…로 청구".
- `lib/merchants.ts`: 서비스 사전(패턴·가격·cancelUrl/manageUrl, 2026-10 URL 검증. 티빙 `/my/ticket`, 디즈니 `/commerce/subscription`).
- `lib/detector.ts`(카드 결제로 구독 판정), `lib/card-alerts/*`(카톡 내보내기·알림 파싱, `bridge.ts`의 NativeBridge 타입).

**안드로이드** (`android/app/src/main/java/kr/submoa/app/`, Kotlin)
- `MainActivity.kt`: WebView + `SubmoaBridge`. `startStoreCapture()`/`startCaptureSequence(json)` → 앱 없는 서비스 제외 → 오버레이·알림 권한 → 캡처 동의 → 첫 화면 열기. 앱 켤 때 OCR 모델 워밍업.
- `ScreenCaptureService.kt`: 캡처 서비스. **세션당 미러 1개 + 최신 프레임 보관**(Android 14는 가상 화면을 한 번만 만들 수 있음), AUTO/GUIDED 모드, 안내창, 캡처 순간 안내창 숨김, **검은 화면(FLAG_SECURE) 감지 시 건너뜀**, 같은 화면 가드(전환 실패 시 오기록 방지), 결과 알림 + 상태("read"/"empty").
- `CaptureApps.kt`: 서비스 → 앱 패키지들(설치된 첫 앱) + 길 안내, 모드 결정, 열기. 쿠팡플레이는 쿠팡플레이 앱 → 쿠팡 앱 순.
- `SubscriptionSignal.kt`: 구독 상태 화면 판정("다음 결제/결제 예정/이용 기간"+금액, 또는 "멤버십 시작", "WOW! 와우회원" 한 줄).
- `StoreStore.kt`(OCR 대기열·캡처 상태 파일), `ImportActivity.kt`(공유 받기), `AlertListenerService.kt`/`AlertFilter.kt`(알림), `AndroidManifest.xml`(SYSTEM_ALERT_WINDOW, FGS mediaProjection, `<queries>` 앱 패키지들).
- `ios/`: SubmoaCore(Swift)·단축어 — 이번 작업은 안드로이드 중심이라 최신 기능 미반영.

## 5. 빌드·테스트
```bash
npx tsc --noEmit && npx vitest run            # 웹 165개
cd android && ./gradlew testDebugUnitTest      # 안드로이드 23개
npm run export && cd android && ./gradlew assembleDebug
node scripts/verify-apk-assets.mjs android/app/build/outputs/apk/debug/app-debug.apk
```
- `android/local.properties`에 `sdk.dir=<안드로이드 SDK 경로>` 필요(git 제외).
- `build.gradle.kts`의 `ignoreAssetsPattern`이 `_next/`를 살려 둔다(빼면 화면이 깨짐). ML Kit 한국어 OCR은 Play 서비스 제공 모델(번들하면 APK가 45MB로 업로드 한도 초과).
- 테스트 픽스처의 실제 화면 글자는 이메일·전화번호·이름을 빼고 넣었다. 계속 그렇게 할 것.

## 6. 다음 할 일 (우선순위)
1. 3번 항목 실기기 검증. 실패하면 어느 단계(동의/전환/감지/복귀/해석)인지 짚어 고친다.
2. 디즈니·티빙·웨이브 이용권 화면 스크린샷 받아서 `app-screens.ts`·`SubscriptionSignal.kt`에 규칙 추가. 캡처가 막힌 앱은 `CaptureApps`에서 즉시 건너뛰고 결제 알림으로 안내.
3. AI 앱(ChatGPT·Claude·Perplexity·Google One) 구독 화면도 같은 방식으로 실화면 기준 규칙화(달러 표기 처리 포함).
4. 네이버플러스를 본인이 내는 사람용: 네이버 앱 멤버십 화면 읽기(패밀리 멤버면 0원).
5. 웨이브 `manageUrl` 미검증(SPA라 모든 경로가 200).
