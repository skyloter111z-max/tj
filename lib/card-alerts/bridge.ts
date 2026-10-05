/**
 * 안드로이드 앱(android/)이 WebView에 심는 `window.SubmoaBridge`와의 접점.
 *
 * 앱은 카드 결제 알림만 골라 폰 안에 쌓아 두고, 웹은 그것을 받아 parse.ts → detector로 판정한다.
 * 결제 알림은 서버로 가지 않는다.
 *
 *   android  알림 접근 권한으로 카톡·문자·카드사 앱 알림을 읽는다 (android/)
 *   ios      다른 앱 알림은 못 읽는다. 단축어 "메시지" 자동화가 문자를 넘겨준다 (ios/)
 *   브라우저 브리지가 없다
 */

import type { AlertMessage } from "./parse";

/** 앱이 저장한 알림 한 건 (AlertStore.toJson) */
export type CapturedAlert = { body: string; postedAt: number };

export type Platform = "android" | "ios";

export type NativeBridge = {
  platform?(): string;
  /** android: 알림 접근이 켜져 있다 / ios: 단축어가 결제 문자를 한 번이라도 넘겼다 */
  isAccessGranted(): boolean;
  /** android: 알림 접근 설정 화면 / ios: 단축어 앱 */
  openAccessSettings(): void;
  /** CapturedAlert[]의 JSON */
  getAlerts(): string;
  /** 카톡 내보내기를 공유받은 원본. 꺼내는 순간 기기에서 지워진다 (android ImportStore) */
  takePendingExport?(): string;
  /** 원본에서 골라낸 카드 결제 알림만 저장한다 — AlertMessage[]의 JSON */
  saveImportedAlerts?(json: string): void;
  getImportedAlerts?(): string;
  clearImported?(): void;
  openKakaoTalk?(): void;
  /** 화면 캡처로 스토어 구독 화면을 자동으로 읽기 시작한다 (android, MediaProjection) */
  startStoreCapture?(): void;
  /** 스토어 구독 스크린샷을 OCR한 글자. 꺼내는 순간 지워진다 (android) */
  takePendingOcrText?(): string;
  /** 웹이 OCR 글자에서 뽑은 스토어 구독 [{id, amount, cycle}]의 JSON을 저장한다 */
  saveStoreSubs?(json: string): void;
  getStoreSubs?(): string;
  clearStoreSubs?(): void;
  /** 디버그 빌드 전용: 실제 결제 없이 모의 결제 알림을 폰에 띄워 알림 읽기 전체를 시험한다 */
  canSimulate?(): boolean;
  simulatePaymentAlert?(): void;
  clearSimulated?(): void;
};

/** 앱이 설정 화면에서 돌아올 때 쏘는 이벤트 (MainActivity.onResume) */
export const RESUME_EVENT = "submoa:resume";

export function bridgePlatform(bridge: Pick<NativeBridge, "platform">): Platform {
  return bridge.platform?.() === "ios" ? "ios" : "android";
}

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

function isAlertMessage(x: unknown): x is AlertMessage {
  if (typeof x !== "object" || x === null) return false;
  const o = x as Record<string, unknown>;
  return typeof o.body === "string" && typeof o.receivedAt === "string" && /^\d{4}-\d{2}-\d{2}$/.test(o.receivedAt);
}

/** 카톡 내보내기로 가져와 저장해 둔 카드 결제 알림 */
export function readImportedAlerts(bridge: Pick<NativeBridge, "getImportedAlerts">): AlertMessage[] {
  if (!bridge.getImportedAlerts) return [];
  try {
    const parsed: unknown = JSON.parse(bridge.getImportedAlerts());
    return Array.isArray(parsed) ? parsed.filter(isAlertMessage) : [];
  } catch {
    return [];
  }
}
