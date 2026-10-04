/**
 * 카드 결제 알림 본문 → 판정 엔진 입력(RawTransaction) 변환.
 *
 * 같은 본문이 두 경로로 들어온다:
 *   - 카카오톡 카드사 알림방 "대화 내용 내보내기" 파일 (가입 시 과거 내역)
 *   - 안드로이드 알림 접근으로 받은 알림톡·푸시 (이후 실시간)
 *
 * 알림에는 가맹점명이 마스킹 없이 들어온다. 오픈뱅킹과 달리 `masked` 옵션이 필요 없다.
 * 다만 전자상거래 알림은 가맹점명이 6자 안팎에서 잘린다("네이버파이낸").
 * 본문의 날짜에는 연도가 없으므로("10/03 21:24") 메시지를 받은 날짜에서 연도를 가져온다.
 * 이름("김*진")은 읽지 않는다.
 *
 * 형식은 실제 삼성카드 알림방 내보내기(2023-03 ~ 2026-10, 1,307건)에서 확인했다.
 */

import type { RawTransaction } from "../detector";

/** 어떤 알림에서 왔는가. 자동납부는 통신비처럼 그 자체로 정기결제다 */
export type AlertChannel = "card" | "online" | "autopay";

export type CardAlert =
  | {
      kind: "charge";
      transaction: RawTransaction;
      channel: AlertChannel;
      /** HH:MM. 자동납부 접수 알림에는 시각이 없다 */
      time?: string;
      /** 일시불은 1. 일반 승인 알림에만 있다 */
      installmentMonths?: number;
    }
  /** 승인취소·매입취소. 금액은 양수로 둔다 */
  | { kind: "refund"; transaction: RawTransaction }
  /** 온누리상품권 사용처럼 승인 알림은 왔지만 카드 결제대금에는 들어가지 않는 건 */
  | { kind: "not-billed"; amount: number };

export type AlertMessage = {
  body: string;
  /** 메시지를 받은 날짜 YYYY-MM-DD (내보내기 파일의 메시지 시각, 또는 알림 수신 시각) */
  receivedAt: string;
};

/**
 * 일반 승인·승인취소. 알림톡은 3줄, 알림 미리보기는 한 줄로 합쳐질 수 있어
 * 필드 사이는 `\s+`로 받고 가맹점명만 줄 끝에서 끊는다.
 *
 *   삼성1088승인 김*진          삼성0108취소 김*진
 *   88,000원 일시불             -165,323원 일시불
 *   10/03 21:24 바다이야기      10/18 12:29 주식회사야놀자
 */
const CARD_TX =
  /삼성(\d{4})(승인|취소)(?:\s+[^\s\d]\S*)?\s+(-?[\d,]+)원\s+(일시불|\d{1,2}개월)\s+(\d{2})\/(\d{2})\s+(\d{2}):(\d{2})\s+([^\n]+?)\s*$/m;

/**
 * 전자상거래 승인. 카드 번호가 없다.
 *
 *   삼성카드 김*진님 전자상거래이용
 *   04/29 14:51 주식회사발트 4,800원
 */
const ONLINE = /전자상거래이용\s+(\d{2})\/(\d{2})\s+(\d{2}):(\d{2})\s+(.+?)\s+([\d,]+)원\s*$/m;

/**
 * 자동납부 접수. 날짜는 접수일이다.
 *
 *   [삼성카드]0108
 *   자동결제 04/12접수
 *   SK통신료(904163)
 *   51,730원
 */
const AUTOPAY = /\[삼성카드\](\d{4})\s+자동결제\s+(\d{2})\/(\d{2})접수\s+([^\n]+?)\s+([\d,]+)원/;

/**
 * 매입취소. 결제 며칠 뒤에 온다.
 *
 *   [삼성카드]0108취소
 *   01/19 쿠팡
 *   -77,900원
 */
const LATE_CANCEL = /\[삼성카드\](\d{4})취소\s+(\d{2})\/(\d{2})\s+([^\n]+?)\s+-([\d,]+)원/;

const NOT_BILLED = /결제대금에\s*미포함/;

function toAmount(raw: string): number {
  return Math.abs(Number(raw.replace(/,/g, "")));
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

function tx(
  merchant: string,
  amount: string,
  month: string,
  day: string,
  receivedAt: string,
  cardId: string,
): RawTransaction | null {
  const date = inferDate(Number(month), Number(day), receivedAt);
  if (!date) return null;
  return { merchantRaw: merchant.trim(), amount: toAmount(amount), date, cardId };
}

/** 알림 한 건을 해석한다. 결제 알림이 아니면(챗봇 안내·광고 등) null */
export function parseCardAlert(body: string, receivedAt: string): CardAlert | null {
  let m: RegExpMatchArray | null;

  if (NOT_BILLED.test(body)) {
    m = body.match(/([\d,]+)원/);
    return m ? { kind: "not-billed", amount: toAmount(m[1]!) } : null;
  }

  if ((m = body.match(LATE_CANCEL))) {
    const [, last4, month, day, merchant, amount] = m;
    const t = tx(merchant!, amount!, month!, day!, receivedAt, `samsung-${last4}`);
    return t && { kind: "refund", transaction: t };
  }

  if ((m = body.match(CARD_TX))) {
    const [, last4, type, amount, installment, month, day, hh, mm, merchant] = m;
    const t = tx(merchant!, amount!, month!, day!, receivedAt, `samsung-${last4}`);
    if (!t) return null;
    if (type === "취소") return { kind: "refund", transaction: t };
    return {
      kind: "charge",
      transaction: t,
      channel: "card",
      time: `${hh}:${mm}`,
      installmentMonths: installment === "일시불" ? 1 : Number(installment!.replace("개월", "")),
    };
  }

  if ((m = body.match(ONLINE))) {
    const [, month, day, hh, mm, merchant, amount] = m;
    const t = tx(merchant!, amount!, month!, day!, receivedAt, "samsung");
    return t && { kind: "charge", transaction: t, channel: "online", time: `${hh}:${mm}` };
  }

  if ((m = body.match(AUTOPAY))) {
    const [, last4, month, day, merchant, amount] = m;
    // "SK통신료(904163)" — 괄호 속 번호는 납부자 번호라 가맹점 이름에서 뺀다
    const name = merchant!.replace(/\(\d+\)$/, "");
    const t = tx(name, amount!, month!, day!, receivedAt, `samsung-${last4}`);
    return t && { kind: "charge", transaction: t, channel: "autopay" };
  }

  return null;
}

/**
 * 알림 묶음 → 판정 엔진 입력.
 * 해석하지 못한 메시지 수를 함께 돌려준다 — 카드사 형식이 바뀌면 이 숫자가 먼저 오른다.
 * 환불은 따로 모은다 — 구독 결제는 아니지만 해지 신호다(오픈뱅킹 `parseBillDetail`과 같다).
 */
export function collectTransactions(messages: readonly AlertMessage[]): {
  transactions: RawTransaction[];
  refunds: RawTransaction[];
  notBilled: number;
  unrecognized: number;
} {
  const transactions: RawTransaction[] = [];
  const refunds: RawTransaction[] = [];
  let notBilled = 0;
  let unrecognized = 0;

  for (const { body, receivedAt } of messages) {
    const alert = parseCardAlert(body, receivedAt);
    if (!alert) unrecognized++;
    else if (alert.kind === "not-billed") notBilled++;
    else if (alert.kind === "refund") refunds.push(alert.transaction);
    else transactions.push(alert.transaction);
  }

  return { transactions, refunds, notBilled, unrecognized };
}
