import { describe, expect, it } from "vitest";
import { findSpikeMonths, parseBillBasic, parseBillDetail, toAmount, toIsoDate } from "../parse";
import { runSignupScan, type ScanDeps } from "../scan";
import type {
  BillBasicResponse,
  BillDetailItem,
  BillDetailResponse,
  Card,
  CardListResponse,
} from "../types";

const TODAY = "2026-10-03";
/** 테스트 카드는 전부 한 카드사(361)에 있다 */
const ISSUERS = ["361"];
const OK = { api_tran_id: "t", api_tran_dtm: "20261003120000", rsp_code: "A0000", rsp_message: "" };

const card = (n: number): Card => ({
  bank_code_std: "361",
  member_bank_code: "023",
  card_id: `card-${n}`,
  card_name: `카드${n}`,
});

/** 명세 형식 그대로의 상세 건 */
const detail = (masked: string, amt: number, date: string): BillDetailItem => ({
  card_value: "abcABC123",
  paid_date: date.replace(/-/g, ""),
  paid_time: "102030",
  paid_amt: String(amt),
  merchant_name_masked: masked,
  credit_fee_amt: "0",
  product_type: "01",
});

describe("응답 변환", () => {
  it("날짜·금액 문자열을 변환한다", () => {
    expect(toIsoDate("20190110")).toBe("2019-01-10");
    expect(toAmount("456,000")).toBe(456000);
    expect(toAmount("-29000")).toBe(-29000);
  });

  it("형식이 아니면 던진다 — 조용히 0으로 만들지 않는다", () => {
    expect(() => toIsoDate("2019-01-10")).toThrow();
    expect(() => toAmount("없음")).toThrow();
  });

  it("음수 건은 구독 거래에서 빼고 환불로 분리한다", () => {
    const res: BillDetailResponse = {
      ...OK,
      user_seq_no: "U1",
      next_page_yn: "N",
      befor_inquiry_trace_info: "",
      bill_detail_cnt: "3",
      bill_list: [
        detail("넷플**", 13500, "2026-09-17"),
        detail("넷플**", -13500, "2026-09-20"),
        detail("커피**", 0, "2026-09-21"),
      ],
    };
    const { transactions, refunds } = parseBillDetail(res);
    expect(transactions).toHaveLength(1);
    expect(refunds).toHaveLength(1);
    expect(refunds[0]!.amount).toBe(13500);
  });

  it("결제순번이 없는 달은 상세 조회가 불가능하므로 버린다", () => {
    const res: BillBasicResponse = {
      ...OK,
      user_seq_no: "U1",
      next_page_yn: "N",
      befor_inquiry_trace_info: "",
      bill_list: [
        { charge_month: "202609", charge_amt: "500000", settlement_seq_no: "001" },
        { charge_month: "202608", charge_amt: "480000" },
      ],
    };
    expect(parseBillBasic(res)).toHaveLength(1);
  });
});

describe("findSpikeMonths — 연 구독 후보 찾기", () => {
  it("중앙값보다 크게 튀는 달을 고른다", () => {
    const totals = [
      { chargeMonth: "202605", amount: 500000, settlementSeqNo: "1" },
      { chargeMonth: "202606", amount: 520000, settlementSeqNo: "1" },
      { chargeMonth: "202607", amount: 490000, settlementSeqNo: "1" },
      { chargeMonth: "202608", amount: 1_200_000, settlementSeqNo: "1" },
    ];
    expect(findSpikeMonths(totals).map((s) => s.chargeMonth)).toEqual(["202608"]);
  });

  it("금액이 고른 달들에서는 아무것도 고르지 않는다", () => {
    const totals = [500000, 510000, 495000, 505000].map((amount, i) => ({
      chargeMonth: `20260${i + 5}`,
      amount,
      settlementSeqNo: "1",
    }));
    expect(findSpikeMonths(totals)).toHaveLength(0);
  });
});

