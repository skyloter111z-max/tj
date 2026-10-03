/**
 * 오픈뱅킹 응답 → 판정 엔진 입력(RawTransaction) 변환.
 *
 * API는 금액과 날짜를 문자열로 주고, 금액에 음수(취소·환불)가 섞인다.
 */

import type { RawTransaction } from "../detector";
import type { BillBasicItem, BillBasicResponse, BillDetailResponse } from "./types";

/** "20190110" → "2019-01-10" */
export function toIsoDate(yyyymmdd: string): string {
  const s = yyyymmdd.trim();
  if (!/^\d{8}$/.test(s)) throw new Error(`날짜 형식이 아님: ${yyyymmdd}`);
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
}

/** "456000" → 456000. 공백·쉼표·부호를 흡수한다 */
export function toAmount(raw: string): number {
  const n = Number(String(raw).replace(/[,\s]/g, ""));
  if (!Number.isFinite(n)) throw new Error(`금액 형식이 아님: ${raw}`);
  return n;
}

/**
 * 청구상세 응답을 RawTransaction[]으로 바꾼다.
 *
 * 음수·0원 건은 제외한다 — 취소·환불은 구독 결제가 아니고, 주기 판정을 교란한다.
 * 다만 **환불이 있었다는 사실 자체는 구독 해지 신호**이므로, 별도로 돌려준다.
 */
export function parseBillDetail(res: BillDetailResponse): {
  transactions: RawTransaction[];
  refunds: RawTransaction[];
} {
  const transactions: RawTransaction[] = [];
  const refunds: RawTransaction[] = [];

  for (const item of res.bill_list ?? []) {
    const amount = toAmount(item.paid_amt);
    const tx: RawTransaction = {
      merchantRaw: item.merchant_name_masked,
      amount: Math.abs(amount),
      date: toIsoDate(item.paid_date),
      cardId: item.card_value,
    };
    if (amount > 0) transactions.push(tx);
    else if (amount < 0) refunds.push(tx);
  }

  return { transactions, refunds };
}

export type MonthlyTotal = {
  /** YYYYMM */
  chargeMonth: string;
  amount: number;
  settlementSeqNo: string;
};

/** 청구기본 응답 → 월별 총액. 결제순번이 없는 달은 상세 조회를 할 수 없으므로 버린다 */
export function parseBillBasic(res: BillBasicResponse): MonthlyTotal[] {
  const out: MonthlyTotal[] = [];
  for (const item of res.bill_list ?? []) {
    if (!item.settlement_seq_no) continue;
    out.push({
      chargeMonth: item.charge_month,
      amount: toAmount(item.charge_amt),
      settlementSeqNo: item.settlement_seq_no,
    });
  }
  return out.sort((a, b) => a.chargeMonth.localeCompare(b.chargeMonth));
}

/**
 * 총액이 튀는 달을 찾는다 — 연 구독 후보.
 *
 * 연 구독은 금액이 크고 한 달에만 찍히므로, 중앙값 대비 크게 벗어난 달을 고른다.
 * 그 달만 비싼 상세 조회를 쓴다 (spec/v5 §3.1 3단계).
 */
export function findSpikeMonths(
  totals: readonly MonthlyTotal[],
  /** 중앙값의 몇 배를 넘으면 튄 것으로 보는가 */
  threshold = 1.5,
): MonthlyTotal[] {
  const amounts = totals.map((t) => t.amount).filter((a) => a > 0);
  if (amounts.length < 3) return [];

  const sorted = [...amounts].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 1 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
  if (median <= 0) return [];

  return totals
    .filter((t) => t.amount > median * threshold)
    .sort((a, b) => b.amount - a.amount);
}

/** 총액이 0인 달만 있는 카드는 비활성이다 — 상세 조회할 이유가 없다 */
export function isActiveCard(totals: readonly MonthlyTotal[]): boolean {
  return totals.some((t) => t.amount > 0);
}

/** 기본조회 응답 항목에 결제순번이 비어 있으면 상세 조회가 불가능하다 */
export function hasSettlementSeq(item: BillBasicItem): boolean {
  return Boolean(item.settlement_seq_no);
}
