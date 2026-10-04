/**
 * 가맹점명 정규화 사전.
 *
 * 카드 명세의 가맹점명은 PG·국가·결제대행사에 따라 지저분하게 들어온다.
 *   "PADDLE.NET* OPENAI"  "NETFLIX.COM"  "넷플릭스"  "GOOGLE *YouTubePremium"
 * 이것을 정규화된 서비스로 매핑하는 것이 이 앱의 유일한 축적 자산이다(spec/v5 §2.1).
 *
 * 미분류 가맹점은 수집해 사전을 키운다. 사전이 커질수록 CS가 줄고,
 * CS 1건은 고객 3명의 연 수익이다(spec/v5 §6).
 */

export type ServiceCategory = "ott" | "ai" | "music" | "commerce" | "cloud" | "etc";

export type ServiceDef = {
  id: string;
  name: string;
  category: ServiceCategory;
  /** 정규화된 가맹점명에 대해 검사할 패턴 */
  patterns: RegExp[];
  /**
   * 마스킹된 가맹점명에서 드러나는 접두 후보.
   *
   * 오픈뱅킹 `카드청구상세정보조회`는 가맹점명을 마스킹해서 준다
   * (`merchant_name_masked`, 예시 "오픈**"). 앞 몇 글자만 남으므로
   * 패턴 매칭이 듣지 않고, 접두 + 가격으로 좁혀야 한다.
   */
  maskedPrefixes?: string[];
  /**
   * 알려진 **월** 가격 지점(원). 마스킹 환경의 1차 식별 신호다.
   * 구독료는 상수라서 접두보다 판별력이 높다.
   */
  prices?: number[];
  /**
   * 이 서비스가 실제로 제공하는 결제 주기.
   *
   * 넷플릭스와 ChatGPT Plus는 **연간 결제가 없다**(2026 확인). 월 전용 서비스를
   * 알고 있으면 ① 연 구독 탐색 대상에서 빼고 ② 365일 간격 관측을 연 구독으로
   * 오판하지 않는다. 가장 흔한 두 구독이 여기 해당하므로 실익이 크다.
   */
  cycles: ("monthly" | "yearly")[];
  /** 연간권 가격 지점(원). cycles에 "yearly"가 있을 때만 의미가 있다 */
  yearlyPrices?: number[];
  /** 해지 페이지 딥링크 (spec/v5 §4-5) */
  cancelUrl?: string;
};

/**
 * 결제대행사가 가맹점명 앞뒤에 붙이는 노이즈.
 * 실제 서비스명을 가리므로 정규화 단계에서 제거한다.
 */
const PG_NOISE: RegExp[] = [
  /^PADDLE\.NET\*?/,
  /^GOOGLE\s*\*/,
  /^APPLE\.COM\/BILL/,
  /^PAYPAL\s*\*/,
  /^STRIPE\s*\*?/,
  /^SQ\s*\*/,
  /^FS\s*\*/,
  /^NICEPAY/,
  /^TOSSPAYMENTS?/,
  /^KAKAOPAY/,
  /^\(주\)/,
];

/** 금액·일자·지점 등 꼬리 노이즈 */
const TAIL_NOISE: RegExp[] = [
  // 끝의 숫자 덩어리(지점·단말기 번호). 4자리 이상만 자른다 —
  // 2~3자리까지 자르면 "MICROSOFT 365", "OFFICE 365"처럼 숫자가
  // 서비스명의 일부인 경우를 망가뜨린다.
  /\s+\d{4,}$/,
  /\s+(KR|US|IE|SG|JP|NL)$/i, // 국가 코드
  /\s+(해외|국내)$/,
];

/**
 * 가맹점명을 비교 가능한 형태로 정규화한다.
 * 대문자화 → PG 노이즈 제거 → 꼬리 노이즈 제거 → 공백 정리.
 */
export function normalizeMerchant(raw: string): string {
  let s = raw.toUpperCase().trim();
  for (const re of PG_NOISE) s = s.replace(re, "");
  for (const re of TAIL_NOISE) s = s.replace(re, "");
  return s.replace(/\s+/g, " ").trim();
}

