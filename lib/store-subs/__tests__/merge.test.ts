import { describe, expect, it } from "vitest";
import { detectSubscriptions, type RawTransaction } from "../../detector";
import { findService } from "../../merchants";
import { mergeStoreSubs, storeSubToDetected } from "../parse";

const svc = (id: string) => findService(id)!;

describe("storeSubToDetected", () => {
  it("스토어 구독을 구독 항목으로 바꾸고 출처를 store로 둔다", () => {
    const d = storeSubToDetected({ service: svc("netflix"), amount: 17000, cycle: "monthly" }, "2026-10-05");
    expect(d).toMatchObject({ amount: 17000, cycle: "monthly", source: "store", totalPaid: 17000, nextChargeDate: "2026-11-04" });
  });
});

describe("mergeStoreSubs", () => {
  const cardNetflix: RawTransaction[] = [
    { merchantRaw: "넷플릭스", amount: 17000, date: "2026-08-10" },
    { merchantRaw: "넷플릭스", amount: 17000, date: "2026-09-10" },
  ];

  it("카드에 없는 스토어 구독만 더한다", () => {
    const card = detectSubscriptions(cardNetflix, { today: "2026-10-05" });
    const merged = mergeStoreSubs(card, [
      { service: svc("netflix"), amount: 17000, cycle: "monthly" }, // 카드에 이미 있음 → 무시
      { service: svc("youtubepremium"), amount: 14900, cycle: "monthly" }, // 스토어 전용 → 추가
    ], "2026-10-05");
    expect(merged.map((s) => s.service?.id).sort()).toEqual(["netflix", "youtubepremium"]);
    expect(merged.find((s) => s.service?.id === "netflix")!.source).toBe("card");
    expect(merged.find((s) => s.service?.id === "youtubepremium")!.source).toBe("store");
  });
})
