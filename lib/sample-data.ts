/**
 * 엔진 동작을 보기 위한 샘플 거래 내역.
 *
 * 운영에서는 오픈뱅킹 `카드청구상세정보조회` 응답을 RawTransaction으로 변환해 넣는다.
 * 그 API가 건별 가맹점명을 주는지는 아직 미확인이며, 그것이 사업의 전제다
 * (spec/v5 §1).
 *
 * 가맹점명은 실제 카드 명세에서 관측되는 형태를 그대로 썼다.
 */

import type { RawTransaction } from "./detector";

export const SAMPLE_TRANSACTIONS: RawTransaction[] = [
  // 넷플릭스 — 3개월 연속, 요금 인상 포함
  { merchantRaw: "NETFLIX.COM", amount: 13500, date: "2026-07-17" },
  { merchantRaw: "NETFLIX.COM", amount: 13500, date: "2026-08-17" },
  { merchantRaw: "NETFLIX.COM KR", amount: 17000, date: "2026-09-17" },

  // ChatGPT — 결제대행사를 거쳐 들어온다
  { merchantRaw: "PADDLE.NET* OPENAI", amount: 29000, date: "2026-08-11" },
  { merchantRaw: "PADDLE.NET* OPENAI", amount: 29000, date: "2026-09-11" },

  // 스포티파이 — 결제일이 주말로 밀린다
  { merchantRaw: "PAYPAL *SPOTIFY", amount: 11990, date: "2026-07-05" },
  { merchantRaw: "SPOTIFY", amount: 11990, date: "2026-08-03" },
  { merchantRaw: "SPOTIFY", amount: 11990, date: "2026-09-07" },

  // 쿠팡 와우
  { merchantRaw: "쿠팡와우", amount: 7890, date: "2026-07-22" },
  { merchantRaw: "쿠팡와우", amount: 7890, date: "2026-08-22" },
  { merchantRaw: "쿠팡와우", amount: 7890, date: "2026-09-22" },

  // MS365 — 연 구독
  { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2025-09-20" },
  { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2026-09-20" },

  // 사전에 없는 구독 — 미분류지만 주기가 규칙적이라 올라온다
  { merchantRaw: "(주)모르는서비스 0012", amount: 4900, date: "2026-07-14" },
  { merchantRaw: "(주)모르는서비스 0012", amount: 4900, date: "2026-08-14" },
  { merchantRaw: "(주)모르는서비스 0012", amount: 4900, date: "2026-09-14" },

  // 구독이 아닌 노이즈 — 걸러져야 한다
  { merchantRaw: "쿠팡", amount: 12400, date: "2026-07-03" },
  { merchantRaw: "쿠팡", amount: 47200, date: "2026-08-19" },
  { merchantRaw: "쿠팡", amount: 3300, date: "2026-09-02" },
  { merchantRaw: "스타벅스 역삼점", amount: 5600, date: "2026-09-28" },
];

/**
 * 지난 배치에서 이미 본 구독.
 *
 * 운영에서는 DB에 저장된 키를 읽어온다. 이 값이 있어야 신규 구독 알림이
 * "처음 보는 것만" 짚는다. 비워 두면 첫 실행에서 전부 신규로 뜬다.
 */
export const KNOWN_KEYS: ReadonlySet<string> = new Set([
  "svc:netflix",
  "svc:spotify",
  "svc:coupangwow",
  "svc:ms365",
  "raw:모르는서비스",
]);