function makeDeps(
  cards: Card[],
  data: Record<string, Record<string, BillDetailItem[]>>,
  opts: { pageSize?: number } = {},
) {
  const pageSize = opts.pageSize ?? 20;
  const deps: ScanDeps = {
    async fetchCardList({ bankCodeStd }): Promise<CardListResponse> {
      return {
        ...OK,
        user_seq_no: "U1",
        next_page_yn: "N",
        befor_inquiry_trace_info: "",
        card_list: cards.filter((c) => c.bank_code_std === bankCodeStd),
      };
    },
    async fetchBillBasic({ card }): Promise<BillBasicResponse> {
      const months = data[card.card_id] ?? {};
      return {
        ...OK,
        user_seq_no: "U1",
        next_page_yn: "N",
        befor_inquiry_trace_info: "",
        bill_list: Object.entries(months).map(([charge_month, items]) => ({
          charge_month,
          charge_amt: String(items.reduce((s, i) => s + Number(i.paid_amt), 0)),
          settlement_seq_no: "001",
        })),
      };
    },
    async fetchBillDetail({ card, chargeMonth, traceInfo }): Promise<BillDetailResponse> {
      const items = data[card.card_id]?.[chargeMonth] ?? [];
      const page = Number(traceInfo ?? "0");
      const slice = items.slice(page * pageSize, (page + 1) * pageSize);
      const hasMore = items.length > (page + 1) * pageSize;
      return {
        ...OK,
        user_seq_no: "U1",
        next_page_yn: hasMore ? "Y" : "N",
        befor_inquiry_trace_info: hasMore ? String(page + 1) : "",
        bill_detail_cnt: String(slice.length),
        bill_list: slice,
      };
    },
  };
  return { deps };
}

function monthlySub(masked: string, amt: number, days: string[]) {
  const out: Record<string, BillDetailItem[]> = {};
  for (const d of days) out[d.slice(0, 7).replace("-", "")] = [detail(masked, amt, d)];
  return out;
}