export const SERVICES: ServiceDef[] = [
  // ── OTT
  {
    id: "netflix",
    name: "넷플릭스",
    category: "ott",
    patterns: [/NETFLIX/, /넷플릭스/],
    cancelUrl: "https://www.netflix.com/cancelplan",
    maskedPrefixes: ["넷플", "NE"],
    prices: [7000, 13500, 17000],
    cycles: ["monthly"],
  },
  {
    id: "disneyplus",
    name: "디즈니+",
    category: "ott",
    patterns: [/DISNEY\s?\+?/, /DISNEYPLUS/, /디즈니/],
    cancelUrl: "https://www.disneyplus.com/account/subscription",
    maskedPrefixes: ["디즈", "DI"],
    prices: [9900, 13900],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [99000, 139000],
  },
  {
    id: "tving",
    name: "티빙",
    category: "ott",
    patterns: [/TVING/, /티빙/],
    maskedPrefixes: ["티빙", "TV"],
    prices: [5500, 9500, 13900, 17000],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [83000, 94800, 118000, 130800, 148000, 183600],
  },
  {
    id: "wavve",
    name: "웨이브",
    category: "ott",
    patterns: [/WAVVE/, /웨이브/],
    maskedPrefixes: ["웨이", "WA"],
    prices: [7900, 10900, 13900],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [79000, 109000, 139000],
  },
  {
    id: "coupangplay",
    name: "쿠팡플레이",
    category: "ott",
    patterns: [/COUPANG\s?PLAY/, /쿠팡플레이/],
    // 와우 멤버십에 포함돼 별도 청구되지 않는다 → 가격 지문을 두지 않는다.
    // 쿠팡와우와 접두·가격이 모두 겹치면 둘을 가를 수 없다.
    maskedPrefixes: ["쿠팡", "CO"],
    cycles: ["monthly"],
  },
  {
    id: "youtubepremium",
    name: "유튜브 프리미엄",
    category: "ott",
    patterns: [/YOUTUBE\s?PREMIUM/, /YOUTUBEPREMIUM/, /유튜브\s?프리미엄/],
    cancelUrl: "https://www.youtube.com/paid_memberships",
    maskedPrefixes: ["유튜", "GO", "YO"],
    prices: [14900, 23900],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [163900],
  },

  // ── AI
  {
    id: "chatgpt",
    name: "ChatGPT",
    category: "ai",
    patterns: [/OPENAI/, /CHATGPT/],
    cancelUrl: "https://chatgpt.com/#settings/Subscription",
    maskedPrefixes: ["오픈", "PA", "OP"],
    prices: [29000],
    cycles: ["monthly"],
  },
  {
    id: "claude",
    name: "Claude",
    category: "ai",
    patterns: [/ANTHROPIC/, /CLAUDE\.?AI/],
    cancelUrl: "https://claude.ai/settings/billing",
    maskedPrefixes: ["앤트", "AN", "CL"],
    prices: [27000],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [288000],
  },
  {
    id: "gemini",
    name: "Google One / Gemini",
    category: "ai",
    patterns: [/GOOGLE\s?ONE/, /GOOGLEONE/],
    cancelUrl: "https://one.google.com/settings",
    maskedPrefixes: ["구글", "GO"],
    prices: [2400, 11900, 29000],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [289000],
  },
  {
    id: "perplexity",
    name: "Perplexity",
    category: "ai",
    patterns: [/PERPLEXITY/],
    maskedPrefixes: ["퍼플", "PE"],
    prices: [27000],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [288000],
  },
  {
    id: "cursor",
    name: "Cursor",
    category: "ai",
    patterns: [/CURSOR(\s|$)/, /ANYSPHERE/],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [230000],
  },
  {
    id: "midjourney",
    name: "Midjourney",
    category: "ai",
    patterns: [/MIDJOURNEY/],
    cycles: ["monthly"],
  },

  // ── 음악
  {
    id: "spotify",
    name: "스포티파이",
    category: "music",
    patterns: [/SPOTIFY/, /스포티파이/],
    maskedPrefixes: ["스포", "SP", "PA"],
    prices: [11990, 16350],
    cycles: ["monthly"],
  },
  {
    id: "melon",
    name: "멜론",
    category: "music",
    patterns: [/MELON/, /멜론/, /KAKAO\s?ENTERTAINMENT/],
    maskedPrefixes: ["멜론", "ME", "KA"],
    prices: [7900, 11400],
    cycles: ["monthly"],
  },

  // ── 커머스·기타
  {
    id: "coupangwow",
    name: "쿠팡 와우",
    category: "commerce",
    // 전자상거래 알림은 가맹점명을 6자 안팎에서 자른다: "쿠팡(와우멤"
    patterns: [/COUPANG\s?WOW/, /쿠팡\s?\(?와우/, /와우멤버십/],
    maskedPrefixes: ["쿠팡", "CO"],
    prices: [7890],
    cycles: ["monthly"],
  },
  {
    id: "naverplus",
    name: "네이버플러스",
    category: "commerce",
    patterns: [/NAVER\s?PLUS/, /네이버플러스/, /네이버\s?멤버십/],
    maskedPrefixes: ["네이", "NA"],
    prices: [3900, 4900],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [46800],
  },
  {
    id: "icloud",
    name: "iCloud+",
    category: "cloud",
    patterns: [/ICLOUD/, /APPLE\s?ONE/],
    maskedPrefixes: ["애플", "AP"],
    prices: [1100, 3300, 11100],
    cycles: ["monthly"],
  },
  {
    id: "ms365",
    name: "Microsoft 365",
    category: "cloud",
    patterns: [/MICROSOFT\s?365/, /MSFT\s?365/, /OFFICE\s?365/],
    maskedPrefixes: ["마이", "MI", "MS"],
    prices: [11900, 89000, 155000],
    cycles: ["monthly", "yearly"],
    yearlyPrices: [89000, 155000],
  },
];

export type MerchantMatch = {
  service: ServiceDef | null;
  normalized: string;
};

/**
 * 가맹점명 원문을 서비스에 매핑한다.
 * 매칭 실패(service: null)는 버그가 아니라 사전을 키울 입력이다.
 */
export function matchMerchant(raw: string): MerchantMatch {
  const normalized = normalizeMerchant(raw);
  for (const service of SERVICES) {
    if (service.patterns.some((re) => re.test(normalized))) {
      return { service, normalized };
    }
  }
  return { service: null, normalized };
}

export function findService(id: string): ServiceDef | undefined {
  return SERVICES.find((s) => s.id === id);
}

/** 마스킹 문자열에서 드러난 접두를 뽑는다. "넷플**" → "넷플" */
export function revealedPrefix(masked: string): string {
  const cut = masked.search(/[*＊]/);
  return (cut === -1 ? masked : masked.slice(0, cut)).trim();
}

/** 환율로 흔들리는 해외 결제를 흡수하는 가격 일치 판정 */
function priceMatches(prices: number[] | undefined, amount: number): boolean {
  if (!prices || prices.length === 0) return false;
  return prices.some((p) => Math.abs(p - amount) / p <= 0.05);
}

export type MaskedMatch = MerchantMatch & {
  /** 어떤 신호로 맞췄는지. 운영 중 사전 품질을 보는 데 쓴다 */
  by: "declared+price" | "prefix+price" | "price-only" | "prefix-only" | "none";
};

/**
 * 마스킹된 가맹점명을 금액과 함께 서비스에 매핑한다.
 *
 * 오픈뱅킹 카드청구상세정보조회는 가맹점명을 마스킹해서 주므로
 * (`merchant_name_masked`) 패턴 매칭만으로는 식별이 안 된다.
 * 구독료는 상수에 가까우므로 금액이 접두보다 판별력이 높다.
 *
 * 접두와 금액이 함께 맞을 때만 확정하고, 하나만 맞거나 후보가 여럿이면
 * 미분류로 남긴다 — 틀린 이름을 보여주는 것이 모르는 것보다 나쁘다.
 */
export function matchMaskedMerchant(
  masked: string,
  amount: number,
  /**
   * 온보딩에서 사용자가 "쓰고 있다"고 고른 서비스 id.
   *
   * **필터가 아니라 힌트다.** 선언되지 않은 구독도 계속 찾는다 — 사용자가 잊은
   * 구독을 찾아주는 것이 이 앱의 핵심 가치이므로, 선언 목록으로 걸러내면 안 된다.
   * 후보가 여럿일 때 선언된 쪽을 택하는 데만 쓴다. Claude Pro와 Perplexity Pro는
   * 둘 다 27,000원이라 선언 없이는 구분할 수 없다.
   */
  declared?: ReadonlySet<string>,
): MaskedMatch {
  const prefix = revealedPrefix(masked).toUpperCase();
  const normalized = normalizeMerchant(masked);

  const pool = SERVICES;
  const byPrefix = pool.filter((s) => s.maskedPrefixes?.some((p) => p.toUpperCase() === prefix));
  const byPrice = pool.filter((s) => priceMatches(s.prices, amount));

  // 선언된 서비스가 후보에 있으면 그것으로 모호성을 푼다
  if (declared && declared.size > 0) {
    const declaredHits = byPrice.filter((s) => declared.has(s.id));
    if (declaredHits.length === 1) {
      return { service: declaredHits[0]!, normalized, by: "declared+price" };
    }
  }

  const both = byPrefix.filter((s) => byPrice.includes(s));
  if (both.length === 1) {
    return { service: both[0]!, normalized, by: "prefix+price" };
  }

  // 접두가 겹치는 서비스가 여럿이어도(쿠팡플레이/쿠팡와우) 금액이 하나로 좁히면 확정
  if (both.length === 0 && byPrice.length === 1 && byPrefix.length === 0) {
    return { service: byPrice[0]!, normalized, by: "price-only" };
  }

  if (both.length === 0 && byPrefix.length === 1 && byPrice.length === 0) {
    return { service: byPrefix[0]!, normalized, by: "prefix-only" };
  }

  return { service: null, normalized, by: "none" };
}

/** 연간 결제를 제공하는 서비스만. 연 구독 탐색·질문의 대상 범위다. */
export const YEARLY_CAPABLE_SERVICES: ServiceDef[] = SERVICES.filter((s) =>
  s.cycles.includes("yearly"),
);

/** 이 서비스가 해당 주기로 결제될 수 있는가. 사전이 오판을 거부하는 장치다. */
export function supportsCycle(service: ServiceDef, cycle: "monthly" | "yearly"): boolean {
  return service.cycles.includes(cycle);
}

/** 연간권 가격 지문에 맞는가 */
export function matchesYearlyPrice(service: ServiceDef, amount: number): boolean {
  return (service.yearlyPrices ?? []).some((p) => Math.abs(p - amount) / p <= 0.05);
}
