import { describe, expect, it } from "vitest";
import { detectSubscriptions } from "../../detector";
import { exportSpan, parseKakaoExport } from "../kakao-export";
import { collectTransactions } from "../parse";

// 모바일 내보내기의 실제 구조(BOM·CRLF·시각 붙은 구분선). 내용은 바꿨다.
const MOBILE = `\uFEFF삼성카드 님과 카카오톡 대화\r
저장한 날짜 : 2026년 10월 4일 오후 9:16\r
\r
\r
2026년 7월 15일 오전 3:12\r
2026년 7월 15일 오전 3:12, 삼성카드 : [삼성카드]
삼성1088승인 김*진
13,500원 일시불
07/15 03:12 넷플릭스

이번 달 카드 이용내역 자세히 보기
2026년 8월 15일 오전 3:12
2026년 8월 15일 오전 3:12, 삼성카드 : 삼성1088승인 김*진
13,500원 일시불
08/15 03:12 넷플릭스
2026년 9월 15일 오전 3:12
2026년 9월 15일 오전 3:12, 삼성카드 : 삼성1088승인 김*진
13,500원 일시불
09/15 03:12 넷플릭스
2026년 9월 15일 오후 1:02, 홍길동 : 이번달 결제 금액 알려줘
2026년 10월 3일 오후 4:35
2026년 10월 3일 오후 4:35, 삼성카드 : [삼성카드]12,060원
승인(온누리상품권 12,060원 사용)
*결제대금에 미포함
2026년 10월 3일 오후 9:24, 삼성카드 : 삼성1088승인 김*진
88,000원 일시불
10/03 21:24 바다이야기`;

// 형식 추정: 구형·PC 내보내기는 실제 파일로 확인하지 않았다
const LEGACY = `2026. 10. 3. 오후 9:24, 삼성카드 : 삼성1088승인 김*진
88,000원 일시불
10/03 21:24 바다이야기`;

const PC = `--------------- 2026년 10월 3일 토요일 ---------------
[삼성카드] [오후 9:24] 삼성1088승인 김*진
88,000원 일시불
10/03 21:24 바다이야기`;

const EXPECTED_BODY = "삼성1088승인 김*진\n88,000원 일시불\n10/03 21:24 바다이야기";

describe("parseKakaoExport", () => {
  it("모바일·구형·PC 형식에서 같은 메시지를 꺼낸다", () => {
    for (const text of [LEGACY, PC]) {
      expect(parseKakaoExport(text)).toEqual([{ receivedAt: "2026-10-03", body: EXPECTED_BODY }]);
    }
    expect(parseKakaoExport(MOBILE).at(-1)).toEqual({ receivedAt: "2026-10-03", body: EXPECTED_BODY });
  });

  it("시각이 붙은 구분선을 앞 메시지에 이어 붙이지 않는다", () => {
    const first = parseKakaoExport(MOBILE)[0]!;
    expect(first.body).not.toMatch(/2026년 8월/);
    expect(first.body.endsWith("자세히 보기")).toBe(true);
  });

  it("머리말과 날짜 구분선을 메시지에 섞지 않는다", () => {
    const bodies = parseKakaoExport(MOBILE).map((m) => m.body).join("\n");
    expect(bodies).not.toContain("저장한 날짜");
    expect(bodies).not.toContain("카카오톡 대화");
  });

  it("기간을 계산한다", () => {
    expect(exportSpan(parseKakaoExport(MOBILE))).toEqual({ from: "2026-07-15", to: "2026-10-03" });
  });
});

describe("내보내기 파일 → 구독 탐지", () => {
  it("알림톡 머리말·버튼 문구·사용자 메시지가 섞여도 넷플릭스를 찾는다", () => {
    const { transactions, notBilled, unrecognized } = collectTransactions(parseKakaoExport(MOBILE));
    expect(transactions).toHaveLength(4);
    expect(notBilled).toBe(1);
    expect(unrecognized).toBe(1); // 사용자가 챗봇에 보낸 메시지

    const subs = detectSubscriptions(transactions, { today: "2026-10-04" });
    expect(subs.map((s) => s.service?.id)).toEqual(["netflix"]);
    expect(subs[0]!.nextChargeDate).toBe("2026-10-15");
  });
});
