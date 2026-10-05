/**
 * "주요 OTT 한눈에 보기" — 사람들이 많이 쓰는 OTT를 정해 두고, 가져온 결제에서
 * 각각을 찾았는지 한 화면에 보여 준다. 구독 전부가 아니라 대표 OTT만 추린다.
 */

import type { DetectedSubscription } from "./detector";
import { SERVICES, type ServiceDef } from "./merchants";

/** 사전의 OTT 카테고리 = 주요 OTT 목록 (넷플릭스·디즈니+·티빙·웨이브·쿠팡플레이·유튜브) */
export const OTT_WATCHLIST: ServiceDef[] = SERVICES.filter((s) => s.category === "ott");

export type OttStatus = {
  service: ServiceDef;
  /** 가져온 결제에서 찾은 구독. 없으면 null */
  found: DetectedSubscription | null;
};

/** 주요 OTT마다 "찾음/못 찾음"을 매긴다. 찾은 것이 위로 온다 */
export function ottStatuses(subs: readonly DetectedSubscription[]): OttStatus[] {
  const byId = new Map<string, DetectedSubscription>();
  for (const s of subs) if (s.service) byId.set(s.service.id, s);
  return OTT_WATCHLIST.map((service) => ({ service, found: byId.get(service.id) ?? null })).sort(
    (a, b) => Number(b.found !== null) - Number(a.found !== null),
  );
}

export function foundCount(statuses: readonly OttStatus[]): number {
  return statuses.filter((s) => s.found !== null).length;
}
