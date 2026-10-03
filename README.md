# 구독모아

구독 지출을 자동으로 모아 보고, 같이 쓸 사람을 찾는 앱.

기획은 `spec/`에, 초기 적대적 실사는 `review/`에 있다.
현행 기획서는 **`spec/v5-subscription-manager-openbanking.md`** (오픈뱅킹 연동 / 연 1,200원 / 1인 운영).

## 구성

| 경로 | 역할 |
|---|---|
| `lib/merchants.ts` | 가맹점명 정규화 사전. 이 앱의 유일한 축적 자산 |
| `lib/detector.ts` | 정기결제 판정 엔진. 건별 결제 내역 → 구독 인벤토리 |
| `lib/parties.ts` | 파티 모집 (관심 등록 모델) |
| `lib/referral.ts` | 겜스고 어필리에이트 링크 + 경제적 이해관계 고지 |
| `app/page.tsx` | 내 구독 — 지출·D-Day·신규 구독·요금 인상 |
| `app/party/` | 파티 찾기 — 4인 슬롯 UI |

## 실행

```bash
npm install
npm run dev        # http://localhost:3000
npm test           # 판정 엔진 테스트
npm run typecheck
npm run build
```

## 환경 변수

```
NEXT_PUBLIC_GAMSGO_PROMO=   # 겜스고 어필리에이트 프로모션 코드
```
미설정 시 링크는 동작하지만 커미션이 집계되지 않으며, 화면에 경고가 표시된다.

## 지금 막혀 있는 것

구독 식별은 오픈뱅킹 `카드청구상세정보조회`가 **건별 가맹점명**을 주는지에 달려 있다.
`카드청구기본정보조회`는 월별 청구 총액만 준다는 것이 확인됐다(가맹점명 없음).

상세 API 명세는 `developers.kftc.or.kr` 로그인 후 열람해야 하므로 아직 미확인이며,
**이것이 사업의 단일 전제다.** 총액만 온다면 카드 결제 구독을 식별할 수 없다.
자세한 내용은 `spec/v5-subscription-manager-openbanking.md` §1.

현재 `app/page.tsx`는 `lib/sample-data.ts`의 샘플 거래로 엔진을 돌린다.
