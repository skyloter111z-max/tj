/**
 * 안드로이드 브리지에 저장된 스토어 구독을 읽고, OCR 글자를 받아 파싱해 저장한다.
 */

import type { NativeBridge } from "../card-alerts/bridge";
import { findService } from "../merchants";
import { parseStoreScreenshot, toStored, type StoreSubscription } from "./parse";

/** 저장된 스토어 구독을 복원한다. 사전에서 사라진 id는 버린다 */
export function readStoreSubs(bridge: Pick<NativeBridge, "getStoreSubs">): StoreSubscription[] {
  if (!bridge.getStoreSubs) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(bridge.getStoreSubs());
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: StoreSubscription[] = [];
  for (const row of parsed) {
    if (typeof row !== "object" || row === null) continue;
    const { id, amount, cycle } = row as Record<string, unknown>;
    const service = typeof id === "string" ? findService(id) : undefined;
    if (!service || typeof amount !== "number" || (cycle !== "monthly" && cycle !== "yearly")) continue;
    out.push({ service, amount, cycle });
  }
  return out;
}

export type OcrIngest = {
  /** 이번에 새로 뽑은 스토어 구독 */
  found: StoreSubscription[];
  /** 화면을 읽긴 했다(글자가 있었다) — 못 알아본 건지, 아예 못 읽은 건지 구분하려고 */
  readText: boolean;
};

/**
 * 공유받은/캡처한 스크린샷 OCR 글자가 있으면 파싱해 저장한다. 방금 추가한 스토어 구독을 돌려준다.
 * 이미 저장된 것과 서비스 id로 합친다(최신 값으로 갱신).
 *
 * 글자가 있었는지(readText)도 같이 돌려준다: 화면은 읽혔는데 아는 구독이 없을 때와,
 * 캡처 자체가 빈 화면이라 읽을 글자가 없었을 때를 홈에서 다르게 안내하기 위해서다.
 */
export function ingestPendingOcr(
  bridge: Pick<NativeBridge, "takePendingOcrText" | "getStoreSubs" | "saveStoreSubs">,
): OcrIngest {
  const text = bridge.takePendingOcrText?.() ?? "";
  if (!text.trim()) return { found: [], readText: false };
  const found = parseStoreScreenshot(text);
  if (found.length === 0) return { found: [], readText: true };

  const byId = new Map(readStoreSubs(bridge).map((s) => [s.service.id, s]));
  for (const s of found) byId.set(s.service.id, s);
  bridge.saveStoreSubs?.(JSON.stringify(toStored([...byId.values()])));
  return { found, readText: true };
}
