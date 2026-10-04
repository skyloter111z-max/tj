import { describe, expect, it } from "vitest";
import { detectSubscriptions } from "../../detector";
import { exportSpan, parseKakaoExport } from "../kakao-export";
import { collectTransactions } from "../parse";

// 형식 추정: 실제 내보내기 파일 앞부분을 받으면 이 픽스처를 교체한다
const IOS = `삼성카드 님과 카카오톡 대화
저장한 날짜 : 2026. 10. 4. 오전 10:50

2026년 7월 15일 수요일
2026. 7. 15. 오전 3:12, 삼성카드 : 알림톡 도착
삼성1088승인 김*진
13,500원 일시불
07/15 03:12 넷플릭스
이번달 이용내역 조회
2026년 8월 15일 토요일
2026. 8. 15. 오전 3:12, 삼성카드 : 삼성1088승인 김*진
13,500원 일시불
08/15 03:12 넷플릭스
2026년 9월 15일 화요일
2026. 9. 15. 오전 3:12, 삼성카드 : 삼성1088승인 김*진
13,500원 일시불
09/15 03:12 넷플릭스
2026. 9. 15. 오후 1:02, 김지진 : 이번달 결제 금액 알려줘
2026년 10월 3일 토요일
2026. 10. 3. 오후 4:35, 삼성카드 : [삼성카드]12,060원
승인(온누리상품권 12,060원 사용)
*결제대금에 미포함
2026. 10. 3. 오후 9:24, 삼성카드 : 삼성1088승인 김*진
88,000원 일시불
10/03 21:24 바다이야기`;

const ANDROID = `2026년 10월 3일 오후 9:24, 삼성카드 : 삼성1088승인 김*진
88,000원 일시불
10/03 21:24 바다이야기`;

const PC = `--------------- 2026년 10월 3일 토요일 ---------------
[삼성카드] [오후 9:24] 삼성1088승인 김*진
88,000원 일시불
10/03 21:24 바다이야기`;

const EXPECTED_BODY = "삼성1088승인 김*진\n88,000원 일시불\n10/03 21:24 바다이야기";

describe("parseKakaoExport", () => {
  it("iOS·Android·PC 형식에서 같은 메시지를 꺼낸다", () => {
    for (const text of [ANDROID, PC]) {
      expect(parseKakaoExport(text)).toEqual([{ receivedAt: "2026-10-03", body: EXPECTED_BODY }]);
    }
    expect(parseKakaoExport(IOS).at(-1)).toEqual({ receivedAt: "2026-10-03", body: EXPECTED_BODY });
  });

  it("머리말과 날짜 구분선을 메시지에 섞지 않는다", () => {
    const bodies = parseKakaoExport(IOS).map((m) => m.body).join("\n");
    expect(bodies).not.toContain("저장한 날짜");
    expect(bodies).not.toContain("요일");
  });

  it("기간을 계산한다", () => {
    expect(exportSpan(parseKakaoExport(IOS))).toEqual({ from: "2026-07-15", to: "2026-10-03" });
  });
});

describe("내보내기 파일 → 구독 탐지", () => {
  it("알림톡 머리말·버튼 문구·사용자 메시지가 섞여도 넷플릭스를 찾는다", () => {
    const { transactions, notBilled, unrecognized } = collectTransactions(parseKakaoExport(IOS));
    expect(transactions).toHaveLength(4);
    expect(notBilled).toBe(1);
    expect(unrecognized).toBe(1); // 사용자가 챗봇에 보낸 메시지

    const subs = detectSubscriptions(transactions, { today: "2026-10-04" });
    expect(subs.map((s) => s.service?.id)).toEqual(["netflix"]);
    expect(subs[0]!.nextChargeDate).toBe("2026-10-15");
  });
});
