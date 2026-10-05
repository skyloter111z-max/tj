import { describe, expect, it } from "vitest";
import { collectTransactions } from "../card-alerts/parse";
import { detectSubscriptions } from "../detector";

// 전자상거래 알림은 가맹점명을 약 6자로 자른다. 주요 OTT가 잘린 형태로도 잡혀야 한다.
// 실제 카드 알림에서 흔한 표기 + 6자 절단을 가정한 값.
const online = (mmdd: string, merchant: string, amount: string, receivedAt: string) => ({
  body: `삼성카드 홍*동님 전자상거래이용\n${mmdd} 03:12 ${merchant} ${amount}원`,
  receivedAt,
});

/** 3개월 반복으로 한 OTT를 만든다 */
function months(merchant: string, amount: string) {
  return [
    online("07/10", merchant, amount, "2026-07-10"),
    online("08/10", merchant, amount, "2026-08-10"),
    online("09/10", merchant, amount, "2026-09-10"),
  ];
}

const CASES: [string, string, string][] = [
  // [표기(절단 가능), 금액, 기대 service id]
  ["넷플릭스", "17,000", "netflix"],
  ["디즈니+", "9,900", "disneyplus"],
  ["디즈니플러", "9,900", "disneyplus"], // 디즈니플러스 → 6자 절단
  ["티빙", "17,000", "tving"],
  ["웨이브", "13,900", "wavve"],
  ["쿠팡플레이", "7,890", "coupangplay"],
  ["유튜브 프리", "14,900", "youtubepremium"], // 유튜브 프리미엄 → 6자 절단
  ["유튜브프리미", "14,900", "youtubepremium"],
];

describe("주요 OTT 절단 표기 탐지", () => {
  for (const [merchant, amount, id] of CASES) {
    it(`"${merchant}" → ${id}`, () => {
      const { transactions } = collectTransactions(months(merchant, amount));
      const subs = detectSubscriptions(transactions, { today: "2026-10-01" });
      expect(subs.map((s) => s.service?.id)).toContain(id);
    });
  }
});
