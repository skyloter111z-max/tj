/**
 * 카톡 "대화 내용 내보내기"로 공유받은 원본 → 카드 결제 알림만.
 *
 * 앱은 원본을 한 번 넘겨주고 지운다. 여기서 골라낸 것만 기기에 남는다 — 사용자가 카드사
 * 알림방이 아닌 개인 대화를 잘못 공유해도 대화 내용은 저장되지 않는다.
 */

import { exportSpan, parseKakaoExport } from "./kakao-export";
import { parseCardAlert, type AlertMessage } from "./parse";

export type ImportResult = {
  /** 카드 결제 알림(결제·취소·결제대금 미포함)만 */
  alerts: AlertMessage[];
  /** 그중 결제 건수 */
  payments: number;
  span: { from: string; to: string } | null;
};

export function extractCardAlerts(raw: string): ImportResult {
  const alerts: AlertMessage[] = [];
  let payments = 0;
  for (const message of parseKakaoExport(raw)) {
    const alert = parseCardAlert(message.body, message.receivedAt);
    if (!alert) continue;
    alerts.push(message);
    if (alert.kind === "charge") payments++;
  }
  return { alerts, payments, span: exportSpan(alerts) };
}
