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
  },
  {
    id: "disneyplus",
    name: "디즈니+",
    category: "ott",
    patterns: [/DISNEY\s?\+?/, /DISNEYPLUS/, /디즈니/],
    cancelUrl: "https://www.disneyplus.com/account/subscription",
  },
  {
    id: "tving",
    name: "티빙",
    category: "ott",
    patterns: [/TVING/, /티빙/],
  },
  {
    id: "wavve",
    name: "웨이브",
    category: "ott",
    patterns: [/WAVVE/, /웨이브/],
  },
  {
    id: "coupangplay",
    name: "쿠팡플레이",
    category: "ott",
    patterns: [/COUPANG\s?PLAY/, /쿠팡플레이/],
  },
  {
    id: "youtubepremium",
    name: "유튜브 프리미엄",
    category: "ott",
    patterns: [/YOUTUBE\s?PREMIUM/, /YOUTUBEPREMIUM/, /유튜브\s?프리미엄/],
    cancelUrl: "https://www.youtube.com/paid_memberships",
  },

  // ── AI
  {
    id: "chatgpt",
    name: "ChatGPT",
    category: "ai",
    patterns: [/OPENAI/, /CHATGPT/],
    cancelUrl: "https://chatgpt.com/#settings/Subscription",
  },
  {
    id: "claude",
    name: "Claude",
    category: "ai",
    patterns: [/ANTHROPIC/, /CLAUDE\.?AI/],
    cancelUrl: "https://claude.ai/settings/billing",
  },
  {
    id: "gemini",
    name: "Google One / Gemini",
    category: "ai",
    patterns: [/GOOGLE\s?ONE/, /GOOGLEONE/],
    cancelUrl: "https://one.google.com/settings",
  },
  {
    id: "perplexity",
    name: "Perplexity",
    category: "ai",
    patterns: [/PERPLEXITY/],
  },
  {
    id: "cursor",
    name: "Cursor",
    category: "ai",
    patterns: [/CURSOR(\s|$)/, /ANYSPHERE/],
  },
  {
    id: "midjourney",
    name: "Midjourney",
    category: "ai",
    patterns: [/MIDJOURNEY/],
  },

  // ── 음악
  {
    id: "spotify",
    name: "스포티파이",
    category: "music",
    patterns: [/SPOTIFY/, /스포티파이/],
  },
  {
    id: "melon",
    name: "멜론",
    category: "music",
    patterns: [/MELON/, /멜론/, /KAKAO\s?ENTERTAINMENT/],
  },

  // ── 커머스·기타
  {
    id: "coupangwow",
    name: "쿠팡 와우",
    category: "commerce",
    patterns: [/COUPANG\s?WOW/, /쿠팡와우/, /와우멤버십/],
  },
  {
    id: "naverplus",
    name: "네이버플러스",
    category: "commerce",
    patterns: [/NAVER\s?PLUS/, /네이버플러스/, /네이버\s?멤버십/],
  },
  {
    id: "icloud",
    name: "iCloud+",
    category: "cloud",
    patterns: [/ICLOUD/, /APPLE\s?ONE/],
  },
  {
    id: "ms365",
    name: "Microsoft 365",
    category: "cloud",
    patterns: [/MICROSOFT\s?365/, /MSFT\s?365/, /OFFICE\s?365/],
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
