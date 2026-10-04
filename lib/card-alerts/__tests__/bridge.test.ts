import { describe, expect, it } from "vitest";
import { kstDate, readCapturedAlerts } from "../bridge";
import { collectTransactions } from "../parse";

describe("kstDate", () => {
  it("UTC 자정 전이라도 한국 날짜로 바꾼다", () => {
    // 2026-10-03 15:30 UTC = 2026-10-04 00:30 KST
    expect(kstDate(Date.UTC(2026, 9, 3, 15, 30))).toBe("2026-10-04");
    expect(kstDate(Date.UTC(2026, 9, 3, 14, 59))).toBe("2026-10-03");
  });
});

describe("readCapturedAlerts", () => {
  const body = "삼성1088승인 홍*동\n88,000원 일시불\n10/03 21:24 바다식당";

  it("앱이 모은 알림을 판정 입력으로 바꾼다", () => {
    const json = JSON.stringify([{ body, postedAt: Date.UTC(2026, 9, 3, 12, 24) }]);
    const messages = readCapturedAlerts({ getAlerts: () => json });
    expect(messages).toEqual([{ body, receivedAt: "2026-10-03" }]);
    expect(collectTransactions(messages).transactions[0]).toMatchObject({ amount: 88000, merchantRaw: "바다식당" });
  });

  it("깨진 응답과 모양이 틀린 항목은 버린다", () => {
    expect(readCapturedAlerts({ getAlerts: () => "not json" })).toEqual([]);
    expect(readCapturedAlerts({ getAlerts: () => '{"body":"x"}' })).toEqual([]);
    const mixed = JSON.stringify([{ body, postedAt: 0 }, { body: 1, postedAt: 0 }, { body }]);
    expect(readCapturedAlerts({ getAlerts: () => mixed })).toHaveLength(1);
  });
});
