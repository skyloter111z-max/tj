/**
 * 홈 화면 데이터. 앱이 모은 결제 알림 → 구독 판정 → 화면에 필요한 모양.
 *
 * "새로 생긴 정기결제"(spec/v5 §4-4)는 처음 찾은 날로부터 며칠간 보여 준다.
 * 알림은 허용한 뒤부터만 오므로, 여기서 "새로"는 "구독이 새로 생겼다"가 아니라
 * "이 앱이 새로 찾았다"는 뜻이다 — 화면 문구도 그에 맞춘다.
 */

import type { AlertMessage } from "./card-alerts/parse";
import { collectTransactions } from "./card-alerts/parse";
import {
  detectSubscriptions,
  subscriptionKey,
  type DetectedSubscription,
  type RawTransaction,
} from "./detector";

/** 구독 키 → 처음 찾은 날짜(YYYY-MM-DD) */
export type SeenMap = Record<string, string>;

/** 처음 찾은 뒤 이 기간 동안 "새로 찾은 구독"으로 띄운다 */
export const NEW_FOR_DAYS = 7;

const DAY_MS = 86_400_000;

function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);
}

/** 처음 찾은 지 NEW_FOR_DAYS가 지난 구독 키 — 판정 엔진의 knownKeys로 넘긴다 */
export function knownKeys(seen: SeenMap, today: string): Set<string> {
  return new Set(Object.entries(seen).filter(([, first]) => daysBetween(first, today) >= NEW_FOR_DAYS).map(([k]) => k));
}

/** 이번에 처음 본 키에 오늘 날짜를 붙인다. 이미 본 키의 날짜는 건드리지 않는다 */
export function markSeen(seen: SeenMap, keys: readonly string[], today: string): SeenMap {
  const next = { ...seen };
  for (const k of keys) next[k] ??= today;
  return next;
}

export type LiveHome = {
  /** 지금 나가고 있는 구독 */
  subs: DetectedSubscription[];
  /** 해지한 것으로 보이는 구독 수 */
  ended: number;
  /** 최근 결제 알림 — 알림 읽기가 동작하는지 사용자가 바로 확인한다 */
  recent: RawTransaction[];
  /** 지금까지 읽은 결제 건수 */
  paymentCount: number;
  /** 저장할 SeenMap */
  seen: SeenMap;
};

export function buildLiveHome(messages: readonly AlertMessage[], today: string, seen: SeenMap): LiveHome {
  const { transactions } = collectTransactions(messages);
  const all = detectSubscriptions(transactions, { today, knownKeys: knownKeys(seen, today) });
  const recent = [...transactions].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 5);
  return {
    subs: all.filter((s) => s.active),
    ended: all.filter((s) => !s.active).length,
    recent,
    paymentCount: transactions.length,
    seen: markSeen(seen, all.map(subscriptionKey), today),
  };
}
