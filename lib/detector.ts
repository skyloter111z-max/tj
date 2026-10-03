/**
 * 정기결제 판정 엔진 (spec/v5 §2.1).
 *
 * 입력: 오픈뱅킹 카드/계좌 API가 돌려준 건별 결제 내역
 * 출력: 구독 인벤토리 (서비스·금액·주기·다음 결제일·신뢰도)
 *
 * 사용자에게 아무것도 묻지 않는다. 최초 인증 1회가 전부다.
 */

import { matchMerchant, type ServiceDef } from "./merchants";

export type RawTransaction = {
  /** 카드 명세의 가맹점명 원문, 또는 계좌 거래내역의 통장인자내용 */
  merchantRaw: string;
  amount: number;
  /** YYYY-MM-DD */
  date: string;
  cardId?: string;
};

export type Cycle = "weekly" | "monthly" | "yearly";

export type PriceChange = {
  from: number;
  to: number;
  /** 인상이 관측된 결제일 */
  at: string;
};

export type DetectedSubscription = {
  service: ServiceDef | null;
  /** 사전 매칭 실패 시 정규화된 가맹점명을 그대로 보여준다 */
  displayName: string;
  merchantNormalized: string;
  amount: number;
  cycle: Cycle;
  /** YYYY-MM-DD */
  nextChargeDate: string;
  /** 0~1. 0.5 미만은 사용자에게 확인을 받는다 */
  confidence: number;
  occurrences: number;
  lastChargeDate: string;
  priceChange: PriceChange | null;
  /** 이번 배치에서 처음 등장한 구독 (spec/v5 §4-4 신규 구독 알림) */
  isNew: boolean;
};

const DAY_MS = 86_400_000;

/** 주기별 허용 간격(일). 결제일이 주말·공휴일로 밀리는 것을 흡수한다. */
const CYCLE_WINDOWS: Record<Cycle, { min: number; max: number; nominal: number }> = {
  weekly: { min: 5, max: 9, nominal: 7 },
  monthly: { min: 26, max: 35, nominal: 30 },
  yearly: { min: 350, max: 380, nominal: 365 },
};

function toDate(s: string): Date {
  return new Date(`${s}T00:00:00Z`);
}

