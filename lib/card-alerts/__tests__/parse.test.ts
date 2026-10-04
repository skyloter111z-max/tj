import { describe, expect, it } from "vitest";
import { detectSubscriptions, totalMonthly } from "../../detector";
import { collectTransactions, inferDate, parseCardAlert } from "../parse";

// 삼성카드 카카오톡 알림톡의 실제 형식. 금액·가맹점·이름은 바꿨다.
const APPROVAL = "삼성1088승인 홍*동\n88,000원 일시불\n10/03 21:24 바다식당";
const APPROVAL_WRAPPED = "[삼성카드]\n삼성1088승인 홍*동 \n88,000원 일시불\n10/03 21:24 바다식당\n\n이번 달 카드 이용내역 자세히 보기";
const ONLINE = "삼성카드 홍*동님 전자상거래이용\n05/06 01:26 테스트상점 42,400원";
const AUTOPAY = "[삼성카드]1088\n자동결제 04/12접수\nKT통신료(123456)\n55,000원";
const CANCEL = "[삼성카드]\n삼성1088취소 홍*동\n-165,000원 일시불\n10/18 12:29 주식회사여행사";
const LATE_CANCEL = "[삼성카드]1088취소\n01/19 테스트상점\n-77,900원\nhttp://q.samsungcard.com/xxxx";
const VOUCHER = "[삼성카드]12,060원\n승인(온누리상품권 12,060원 사용)\n*결제대금에 미포함";
const VOUCHER_WRAPPED = "[삼성카드]4,500원 승인(온누리상품권\n4,500원 사용)\n*결제대금에 미포함";

describe("parseCardAlert — 삼성카드", () => {
  it("일반 승인에서 카드·금액·날짜·가맹점을 읽는다", () => {
    expect(parseCardAlert(APPROVAL, "2026-10-03")).toEqual({
      kind: "charge",
      channel: "card",
      transaction: { merchantRaw: "바다식당", amount: 88000, date: "2026-10-03", cardId: "samsung-1088" },
      time: "21:24",
      installmentMonths: 1,
    });
  });

  it("[삼성카드] 머리말·이름 뒤 공백·안내 문구가 붙어도 같게 읽는다", () => {
    expect(parseCardAlert(APPROVAL_WRAPPED, "2026-10-03")).toEqual(parseCardAlert(APPROVAL, "2026-10-03"));
  });

  it("알림 미리보기처럼 한 줄로 합쳐진 본문도 읽는다", () => {
    const alert = parseCardAlert(APPROVAL.replace(/\n/g, " "), "2026-10-03");
    expect(alert?.kind === "charge" && alert.transaction.merchantRaw).toBe("바다식당");
  });

  it("전자상거래 승인을 읽는다 (카드 번호 없음)", () => {
    expect(parseCardAlert(ONLINE, "2026-05-06")).toEqual({
      kind: "charge",
      channel: "online",
      transaction: { merchantRaw: "테스트상점", amount: 42400, date: "2026-05-06", cardId: "samsung" },
      time: "01:26",
    });
  });

  it("자동납부 접수를 읽고 납부자 번호를 가맹점명에서 뺀다", () => {
    expect(parseCardAlert(AUTOPAY, "2026-04-13")).toEqual({
      kind: "charge",
      channel: "autopay",
      transaction: { merchantRaw: "KT통신료", amount: 55000, date: "2026-04-12", cardId: "samsung-1088" },
    });
  });

  it("승인취소·매입취소는 환불로 나눈다", () => {
    expect(parseCardAlert(CANCEL, "2026-10-18")).toEqual({
      kind: "refund",
      transaction: { merchantRaw: "주식회사여행사", amount: 165000, date: "2026-10-18", cardId: "samsung-1088" },
    });
    expect(parseCardAlert(LATE_CANCEL, "2026-01-22")).toEqual({
      kind: "refund",
      transaction: { merchantRaw: "테스트상점", amount: 77900, date: "2026-01-19", cardId: "samsung-1088" },
    });
  });

  it("이름을 결과에 남기지 않는다", () => {
    for (const body of [APPROVAL, ONLINE, CANCEL]) {
      expect(JSON.stringify(parseCardAlert(body, "2026-10-03"))).not.toContain("홍");
    }
  });

  it("온누리상품권 사용은 결제대금 미포함으로 분리한다", () => {
    expect(parseCardAlert(VOUCHER, "2026-10-03")).toEqual({ kind: "not-billed", amount: 12060 });
    expect(parseCardAlert(VOUCHER_WRAPPED, "2026-10-04")).toEqual({ kind: "not-billed", amount: 4500 });
  });

  // 형식 추정: 실제 할부 알림 샘플은 아직 없다
  it("할부 개월 수를 읽는다", () => {
    const alert = parseCardAlert(APPROVAL.replace("일시불", "03개월"), "2026-10-03");
    expect(alert?.kind === "charge" && alert.installmentMonths).toBe(3);
  });

  it("결제 알림이 아닌 메시지는 null", () => {
    expect(parseCardAlert("[삼성카드] 결제일 안내\n\n홍*동 회원님, 결제일은 14일입니다.", "2026-10-03")).toBeNull();
  });
});

