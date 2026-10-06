/**
 * 안드로이드 브리지에 저장된 스토어 구독을 읽고, OCR 글자를 받아 파싱해 저장한다.
 */

import type { NativeBridge } from "../card-alerts/bridge";
import { findService } from "../merchants";
import { inferFromAppScreen } from "./app-screens";
import {
  parseStoreScreenshot,
  parseStoreScreenshotFor,
  toStored,
  type StoreSubscription,
} from "./parse";

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
    const { id, amount, cycle, billedVia } = row as Record<string, unknown>;
    const service = typeof id === "string" ? findService(id) : undefined;
    if (!service || typeof amount !== "number" || (cycle !== "monthly" && cycle !== "yearly")) continue;
    const via = typeof billedVia === "string" && findService(billedVia) ? billedVia : undefined;
    out.push({ service, amount, cycle, ...(via ? { billedVia: via } : {}) });
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
 * 읽은 화면 한 장: 글자와, 어느 서비스 화면이었는지(없으면 ""). 네이티브 StoreStore와 짝.
 * trusted: 그 서비스 앱 안에서 읽었다 — 화면에 서비스 이름이 없어도 그 서비스로 해석한다.
 */
type OcrScreen = { id: string; text: string; trusted?: boolean };

function parseScreens(raw: string): OcrScreen[] {
  const trimmed = raw.trim();
  if (!trimmed) return [];
  // 새 형식: [{id, text}]. 옛 형식(그냥 글자 하나)도 안전하게 받아 일반 해석한다.
  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed)) {
      return parsed
        .filter((r): r is OcrScreen => typeof r === "object" && r !== null && typeof (r as OcrScreen).text === "string")
        .map((r) => ({ id: typeof r.id === "string" ? r.id : "", text: r.text, trusted: r.trusted === true }));
    }
  } catch {
    // JSON이 아니면 글자 하나로 본다
  }
  return [{ id: "", text: trimmed }];
}

/**
 * 캡처/공유한 화면들의 OCR 글자가 있으면 파싱해 저장한다. 방금 추가한 스토어 구독을 돌려준다.
 * 이미 저장된 것과 서비스 id로 합친다(최신 값으로 갱신).
 *
 * 화면마다 어느 서비스였는지(id)를 알면 그 서비스를 노려 해석하므로("모두 읽기"에서 각 OTT 화면),
 * 이름과 금액이 떨어져 있어도 잡는다. 글자가 있었는지(readText)도 같이 돌려준다: 화면은 읽혔는데
 * 아는 구독이 없을 때와, 캡처 자체가 빈 화면이라 읽을 글자가 없었을 때를 홈에서 다르게 안내한다.
 */
export function ingestPendingOcr(
  bridge: Pick<NativeBridge, "takePendingOcrText" | "getStoreSubs" | "saveStoreSubs">,
): OcrIngest {
  const screens = parseScreens(bridge.takePendingOcrText?.() ?? "");
  if (screens.length === 0) return { found: [], readText: false };

  const found: StoreSubscription[] = [];
  const add = (s: StoreSubscription) => {
    if (!found.some((x) => x.service.id === s.service.id)) found.push(s);
  };
  for (const screen of screens) {
    if (!screen.text.trim()) continue;
    // 서비스 앱 안 화면: 그 앱을 아는 해석(요금제 → 금액, 묶음 멤버십)을 먼저 한다.
    // 앱 안 화면엔 금액이 없는 경우가 많고("광고형 스탠다드 멤버십", "WOW! 와우회원"), 일반 해석보다 정확하다.
    if (screen.trusted && screen.id) for (const s of inferFromAppScreen(screen.text, screen.id)) add(s);
    for (const s of parseStoreScreenshot(screen.text)) add(s);
    // 이 화면이 특정 OTT 것이면, 일반 해석이 놓쳤을 때 그 하나만 노려 다시 본다
    if (screen.id && !found.some((s) => s.service.id === screen.id)) {
      const one = parseStoreScreenshotFor(screen.text, screen.id, { trusted: screen.trusted });
      if (one) add(one);
    }
  }
  if (found.length === 0) return { found: [], readText: true };

  const byId = new Map(readStoreSubs(bridge).map((s) => [s.service.id, s]));
  for (const s of found) byId.set(s.service.id, s);
  bridge.saveStoreSubs?.(JSON.stringify(toStored([...byId.values()])));
  return { found, readText: true };
}
