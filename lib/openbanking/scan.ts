/**
 * 가입 시 스캔 오케스트레이션 (spec/v5 §3.1).
 *
 *   0단계  온보딩 선언 (조회 0회)
 *   1단계  전 카드 × 13개월 총액 추이       = 카드당 1~2회
 *   2단계  활성 카드 × 최근 3개월 상세      = 카드당 최대 9회, 선언분 다 찾으면 중단
 *   3단계  연간권 있는 서비스만, 튀는 달 상세 = 건당 3회
 *
 * 비싼 것은 상세 조회다. 이 모듈의 유일한 목적은 **상세 조회를 아끼는 것**이고,
 * 호출 수를 세어 돌려주므로 테스트로 비용 가정을 고정할 수 있다.
 */

import { detectSubscriptions, type DetectedSubscription, type RawTransaction } from "../detector";
import { findService, matchMaskedMerchant, supportsCycle } from "../merchants";
import { findSpikeMonths, isActiveCard, parseBillBasic, parseBillDetail, type MonthlyTotal } from "./parse";
import type { BillBasicResponse, BillDetailResponse, Card, CardListResponse } from "./types";

/** API 호출을 주입받는다 — 테스트에서 가짜 구현을 넣어 호출 수를 센다 */
export type ScanDeps = {
  fetchCardList(): Promise<CardListResponse>;
  fetchBillBasic(args: {
    card: Card;
    fromMonth: string;
    toMonth: string;
    traceInfo?: string;
  }): Promise<BillBasicResponse>;
  fetchBillDetail(args: {
    card: Card;
    chargeMonth: string;
    settlementSeqNo: string;
    traceInfo?: string;
  }): Promise<BillDetailResponse>;
};

export type ScanOptions = {
  /** 오늘 (YYYY-MM-DD). 조회 범위 계산 기준 */
  today: string;
  /** 0단계에서 사용자가 선언한 서비스 id */
  declared?: ReadonlySet<string>;
  /** 2단계에서 카드별로 훑을 최근 개월 수 */
  recentMonths?: number;
  /** 1단계에서 받을 총 개월 수. 13개월이면 연 구독이 2회 관측된다 */
  trendMonths?: number;
  /** 안전장치 — 이 호출 수를 넘으면 스캔을 중단한다 */
  maxCalls?: number;
};

export type ScanResult = {
  subscriptions: DetectedSubscription[];
  /** 취소·환불 건. 해지 신호로 쓴다 */
  refunds: RawTransaction[];
  /** 실제 호출 수. 비용 추적용 */
  calls: { basic: number; detail: number; cardList: number; total: number };
  /** 선언했는데 못 찾은 서비스 id */
  declaredNotFound: string[];
  /** 선언하지 않았는데 발견된 구독 — "이것도 쓰시나요?" 대상 */
  undeclared: DetectedSubscription[];
  /** maxCalls에 걸려 중단됐는가 */
  truncated: boolean;
};

