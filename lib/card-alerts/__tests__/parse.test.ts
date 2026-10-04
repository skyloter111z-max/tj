import { describe, expect, it } from "vitest";
import { detectSubscriptions } from "../../detector";
import { collectTransactions, inferDate, parseCardAlert } from "../parse";

// 실제 삼성카드 카카오톡 알림톡 본문 (2026-10-03·04 수신)
const APPROVAL = "삼성1088승인 김*진\n88,000원 일시불\n10/03 21:24 바다이야기";
const VOUCHER = "[삼성카드]12,060원\n승인(온누리상품권 12,060원 사용)\n*결제대금에 미포함";
const VOUCHER_WRAPPED = "[삼성카드]4,500원 승인(온누리상품권\n4,500원 사용)\n*결제대금에 미포함";

describe("parseCardAlert — 삼성카드", () => {
  it("승인 알림에서 카드·금액·날짜·가맹점을 읽는다", () => {
    expect(parseCardAlert(APPROVAL, "2026-10-03")).toEqual({
      kind: "charge",
      transaction: {
        merchantRaw: "바다이야기",
        amount: 88000,
        date: "2026-10-03",
        cardId: "samsung-1088",
      },
      time: "21:24",
      installmentMonths: 1,
    });
  });

  it("알림 미리보기처럼 한 줄로 합쳐진 본문도 읽는다", () => {
    const oneLine = APPROVAL.replace(/\n/g, " ");
    const alert = parseCardAlert(oneLine, "2026-10-03");
    expect(alert?.kind).toBe("charge");
    if (alert?.kind === "charge") expect(alert.transaction.merchantRaw).toBe("바다이야기");
  });

  it("이름을 결과에 남기지 않는다", () => {
    expect(JSON.stringify(parseCardAlert(APPROVAL, "2026-10-03"))).not.toContain("김");
  });

  it("온누리상품권 사용은 결제대금 미포함으로 분리한다", () => {
    expect(parseCardAlert(VOUCHER, "2026-10-03")).toEqual({ kind: "not-billed", amount: 12060 });
    expect(parseCardAlert(VOUCHER_WRAPPED, "2026-10-04")).toEqual({
      kind: "not-billed",
      amount: 4500,
    });
  });

  // 형식 추정: 할부 알림 실제 샘플을 받으면 교체한다
  it("할부 개월 수를 읽는다", () => {
    const alert = parseCardAlert(APPROVAL.replace("일시불", "03개월"), "2026-10-03");
    expect(alert?.kind === "charge" && alert.installmentMonths).toBe(3);
  });

  it("결제 알림이 아닌 메시지는 null", () => {
    expect(parseCardAlert("안녕하세요! 삼성카드 챗봇입니다.", "2026-10-03")).toBeNull();
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
  const netflix = (mmdd: string, receivedAt: string) => ({
    body: `삼성1088승인 김*진\n13,500원 일시불\n${mmdd} 03:12 넷플릭스`,
    receivedAt,
  });

  const messages = [
    netflix("07/15", "2026-07-15"),
    netflix("08/15", "2026-08-15"),
    netflix("09/15", "2026-09-15"),
    { body: APPROVAL, receivedAt: "2026-10-03" },
    { body: VOUCHER, receivedAt: "2026-10-03" },
    { body: "안녕하세요! 삼성카드 챗봇입니다.", receivedAt: "2026-10-03" },
  ];

  it("결제·미포함·해석 불가를 나눠 센다", () => {
    const { transactions, notBilled, unrecognized } = collectTransactions(messages);
    expect(transactions).toHaveLength(4);
    expect(notBilled).toBe(1);
    expect(unrecognized).toBe(1);
  });

  it("카톡 알림 내역만으로 넷플릭스 월구독을 찾는다", () => {
    const { transactions } = collectTransactions(messages);
    const subs = detectSubscriptions(transactions, { today: "2026-10-04" });
    expect(subs).toHaveLength(1);
    expect(subs[0]!.service?.id).toBe("netflix");
    expect(subs[0]!.cycle).toBe("monthly");
    expect(subs[0]!.nextChargeDate).toBe("2026-10-15");
  });
});
