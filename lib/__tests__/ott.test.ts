import { describe, expect, it } from "vitest";
import type { DetectedSubscription } from "../detector";
import { foundCount, OTT_WATCHLIST, ottStatuses } from "../ott";
import { findService } from "../merchants";

function sub(id: string): DetectedSubscription {
  const service = findService(id)!;
  return {
    service,
    displayName: service.name,
    merchantNormalized: service.name,
    amount: 10000,
    cycle: "monthly",
    nextChargeDate: "2026-11-01",
    confidence: 0.9,
    occurrences: 3,
    lastChargeDate: "2026-10-01",
    firstChargeDate: "2026-08-01",
    totalPaid: 30000,
    priceChange: null,
    isNew: false,
    active: true,
  };
}

describe("ottStatuses", () => {
  it("주요 OTT 6종을 모두 포함한다", () => {
    expect(OTT_WATCHLIST.map((s) => s.id).sort()).toEqual(
      ["coupangplay", "disneyplus", "netflix", "tving", "wavve", "youtubepremium"].sort(),
    );
  });

  it("찾은 OTT를 위로 올리고 나머지는 못 찾음으로 둔다", () => {
    const statuses = ottStatuses([sub("netflix"), sub("tving")]);
    expect(foundCount(statuses)).toBe(2);
    expect(statuses.slice(0, 2).map((s) => s.service.id).sort()).toEqual(["netflix", "tving"]);
    expect(statuses.slice(2).every((s) => s.found === null)).toBe(true);
  });

  it("구독이 없으면 전부 못 찾음", () => {
    expect(foundCount(ottStatuses([]))).toBe(0);
  });

  it("OTT가 아닌 구독(쿠팡 와우)은 OTT 목록에 넣지 않는다", () => {
    expect(foundCount(ottStatuses([sub("coupangwow")]))).toBe(0);
  });
});
