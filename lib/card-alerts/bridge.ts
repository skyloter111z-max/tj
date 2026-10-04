/**
 * 안드로이드 앱(android/)이 WebView에 심는 `window.SubmoaBridge`와의 접점.
 *
 * 앱은 폰에 뜨는 알림 중 카드 결제 알림만 골라 폰 안에 쌓아 두고(AlertListenerService),
 * 웹은 그것을 받아 parse.ts → detector로 판정한다. 결제 알림은 서버로 가지 않는다.
 * 브라우저·아이폰에서는 브리지가 없다 — 아이폰은 다른 앱의 알림을 읽을 수 없다.
 */

import type { AlertMessage } from "./parse";

/** 앱이 저장한 알림 한 건 (AlertStore.toJson) */
export type CapturedAlert = { body: string; postedAt: number };

export type NativeBridge = {
  isAccessGranted(): boolean;
  openAccessSettings(): void;
  /** CapturedAlert[]의 JSON */
  getAlerts(): string;
};

/** 앱이 설정 화면에서 돌아올 때 쏘는 이벤트 (MainActivity.onResume) */
export const RESUME_EVENT = "submoa:resume";

export function nativeBridge(): NativeBridge | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { SubmoaBridge?: NativeBridge }).SubmoaBridge ?? null;
}

const KST_OFFSET_MS = 9 * 60 * 60 * 1000;

/** 알림 수신 시각 → 한국 날짜. 폰의 시간대 설정과 무관하게 카드사 기준일을 쓴다 */
export function kstDate(epochMs: number): string {
  return new Date(epochMs + KST_OFFSET_MS).toISOString().slice(0, 10);
}

function isCaptured(x: unknown): x is CapturedAlert {
  if (typeof x !== "object" || x === null) return false;
  const o = x as Record<string, unknown>;
  return typeof o.body === "string" && typeof o.postedAt === "number" && Number.isFinite(o.postedAt);
}

/** 브리지 응답을 판정 입력으로. 깨진 응답은 빈 목록으로 본다 */
export function readCapturedAlerts(bridge: Pick<NativeBridge, "getAlerts">): AlertMessage[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(bridge.getAlerts());
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(isCaptured).map(({ body, postedAt }) => ({ body, receivedAt: kstDate(postedAt) }));
}
