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

/**
 * 공유받은 스크린샷 OCR 글자가 있으면 파싱해 저장한다. 방금 추가한 스토어 구독을 돌려준다.
 * 이미 저장된 것과 서비스 id로 합친다(최신 값으로 갱신).
 */
export function ingestPendingOcr(
  bridge: Pick<NativeBridge, "takePendingOcrText" | "getStoreSubs" | "saveStoreSubs">,
): StoreSubscription[] {
  const text = bridge.takePendingOcrText?.() ?? "";
  if (!text.trim()) return [];
  const found = parseStoreScreenshot(text);
  if (found.length === 0) return [];

  const byId = new Map(readStoreSubs(bridge).map((s) => [s.service.id, s]));
  for (const s of found) byId.set(s.service.id, s);
  bridge.saveStoreSubs?.(JSON.stringify(toStored([...byId.values()])));
  return found;
}
