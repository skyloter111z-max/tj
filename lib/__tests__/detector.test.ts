import { describe, expect, it } from "vitest";
import {
  detectSubscriptions,
  monthlyEquivalent,
  subscriptionKey,
  totalMonthly,
  type RawTransaction,
} from "../detector";
import {
  findService,
  matchesYearlyPrice,
  matchMaskedMerchant,
  matchMerchant,
  normalizeMerchant,
  revealedPrefix,
  YEARLY_CAPABLE_SERVICES,
} from "../merchants";

const TODAY = "2026-10-03";

/** 월 단위로 반복되는 결제 내역을 만든다. */
function monthly(merchant: string, amount: number, months: string[]): RawTransaction[] {
  return months.map((date) => ({ merchantRaw: merchant, amount, date }));
}

describe("normalizeMerchant", () => {
  it("결제대행사 접두 노이즈를 제거한다", () => {
    expect(normalizeMerchant("PADDLE.NET* OPENAI")).toBe("OPENAI");
    expect(normalizeMerchant("GOOGLE *YouTubePremium")).toBe("YOUTUBEPREMIUM");
    expect(normalizeMerchant("PAYPAL *SPOTIFY")).toBe("SPOTIFY");
  });

  it("국가 코드 꼬리를 제거한다", () => {
    expect(normalizeMerchant("NETFLIX.COM KR")).toBe("NETFLIX.COM");
  });
});

describe("matchMerchant", () => {
  it("같은 서비스의 다른 표기를 하나로 모은다", () => {
    const forms = ["NETFLIX.COM", "넷플릭스", "NETFLIX", "netflix.com kr"];
    const ids = forms.map((f) => matchMerchant(f).service?.id);
    expect(new Set(ids)).toEqual(new Set(["netflix"]));
  });

  it("결제대행사를 거친 AI 구독도 매칭한다", () => {
    expect(matchMerchant("PADDLE.NET* OPENAI").service?.id).toBe("chatgpt");
    expect(matchMerchant("ANTHROPIC PBC").service?.id).toBe("claude");
  });

  it("모르는 가맹점은 null을 주되 정규화는 해준다", () => {
    const m = matchMerchant("(주)이름없는가게  1234");
    expect(m.service).toBeNull();
    expect(m.normalized).toBe("이름없는가게");
  });

  it("3자리 숫자는 서비스명의 일부일 수 있으므로 남긴다", () => {
    // "365"를 지점번호로 오인하면 Microsoft 365가 미분류로 떨어진다
    expect(matchMerchant("(주)이름없는가게 123").normalized).toBe("이름없는가게 123");
  });
});