describe("runSignupScan", () => {
  it("구독을 찾고 호출 수를 보고한다", async () => {
    const data = {
      "card-1": monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
    };
    const { deps } = makeDeps([card(1)], data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS });

    expect(r.subscriptions.map((s) => s.service?.id)).toEqual(["netflix"]);
    expect(r.calls.cardList).toBe(1);
    expect(r.calls.basic).toBe(1);
    expect(r.calls.detail).toBe(3);
    expect(r.calls.total).toBe(5);
  });

  it("선언한 구독을 다 찾으면 남은 카드를 스캔하지 않는다 — 조기 종료", async () => {
    // 구독 카드는 매달 금액이 고르고(CV≈0), 쇼핑 카드는 들쭉날쭉하다.
    // 그래서 구독 카드가 먼저 스캔되고 거기서 끝난다.
    const data: Record<string, Record<string, BillDetailItem[]>> = {
      "card-1": monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
    };
    const cards = [card(1)];
    for (let i = 2; i <= 9; i++) {
      cards.push(card(i));
      data[`card-${i}`] = {
        "202608": [detail("마트**", 12000 + i * 3000, "2026-08-05")],
        "202609": [detail("마트**", 180000 + i * 5000, "2026-09-05")],
        "202610": [detail("마트**", 47000 + i * 1000, "2026-10-05")],
      };
    }
    const { deps } = makeDeps(cards, data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS, declared: new Set(["netflix"]) });

    expect(r.calls.basic).toBe(9); // 1단계는 전 카드
    expect(r.calls.detail).toBe(3); // 2단계는 구독 카드 하나에서 끝
    expect(r.declaredNotFound).toEqual([]);
  });

  it("카드를 가릴 수 없으면 조기 종료가 늦어질 뿐, 전부 스캔하는 것이 최악이다", async () => {
    // 모든 카드가 똑같이 규칙적이면 순서를 정할 근거가 없다 (CV가 전부 0)
    const data: Record<string, Record<string, BillDetailItem[]>> = {};
    const cards: Card[] = [];
    for (let i = 1; i <= 4; i++) {
      cards.push(card(i));
      data[`card-${i}`] = {
        "202608": [detail("마트**", 50000, "2026-08-05")],
        "202609": [detail("마트**", 50000, "2026-09-05")],
        "202610": [detail("마트**", 50000, "2026-10-05")],
      };
    }
    // 마지막 카드에만 구독이 있다
    data["card-4"] = monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]);

    const { deps } = makeDeps(cards, data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS, declared: new Set(["netflix"]) });

    expect(r.declaredNotFound).toEqual([]); // 결국 찾는다
    expect(r.calls.detail).toBeLessThanOrEqual(4 * 3); // 최악이 전수 스캔
  });

  it("선언이 없으면 조기 종료가 없다", async () => {
    const data: Record<string, Record<string, BillDetailItem[]>> = {
      "card-1": monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
      "card-2": monthlySub("스포**", 11990, ["2026-08-05", "2026-09-05", "2026-10-05"]),
    };
    const { deps } = makeDeps([card(1), card(2)], data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS });

    expect(r.calls.detail).toBe(6);
    expect(r.subscriptions).toHaveLength(2);
  });

  it("페이지가 여러 장이면 끝까지 순회한다 (한 페이지 20건)", async () => {
    const many = Array.from({ length: 45 }, (_, i) =>
      detail("마트**", 10000 + i, `2026-10-${String((i % 28) + 1).padStart(2, "0")}`),
    );
    const { deps } = makeDeps([card(1)], { "card-1": { "202610": many } });
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS, recentMonths: 1 });

    expect(r.calls.detail).toBe(3);
  });

  it("maxCalls를 넘으면 중단하고 truncated를 세운다", async () => {
    const data: Record<string, Record<string, BillDetailItem[]>> = {};
    const cards: Card[] = [];
    for (let i = 1; i <= 9; i++) {
      cards.push(card(i));
      data[`card-${i}`] = {
        "202608": [detail("마트**", 50000, "2026-08-05")],
        "202609": [detail("마트**", 50000, "2026-09-05")],
        "202610": [detail("마트**", 50000, "2026-10-05")],
      };
    }
    const { deps } = makeDeps(cards, data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS, maxCalls: 15 });

    expect(r.truncated).toBe(true);
    expect(r.calls.total).toBeLessThanOrEqual(15);
  });

  it("총액이 0인 비활성 카드는 상세 조회하지 않는다", async () => {
    const data: Record<string, Record<string, BillDetailItem[]>> = {
      "card-1": monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
      "card-2": { "202609": [detail("미사용**", 0, "2026-09-01")] },
    };
    const { deps } = makeDeps([card(1), card(2)], data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS });

    expect(r.calls.detail).toBe(3);
  });

  it("선언하지 않았는데 발견된 구독을 분리해 돌려준다", async () => {
    const data: Record<string, Record<string, BillDetailItem[]>> = {
      "card-1": {
        "202608": [detail("넷플**", 13500, "2026-08-17"), detail("스포**", 11990, "2026-08-05")],
        "202609": [detail("넷플**", 13500, "2026-09-17"), detail("스포**", 11990, "2026-09-05")],
        "202610": [detail("넷플**", 13500, "2026-10-17"), detail("스포**", 11990, "2026-10-05")],
      },
    };
    const { deps } = makeDeps([card(1)], data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS, declared: new Set(["netflix"]) });

    expect(r.undeclared.map((s) => s.service?.id)).toEqual(["spotify"]);
  });
});