function toISO(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function daysBetween(a: string, b: string): number {
  return Math.round((toDate(b).getTime() - toDate(a).getTime()) / DAY_MS);
}

function median(xs: number[]): number {
  if (xs.length === 0) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  if (s.length % 2 === 1) return s[mid]!;
  return (s[mid - 1]! + s[mid]!) / 2;
}

/** 간격의 중앙값으로 주기를 분류한다. 어느 창에도 안 들어가면 null. */
function classifyCycle(intervals: number[]): Cycle | null {
  if (intervals.length === 0) return null;
  const m = median(intervals);
  for (const [cycle, w] of Object.entries(CYCLE_WINDOWS) as [Cycle, typeof CYCLE_WINDOWS.monthly][]) {
    if (m >= w.min && m <= w.max) return cycle;
  }
  return null;
}

/**
 * 금액 안정성. 구독은 금액이 같거나, 한 번 계단식으로 바뀐다(요금 인상).
 * 값이 매번 다르게 출렁이면 구독이 아니라 같은 가맹점에서의 반복 구매다.
 *
 * 계단 변화와 무작위 변동을 구분하는 것이 핵심이다. 넷플릭스 광고형이
 * 5,500 → 7,000원으로 오른 것은 구독이고, 쿠팡에서 매달 다른 금액을 쓴 것은
 * 구독이 아니다. 둘 다 "편차가 크다"로 뭉치면 가격 인상 감지(spec/v5 §4-3)가
 * 동작하지 않는다.
 */
function amountStability(amounts: number[]): number {
  if (amounts.length < 2) return 1;

  const max = Math.max(...amounts);
  const min = Math.min(...amounts);
  if (max === 0) return 0;

  const distinct = new Set(amounts);
  if (distinct.size === 1) return 1;

  // 값이 바뀐 지점의 수. 계단이면 1이다.
  let steps = 0;
  for (let i = 1; i < amounts.length; i++) {
    if (amounts[i] !== amounts[i - 1]) steps++;
  }

  if (steps === 1 && distinct.size === 2) {
    // 한 번만 바뀌었고 값이 두 종류 — 요금 변경으로 본다.
    // 다만 배 이상 뛰는 것은 요금 인상이라기보다 다른 상품 결제다.
    return max / min <= 2.5 ? 0.95 : 0.3;
  }

  const spread = (max - min) / max;
  if (spread <= 0.05) return 1; // 환율·부가세 변동 흡수
  if (spread <= 0.2) return 0.6;
  return 0.1; // 반복 구매로 본다
}

/** 간격이 얼마나 규칙적인가. 중앙값에서 멀어질수록 낮아진다. */
function intervalRegularity(intervals: number[], cycle: Cycle): number {
  if (intervals.length === 0) return 0;
  const w = CYCLE_WINDOWS[cycle];
  const deviations = intervals.map((i) => Math.abs(i - w.nominal) / w.nominal);
  const avg = deviations.reduce((a, b) => a + b, 0) / deviations.length;
  return Math.max(0, 1 - avg * 2);
}

/** 관측 횟수가 많을수록 확신이 커진다. 2회는 우연일 수 있다. */
function occurrenceScore(n: number): number {
  if (n >= 4) return 0.9;
  if (n === 3) return 0.75;
  if (n === 2) return 0.5;
  return 0.2;
}

function detectPriceChange(sorted: RawTransaction[]): PriceChange | null {
  for (let i = sorted.length - 1; i > 0; i--) {
    const curr = sorted[i]!;
    const prev = sorted[i - 1]!;
    if (curr.amount !== prev.amount) {
      return { from: prev.amount, to: curr.amount, at: curr.date };
    }
  }
  return null;
}

export type DetectOptions = {
  /** 이 날짜 기준으로 다음 결제일을 계산한다. 기본값은 오늘. */
  today?: string;
  /** 이전 배치에서 이미 본 구독 키. 여기 없으면 isNew = true. */
  knownKeys?: ReadonlySet<string>;
  /** 이 값 미만의 신뢰도는 결과에서 제외한다. */
  minConfidence?: number;
};

/** 구독을 식별하는 안정적인 키. 사전 매칭 전후로 바뀌지 않아야 한다. */
export function subscriptionKey(sub: DetectedSubscription): string {
  return sub.service ? `svc:${sub.service.id}` : `raw:${sub.merchantNormalized}`;
}

/**
 * 건별 결제 내역에서 정기결제를 찾아낸다.
 *
 * 판정 규칙(spec/v5 §2.1):
 *   1. 동일 가맹점이 2회 이상 등장
 *   2. 금액이 동일하거나 소폭 변동
 *   3. 결제 간격이 주/월/연 창에 들어감
 *   4. 가맹점명 사전 매칭 시 신뢰도 가산
 */
export function detectSubscriptions(
  transactions: readonly RawTransaction[],
  options: DetectOptions = {},
): DetectedSubscription[] {
  const today = options.today ?? toISO(new Date());
  const known = options.knownKeys ?? new Set<string>();
  const minConfidence = options.minConfidence ?? 0.4;

  // 1. 정규화된 가맹점명으로 묶는다
  const groups = new Map<string, { txs: RawTransaction[]; service: ServiceDef | null }>();
  for (const tx of transactions) {
    const { service, normalized } = matchMerchant(tx.merchantRaw);
    const key = service ? `svc:${service.id}` : `raw:${normalized}`;
    const group = groups.get(key);
    if (group) {
      group.txs.push(tx);
    } else {
      groups.set(key, { txs: [tx], service });
    }
  }

  const results: DetectedSubscription[] = [];

  for (const [key, { txs, service }] of groups) {
    if (txs.length < 2) continue; // 1회 결제는 구독이 아니다

    const sorted = [...txs].sort((a, b) => a.date.localeCompare(b.date));
    const intervals: number[] = [];
    for (let i = 1; i < sorted.length; i++) {
      intervals.push(daysBetween(sorted[i - 1]!.date, sorted[i]!.date));
    }

    const cycle = classifyCycle(intervals);
    if (!cycle) continue; // 규칙적인 주기가 없으면 구독이 아니다

    const amounts = sorted.map((t) => t.amount);
    const confidence =
      occurrenceScore(sorted.length) *
      amountStability(amounts) *
      intervalRegularity(intervals, cycle) *
      (service ? 1 : 0.85); // 사전 미매칭은 신뢰도를 깎되 버리지 않는다

    if (confidence < minConfidence) continue;

    const last = sorted[sorted.length - 1]!;
    const nextDate = new Date(toDate(last.date).getTime() + CYCLE_WINDOWS[cycle].nominal * DAY_MS);

    results.push({
      service,
      displayName: service?.name ?? matchMerchant(last.merchantRaw).normalized,
      merchantNormalized: matchMerchant(last.merchantRaw).normalized,
      amount: last.amount,
      cycle,
      nextChargeDate: toISO(nextDate),
      confidence: Math.round(confidence * 100) / 100,
      occurrences: sorted.length,
      lastChargeDate: last.date,
      priceChange: detectPriceChange(sorted),
      isNew: !known.has(key),
    });
  }

  // 금액 큰 순. 사용자가 가장 먼저 봐야 하는 것이 맨 위다.
  return results.sort((a, b) => monthlyEquivalent(b) - monthlyEquivalent(a));
}

/** 주기가 다른 구독을 비교하기 위한 월 환산액 */
export function monthlyEquivalent(sub: DetectedSubscription): number {
  switch (sub.cycle) {
    case "weekly":
      return Math.round(sub.amount * 4.345);
    case "monthly":
      return sub.amount;
    case "yearly":
      return Math.round(sub.amount / 12);
  }
}

export function totalMonthly(subs: readonly DetectedSubscription[]): number {
  return subs.reduce((sum, s) => sum + monthlyEquivalent(s), 0);
}

/** D-Day. 음수면 이미 지났다. */
export function daysUntilCharge(sub: DetectedSubscription, today: string): number {
  return daysBetween(today, sub.nextChargeDate);
}