/** "2026-10-03", -12 → "202510" */
function shiftMonth(today: string, delta: number): string {
  const [y, m] = [Number(today.slice(0, 4)), Number(today.slice(5, 7))];
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** 페이지를 끝까지 순회한다. 상세 조회는 한 페이지 최대 20건이다 */
async function fetchAllDetailPages(
  deps: ScanDeps,
  card: Card,
  month: MonthlyTotal,
  budget: { left: number },
): Promise<{ transactions: RawTransaction[]; refunds: RawTransaction[]; calls: number }> {
  const transactions: RawTransaction[] = [];
  const refunds: RawTransaction[] = [];
  let calls = 0;
  let traceInfo: string | undefined;

  for (;;) {
    if (budget.left <= 0) break;
    const res = await deps.fetchBillDetail({
      card,
      chargeMonth: month.chargeMonth,
      settlementSeqNo: month.settlementSeqNo,
      traceInfo,
    });
    calls++;
    budget.left--;

    const parsed = parseBillDetail(res);
    transactions.push(...parsed.transactions);
    refunds.push(...parsed.refunds);

    if (res.next_page_yn !== "Y") break;
    traceInfo = res.befor_inquiry_trace_info;
    // 추적정보 없이 Y가 오면 무한루프가 된다 — 방어
    if (!traceInfo) break;
  }

  return { transactions, refunds, calls };
}

/**
 * 월별 총액의 변동계수(표준편차 / 평균).
 * 0에 가까우면 매달 같은 금액 — 정기결제가 지배하는 카드다.
 */
function coefficientOfVariation(totals: readonly MonthlyTotal[]): number {
  const xs = totals.map((t) => t.amount).filter((a) => a > 0);
  if (xs.length < 2) return Number.POSITIVE_INFINITY;
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  if (mean <= 0) return Number.POSITIVE_INFINITY;
  const variance = xs.reduce((s, x) => s + (x - mean) ** 2, 0) / xs.length;
  return Math.sqrt(variance) / mean;
}

/** 지금까지 찾은 구독이 선언 목록을 전부 덮었는가 */
function coversDeclared(
  subs: readonly DetectedSubscription[],
  declared: ReadonlySet<string>,
): boolean {
  if (declared.size === 0) return false;
  const found = new Set(subs.map((s) => s.service?.id).filter(Boolean) as string[]);
  for (const id of declared) if (!found.has(id)) return false;
  return true;
}

export async function runSignupScan(
  deps: ScanDeps,
  options: ScanOptions,
): Promise<ScanResult> {
  const {
    today,
    declared = new Set<string>(),
    recentMonths = 3,
    trendMonths = 13,
    maxCalls = 200,
  } = options;

  const budget = { left: maxCalls };
  const calls = { basic: 0, detail: 0, cardList: 0, total: 0 };
  const allTx: RawTransaction[] = [];
  const allRefunds: RawTransaction[] = [];

  // ── 1단계: 카드 목록 + 전 카드 13개월 총액 추이
  const cardListRes = await deps.fetchCardList();
  calls.cardList++;
  budget.left--;

  const fromMonth = shiftMonth(today, -(trendMonths - 1));
  const toMonth = shiftMonth(today, 0);

  type CardTrend = { card: Card; totals: MonthlyTotal[] };
  const trends: CardTrend[] = [];

  for (const card of cardListRes.card_list ?? []) {
    const totals: MonthlyTotal[] = [];
    let traceInfo: string | undefined;
    for (;;) {
      if (budget.left <= 0) break;
      const res = await deps.fetchBillBasic({ card, fromMonth, toMonth, traceInfo });
      calls.basic++;
      budget.left--;
      totals.push(...parseBillBasic(res));
      if (res.next_page_yn !== "Y" || !res.befor_inquiry_trace_info) break;
      traceInfo = res.befor_inquiry_trace_info;
    }
    trends.push({ card, totals });
  }

  // 활성 카드만 남기고, **월별 총액이 고른 순**으로 본다.
  //
  // 총액이 큰 순은 틀린 기준이다 — 구독은 금액이 작으므로 마트 결제가 많은 카드에
  // 밀린다. 구독이 걸린 카드는 매달 비슷한 금액이 찍히므로 변동계수(CV)가 낮다.
  // 불규칙한 쇼핑에 쓰는 카드는 CV가 높다.
  //
  // ⚠️ 이 순서는 약한 신호다. 총액만으로 카드를 정확히 가릴 수는 없다. 조기 종료의
  //    실익은 "평균적으로 활성 카드의 일부만 스캔한다"는 것이고, 최악의 경우는
  //    전부 스캔하는 것(= 조기 종료가 없는 것)이다.
  const active = trends
    .filter((t) => isActiveCard(t.totals))
    .sort((a, b) => coefficientOfVariation(a.totals) - coefficientOfVariation(b.totals));

  // ── 2단계: 활성 카드의 최근 N개월 상세. 선언분을 다 찾으면 중단
  for (const { card, totals } of active) {
    const recent = totals.slice(-recentMonths);
    for (const month of recent) {
      const page = await fetchAllDetailPages(deps, card, month, budget);
      calls.detail += page.calls;
      allTx.push(...page.transactions);
      allRefunds.push(...page.refunds);
    }

    const soFar = detectSubscriptions(allTx, { today, masked: true, declared });
    if (coversDeclared(soFar, declared)) break; // 조기 종료
    if (budget.left <= 0) break;
  }

  // ── 3단계: 연 구독. 연간권이 있는 서비스만 대상으로, 총액이 튀는 달만 본다
  const yearlyWanted = [...declared]
    .map((id) => findService(id))
    .filter((s): s is NonNullable<typeof s> => Boolean(s) && supportsCycle(s!, "yearly"));

  if (yearlyWanted.length > 0) {
    const alreadyFound = new Set(
      detectSubscriptions(allTx, { today, masked: true, declared })
        .filter((s) => s.cycle === "yearly")
        .map((s) => s.service?.id),
    );
    const missing = yearlyWanted.filter((s) => !alreadyFound.has(s.id));

    if (missing.length > 0) {
      for (const { card, totals } of active) {
        if (budget.left <= 0) break;
        const scanned = new Set(totals.slice(-recentMonths).map((t) => t.chargeMonth));
        for (const spike of findSpikeMonths(totals)) {
          if (budget.left <= 0) break;
          if (scanned.has(spike.chargeMonth)) continue; // 2단계에서 이미 봤다
          const page = await fetchAllDetailPages(deps, card, spike, budget);
          calls.detail += page.calls;
          allTx.push(...page.transactions);
          allRefunds.push(...page.refunds);
        }
      }
    }
  }

  calls.total = calls.cardList + calls.basic + calls.detail;

  const subscriptions = detectSubscriptions(allTx, { today, masked: true, declared });
  const foundIds = new Set(subscriptions.map((s) => s.service?.id).filter(Boolean) as string[]);

  return {
    subscriptions,
    refunds: allRefunds,
    calls,
    declaredNotFound: [...declared].filter((id) => !foundIds.has(id)),
    undeclared: subscriptions.filter((s) => !s.service || !declared.has(s.service.id)),
    truncated: budget.left <= 0,
  };
}

/** 마스킹된 가맹점명을 선언 힌트와 함께 해석한다 — UI에서 후보 제시용 */
export function interpretMasked(
  masked: string,
  amount: number,
  declared?: ReadonlySet<string>,
) {
  return matchMaskedMerchant(masked, amount, declared);
}