describe("inferDate", () => {
  it("받은 날짜의 연도를 붙인다", () => {
    expect(inferDate(10, 3, "2026-10-03")).toBe("2026-10-03");
  });

  it("12월 결제를 1월에 받으면 전년도다", () => {
    expect(inferDate(12, 31, "2027-01-01")).toBe("2026-12-31");
  });

  it("범위를 벗어난 날짜는 null", () => {
    expect(inferDate(13, 1, "2026-10-03")).toBeNull();
  });
});

describe("collectTransactions → detectSubscriptions", () => {
  const online = (mmdd: string, merchant: string, amount: string, receivedAt: string) => ({
    body: `삼성카드 홍*동님 전자상거래이용\n${mmdd} 03:12 ${merchant} ${amount}원`,
    receivedAt,
  });

  const messages = [
    online("07/12", "쿠팡(와우멤", "7,890", "2026-07-12"),
    online("08/12", "쿠팡(와우멤", "7,890", "2026-08-12"),
    online("09/12", "쿠팡(와우멤", "7,890", "2026-09-12"),
    online("09/13", "쿠팡", "16,900", "2026-09-13"),
    { body: APPROVAL, receivedAt: "2026-10-03" },
    { body: CANCEL, receivedAt: "2026-10-03" },
    { body: VOUCHER, receivedAt: "2026-10-03" },
    { body: "안녕하세요! 삼성카드 챗봇입니다.", receivedAt: "2026-10-03" },
  ];

  it("결제·환불·미포함·해석 불가를 나눠 센다", () => {
    const r = collectTransactions(messages);
    expect(r.transactions).toHaveLength(5);
    expect(r.refunds).toHaveLength(1);
    expect(r.notBilled).toBe(1);
    expect(r.unrecognized).toBe(1);
  });

  it("잘린 가맹점명 \"쿠팡(와우멤\"을 쿠팡 와우로 찾고, 일반 쿠팡 구매와 섞지 않는다", () => {
    const subs = detectSubscriptions(collectTransactions(messages).transactions, { today: "2026-10-04" });
    expect(subs.map((s) => s.service?.id)).toEqual(["coupangwow"]);
    expect(subs[0]!.nextChargeDate).toBe("2026-10-12");
    expect(subs[0]!.active).toBe(true);
  });

  it("몇 년치를 읽으면 해지한 구독이 섞인다 — 끝난 구독은 합계에서 뺀다", () => {
    const ended = [
      online("05/02", "앱구독서비", "9,900", "2025-05-02"),
      online("06/02", "앱구독서비", "9,900", "2025-06-02"),
      online("07/02", "앱구독서비", "9,900", "2025-07-02"),
    ];
    const subs = detectSubscriptions(collectTransactions([...messages, ...ended]).transactions, {
      today: "2026-10-04",
    });
    const app = subs.find((s) => s.displayName === "앱구독서비")!;
    expect(app.active).toBe(false);
    expect(totalMonthly(subs)).toBe(7890);
  });
});