describe("detectSubscriptions", () => {
  it("3개월 연속 동일 금액을 월 구독으로 잡는다", () => {
    const txs = monthly("NETFLIX.COM", 13500, ["2026-07-17", "2026-08-17", "2026-09-17"]);
    const [sub] = detectSubscriptions(txs, { today: TODAY });

    expect(sub).toBeDefined();
    expect(sub!.service?.id).toBe("netflix");
    expect(sub!.cycle).toBe("monthly");
    expect(sub!.amount).toBe(13500);
    expect(sub!.occurrences).toBe(3);
    expect(sub!.nextChargeDate).toBe("2026-10-17");
    expect(sub!.confidence).toBeGreaterThan(0.6);
  });

  it("1회성 결제는 구독으로 잡지 않는다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "NETFLIX.COM", amount: 13500, date: "2026-09-17" },
    ];
    expect(detectSubscriptions(txs, { today: TODAY })).toHaveLength(0);
  });

  it("금액이 들쭉날쭉하면 반복 구매로 보고 제외한다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "쿠팡", amount: 12000, date: "2026-07-05" },
      { merchantRaw: "쿠팡", amount: 47000, date: "2026-08-05" },
      { merchantRaw: "쿠팡", amount: 3200, date: "2026-09-05" },
    ];
    expect(detectSubscriptions(txs, { today: TODAY })).toHaveLength(0);
  });

  it("간격이 불규칙하면 제외한다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "NETFLIX.COM", amount: 13500, date: "2026-07-01" },
      { merchantRaw: "NETFLIX.COM", amount: 13500, date: "2026-07-09" },
      { merchantRaw: "NETFLIX.COM", amount: 13500, date: "2026-09-28" },
    ];
    expect(detectSubscriptions(txs, { today: TODAY })).toHaveLength(0);
  });

  it("연 구독을 주기까지 맞춰 식별한다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2024-09-20" },
      { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2025-09-20" },
      { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2026-09-20" },
    ];
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(sub!.cycle).toBe("yearly");
    expect(sub!.nextChargeDate).toBe("2027-09-20");
  });

  it("요금 인상을 감지한다", () => {
    // 넷플릭스 광고형: 5,500 → 7,000원 (2025-05-09)
    const txs: RawTransaction[] = [
      { merchantRaw: "NETFLIX.COM", amount: 5500, date: "2026-07-09" },
      { merchantRaw: "NETFLIX.COM", amount: 5500, date: "2026-08-09" },
      { merchantRaw: "NETFLIX.COM", amount: 7000, date: "2026-09-09" },
    ];
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(sub!.priceChange).toEqual({ from: 5500, to: 7000, at: "2026-09-09" });
    expect(sub!.amount).toBe(7000);
  });

  it("처음 보는 구독에 isNew를 세운다 — 무료체험 전환을 잡는 지점", () => {
    const txs = monthly("PADDLE.NET* OPENAI", 29000, ["2026-08-11", "2026-09-11"]);

    const first = detectSubscriptions(txs, { today: TODAY });
    expect(first[0]!.isNew).toBe(true);

    const known = new Set(first.map(subscriptionKey));
    const second = detectSubscriptions(txs, { today: TODAY, knownKeys: known });
    expect(second[0]!.isNew).toBe(false);
  });

  it("결제일이 주말로 밀려도 같은 구독으로 묶는다", () => {
    const txs = monthly("SPOTIFY", 11990, ["2026-07-05", "2026-08-03", "2026-09-07"]);
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(sub).toBeDefined();
    expect(sub!.occurrences).toBe(3);
  });

  it("사전에 없는 가맹점도 주기가 규칙적이면 구독으로 올린다", () => {
    const txs = monthly("이상한구독서비스", 9900, [
      "2026-07-15",
      "2026-08-15",
      "2026-09-15",
    ]);
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(sub).toBeDefined();
    expect(sub!.service).toBeNull();
    expect(sub!.displayName).toBe("이상한구독서비스");
    // 미매칭이므로 사전 매칭된 경우보다 신뢰도가 낮아야 한다
    expect(sub!.confidence).toBeLessThan(0.9);
  });

  it("여러 구독을 월 환산액 큰 순으로 돌려준다", () => {
    const txs = [
      ...monthly("SPOTIFY", 11990, ["2026-07-05", "2026-08-05", "2026-09-05"]),
      ...monthly("NETFLIX.COM", 17000, ["2026-07-17", "2026-08-17", "2026-09-17"]),
      ...monthly("PADDLE.NET* OPENAI", 29000, ["2026-07-11", "2026-08-11", "2026-09-11"]),
    ];
    const subs = detectSubscriptions(txs, { today: TODAY });
    expect(subs.map((s) => s.service?.id)).toEqual(["chatgpt", "netflix", "spotify"]);
    expect(totalMonthly(subs)).toBe(29000 + 17000 + 11990);
  });
});

describe("monthlyEquivalent", () => {
  it("연 구독을 월로 환산해 비교 가능하게 만든다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2025-09-20" },
      { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2026-09-20" },
    ];
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(monthlyEquivalent(sub!)).toBe(12917);
  });
});

describe("금액 변동 구분 — 계단식 요금 인상 vs 반복 구매", () => {
  it("환율로 금액이 미세하게 흔들려도 구독으로 유지한다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "PADDLE.NET* OPENAI", amount: 8100, date: "2026-07-11" },
      { merchantRaw: "PADDLE.NET* OPENAI", amount: 8150, date: "2026-08-11" },
      { merchantRaw: "PADDLE.NET* OPENAI", amount: 8090, date: "2026-09-11" },
    ];
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(sub).toBeDefined();
    expect(sub!.confidence).toBeGreaterThan(0.6);
  });

  it("금액이 배 이상 뛰면 요금 인상이 아니라 다른 상품으로 본다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "어떤가게", amount: 5000, date: "2026-07-10" },
      { merchantRaw: "어떤가게", amount: 5000, date: "2026-08-10" },
      { merchantRaw: "어떤가게", amount: 50000, date: "2026-09-10" },
    ];
    const subs = detectSubscriptions(txs, { today: TODAY });
    expect(subs).toHaveLength(0);
  });
});

describe("정규화가 서비스명의 숫자를 보존한다", () => {
  it("MICROSOFT 365의 365를 지점번호로 오인하지 않는다", () => {
    expect(normalizeMerchant("MICROSOFT 365")).toBe("MICROSOFT 365");
    expect(matchMerchant("MICROSOFT 365").service?.id).toBe("ms365");
    expect(matchMerchant("OFFICE 365").service?.id).toBe("ms365");
  });

  it("4자리 이상 지점·단말기 번호는 여전히 제거한다", () => {
    expect(normalizeMerchant("(주)모르는서비스 0012")).toBe("모르는서비스");
    expect(normalizeMerchant("어떤가게 123456")).toBe("어떤가게");
  });

  it("MS365 연 구독이 사전 매칭되어 신뢰도가 올라간다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2024-09-20" },
      { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2025-09-20" },
      { merchantRaw: "MICROSOFT 365", amount: 155000, date: "2026-09-20" },
    ];
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(sub!.service?.id).toBe("ms365");
    expect(sub!.displayName).toBe("Microsoft 365");
    expect(sub!.confidence).toBeGreaterThanOrEqual(0.6);
  });
});

