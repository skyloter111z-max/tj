/**
 * 카드 결제 알림 본문 → 판정 엔진 입력(RawTransaction) 변환.
 *
 * 같은 본문이 두 경로로 들어온다:
 *   - 카카오톡 카드사 알림방 "대화 내용 내보내기" 파일 (가입 시 과거 내역)
 *   - 안드로이드 알림 접근으로 받은 알림톡·푸시 (이후 실시간)
 *
 * 알림에는 가맹점명이 마스킹 없이 들어온다. 오픈뱅킹과 달리 `masked` 옵션이 필요 없다.
 * 본문의 날짜에는 연도가 없으므로("10/03 21:24") 메시지를 받은 날짜에서 연도를 가져온다.
 * 이름("김*진")은 읽지 않는다.
 */

import type { RawTransaction } from "../detector";

export type CardAlert =
  | {
      kind: "charge";
      transaction: RawTransaction;
      /** HH:MM */
      time: string;
      /** 일시불은 1 */
      installmentMonths: number;
    }
  /** 온누리상품권 사용처럼 승인 알림은 왔지만 카드 결제대금에는 들어가지 않는 건 */
  | { kind: "not-billed"; amount: number };

export type AlertMessage = {
  body: string;
  /** 메시지를 받은 날짜 YYYY-MM-DD (내보내기 파일의 날짜 구분선, 또는 알림 수신 시각) */
  receivedAt: string;
};

/**
 * 삼성카드 승인 알림.
 *
 *   삼성1088승인 김*진
 *   88,000원 일시불
 *   10/03 21:24 바다이야기
 *
 * 알림톡은 3줄, 알림 미리보기는 한 줄로 합쳐질 수 있어 필드 사이는 `\s+`로 받는다.
 * 가맹점명만 줄 끝에서 끊는다.
 */
const SAMSUNG_APPROVAL =
  /삼성(\d{4})승인(?:\s+[^\s\d]\S*)?\s+([\d,]+)원\s+(일시불|\d{1,2}개월)\s+(\d{2})\/(\d{2})\s+(\d{2}):(\d{2})\s+([^\n]+?)\s*$/m;

const NOT_BILLED = /결제대금에\s*미포함/;

function toAmount(raw: string): number {
  return Number(raw.replace(/,/g, ""));
}

/**
 * 연도 없는 MM/DD에 연도를 붙인다.
 * 12/31 결제 알림을 1/1에 받았다면 전년도다.
 */
export function inferDate(month: number, day: number, receivedAt: string): string | null {
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  const receivedYear = Number(receivedAt.slice(0, 4));
  const receivedMonth = Number(receivedAt.slice(5, 7));
  const year = month > receivedMonth ? receivedYear - 1 : receivedYear;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** 알림 한 건을 해석한다. 결제 알림이 아니면(챗봇 안내·광고 등) null */
export function parseCardAlert(body: string, receivedAt: string): CardAlert | null {
  if (NOT_BILLED.test(body)) {
    const m = body.match(/([\d,]+)원/);
    return m ? { kind: "not-billed", amount: toAmount(m[1]!) } : null;
  }

  const m = body.match(SAMSUNG_APPROVAL);
  if (!m) return null;
  const [, last4, amount, installment, month, day, hh, mm, merchant] = m;
  const date = inferDate(Number(month), Number(day), receivedAt);
  if (!date) return null;

  return {
    kind: "charge",
    transaction: {
      merchantRaw: merchant!,
      amount: toAmount(amount!),
      date,
      cardId: `samsung-${last4}`,
    },
    time: `${hh}:${mm}`,
    installmentMonths: installment === "일시불" ? 1 : Number(installment!.replace("개월", "")),
  };
}

/**
 * 알림 묶음 → 판정 엔진 입력.
 * 해석하지 못한 메시지 수를 함께 돌려준다 — 카드사 형식이 바뀌면 이 숫자가 먼저 오른다.
 */
export function collectTransactions(messages: readonly AlertMessage[]): {
  transactions: RawTransaction[];
  notBilled: number;
  unrecognized: number;
} {
  const transactions: RawTransaction[] = [];
  let notBilled = 0;
  let unrecognized = 0;

  for (const { body, receivedAt } of messages) {
    const alert = parseCardAlert(body, receivedAt);
    if (!alert) unrecognized++;
    else if (alert.kind === "not-billed") notBilled++;
    else transactions.push(alert.transaction);
  }

  return { transactions, notBilled, unrecognized };
}