describe("기획서 §3.1 비용 가정 검증", () => {
  /** 보유 9장, 구독이 1장에 몰린 일반 케이스 */
  it("보유 9장·선언 1개: 총 13회 이내 (기획서 가정 39회보다 낮다)", async () => {
    const data: Record<string, Record<string, BillDetailItem[]>> = {
      "card-1": monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
    };
    const cards = [card(1)];
    for (let i = 2; i <= 9; i++) {
      cards.push(card(i));
      data[`card-${i}`] = {
        "202608": [detail("마트**", 12000 + i * 3000, "2026-08-05")],
        "202609": [detail("마트**", 180000 + i * 5000, "2026-09-05")],
        "202610": [detail("마트**", 47000 + i * 1000, "2026-10-05")],
      };
    }
    const { deps } = makeDeps(cards, data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS, declared: new Set(["netflix"]) });

    // 카드목록 1 + 기본조회 9 + 상세 3 = 13회
    expect(r.calls.total).toBe(13);
    // 건당 10원 기준 130원 → 연 1,200원에서 PG 42원 빼고 986원 남는다
    expect(r.calls.total * 10).toBeLessThan(1200 - 42);
  });

  it("연간권 없는 서비스만 선언하면 3단계가 발동하지 않는다", async () => {
    // 넷플릭스·ChatGPT Plus는 연간 결제가 없다
    const data: Record<string, Record<string, BillDetailItem[]>> = {
      "card-1": {
        ...monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
      },
    };
    // 과거에 총액이 튀는 달을 넣어 둔다 — 3단계가 발동하면 여기를 조회할 것이다
    data["card-1"]!["202602"] = [detail("가전**", 2_000_000, "2026-02-10")];

    const { deps } = makeDeps([card(1)], data);
    const r = await runSignupScan(deps, {
      today: TODAY,
      cardIssuers: ISSUERS,
      declared: new Set(["netflix"]),
    });

    expect(r.calls.detail).toBe(3); // 최근 3개월만. 튀는 달은 보지 않는다
  });

  it("연간권 있는 서비스를 선언하면 튀는 달을 추가로 본다", async () => {
    const data: Record<string, Record<string, BillDetailItem[]>> = {
      "card-1": {
        "202608": [detail("마트**", 50000, "2026-08-05")],
        "202609": [detail("마트**", 52000, "2026-09-05")],
        "202610": [detail("마트**", 48000, "2026-10-05")],
        // 작년 9월에 MS365 연간권
        "202509": [detail("마이**", 155000, "2025-09-20")],
      },
    };
    const { deps } = makeDeps([card(1)], data);
    const r = await runSignupScan(deps, {
      today: TODAY,
      cardIssuers: ISSUERS,
      declared: new Set(["ms365"]),
    });

    expect(r.calls.detail).toBe(4); // 최근 3개월 + 튀는 달 1개
  });
});

describe("카드목록조회는 카드사별 호출이다", () => {
  it("카드사 수만큼 목록을 조회한다", async () => {
    const shinhan: Card = { ...card(1), bank_code_std: "361" };
    const samsung: Card = { ...card(2), bank_code_std: "365" };
    const data = {
      "card-1": monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
      "card-2": monthlySub("스포**", 11990, ["2026-08-05", "2026-09-05", "2026-10-05"]),
    };
    const { deps } = makeDeps([shinhan, samsung], data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ["361", "365"] });

    expect(r.calls.cardList).toBe(2); // 카드사 2곳
    expect(r.subscriptions).toHaveLength(2);
  });

  it("인증하지 않은 카드사의 카드는 보이지 않는다", async () => {
    const shinhan: Card = { ...card(1), bank_code_std: "361" };
    const samsung: Card = { ...card(2), bank_code_std: "365" };
    const data = {
      "card-1": monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
      "card-2": monthlySub("스포**", 11990, ["2026-08-05", "2026-09-05", "2026-10-05"]),
    };
    const { deps } = makeDeps([shinhan, samsung], data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ["361"] });

    expect(r.calls.cardList).toBe(1);
    expect(r.subscriptions.map((s) => s.service?.id)).toEqual(["netflix"]);
  });
});

describe("가족카드는 스캔하지 않는다", () => {
  it("card_member_type이 2면 목록에서 제외한다 — 이용내역이 제공되지 않는다", async () => {
    const own: Card = { ...card(1), card_member_type: "1" };
    const family: Card = { ...card(2), card_member_type: "2" };
    const data = {
      "card-1": monthlySub("넷플**", 13500, ["2026-08-17", "2026-09-17", "2026-10-17"]),
      "card-2": monthlySub("스포**", 11990, ["2026-08-05", "2026-09-05", "2026-10-05"]),
    };
    const { deps } = makeDeps([own, family], data);
    const r = await runSignupScan(deps, { today: TODAY, cardIssuers: ISSUERS });

    // 가족카드는 기본조회·상세조회 모두 건너뛴다
    expect(r.calls.basic).toBe(1);
    expect(r.calls.detail).toBe(3);
    expect(r.subscriptions.map((s) => s.service?.id)).toEqual(["netflix"]);
  });
});