describe("마스킹된 가맹점명 식별 — 오픈뱅킹 카드청구상세 대응", () => {
  it("드러난 접두를 뽑는다", () => {
    expect(revealedPrefix("오픈**")).toBe("오픈");
    expect(revealedPrefix("넷플***")).toBe("넷플");
    expect(revealedPrefix("NETFLIX")).toBe("NETFLIX");
  });

  it("접두와 금액이 함께 맞으면 확정한다", () => {
    const m = matchMaskedMerchant("넷플**", 13500);
    expect(m.service?.id).toBe("netflix");
    expect(m.by).toBe("prefix+price");
  });

  it("환율로 금액이 조금 흔들려도 맞춘다", () => {
    expect(matchMaskedMerchant("오픈**", 28600).service?.id).toBe("chatgpt");
  });

  it("접두가 겹쳐도 가격 지문이 하나면 가른다", () => {
    // 접두 "쿠팡"은 쿠팡와우·쿠팡플레이가 공유하지만,
    // 쿠팡플레이는 와우에 포함돼 별도 청구되지 않으므로 가격 지문이 없다
    const wow = matchMaskedMerchant("쿠팡**", 7890);
    expect(wow.service?.id).toBe("coupangwow");
    expect(wow.by).toBe("prefix+price");
  });

  it("접두와 가격이 모두 겹치는 두 서비스는 추측하지 않는다", () => {
    // Claude Pro와 Perplexity Pro는 둘 다 27,000원이다.
    // 접두가 안 맞으면 가격만으로 확정해서는 안 된다.
    const m = matchMaskedMerchant("알수없는**", 27000);
    expect(m.service).toBeNull();
    expect(m.by).toBe("none");
  });

  it("접두만 맞고 금액이 전혀 다르면 미분류로 남긴다", () => {
    // 틀린 이름을 보여주는 것이 모르는 것보다 나쁘다
    const m = matchMaskedMerchant("넷플**", 999);
    expect(m.service?.id).toBe("netflix");
    expect(m.by).toBe("prefix-only");
  });

  it("아무 신호도 없으면 미분류", () => {
    const m = matchMaskedMerchant("한식당**", 8500);
    expect(m.service).toBeNull();
    expect(m.by).toBe("none");
  });
});

describe("결제 주기 검증 — 사전이 오판을 거부한다", () => {
  it("넷플릭스는 연간 결제가 없으므로 365일 간격을 연 구독으로 올리지 않는다", () => {
    // 중간 달 데이터가 비었거나 서로 다른 결제다
    const txs: RawTransaction[] = [
      { merchantRaw: "NETFLIX.COM", amount: 17000, date: "2025-09-17" },
      { merchantRaw: "NETFLIX.COM", amount: 17000, date: "2026-09-17" },
    ];
    expect(detectSubscriptions(txs, { today: TODAY })).toHaveLength(0);
  });

  it("ChatGPT Plus도 월 전용이다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "PADDLE.NET* OPENAI", amount: 29000, date: "2025-08-11" },
      { merchantRaw: "PADDLE.NET* OPENAI", amount: 29000, date: "2026-08-11" },
    ];
    expect(detectSubscriptions(txs, { today: TODAY })).toHaveLength(0);
  });

  it("디즈니+는 연간권이 있으므로 연 구독으로 올린다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "디즈니플러스", amount: 99000, date: "2024-09-20" },
      { merchantRaw: "디즈니플러스", amount: 99000, date: "2025-09-20" },
      { merchantRaw: "디즈니플러스", amount: 99000, date: "2026-09-20" },
    ];
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(sub?.service?.id).toBe("disneyplus");
    expect(sub?.cycle).toBe("yearly");
  });

  it("사전에 없는 가맹점은 주기를 검증할 수 없으므로 통과시킨다", () => {
    const txs: RawTransaction[] = [
      { merchantRaw: "모르는연간서비스", amount: 50000, date: "2024-06-10" },
      { merchantRaw: "모르는연간서비스", amount: 50000, date: "2025-06-10" },
      { merchantRaw: "모르는연간서비스", amount: 50000, date: "2026-06-10" },
    ];
    const [sub] = detectSubscriptions(txs, { today: TODAY });
    expect(sub?.cycle).toBe("yearly");
    expect(sub?.service).toBeNull();
  });

  it("연 구독 탐색 대상은 연간권이 있는 서비스뿐이다", () => {
    const ids = YEARLY_CAPABLE_SERVICES.map((s) => s.id);
    expect(ids).toContain("disneyplus");
    expect(ids).toContain("ms365");
    expect(ids).not.toContain("netflix");
    expect(ids).not.toContain("chatgpt");
  });

  it("연간권 가격 지문으로 연 구독 후보를 가른다", () => {
    const disney = findService("disneyplus")!;
    expect(matchesYearlyPrice(disney, 99000)).toBe(true);
    expect(matchesYearlyPrice(disney, 13900)).toBe(false); // 월 가격
  });
});
