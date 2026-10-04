import { describe, expect, it } from "vitest";
import { readImportedAlerts } from "../bridge";
import { extractCardAlerts } from "../import";

// 실제 모바일 내보내기 구조. 카드 알림 사이에 안내·광고·내 메시지가 섞여 있다. 값은 바꿨다.
const EXPORT = `﻿삼성카드 님과 카카오톡 대화\r
저장한 날짜 : 2026년 10월 4일 오후 9:16\r
\r
2026년 8월 12일 오전 3:12\r
2026년 8월 12일 오전 3:12, 삼성카드 : 삼성카드 홍*동님 전자상거래이용\r
08/12 03:12 쿠팡(와우멤 7,890원\r
2026년 8월 20일 오전 9:00, 삼성카드 : [삼성카드] 캔디 소멸 예정 안내\r
\r
회원님, 지난달 적립 캔디가 소멸될 예정이에요.\r
2026년 9월 12일 오전 3:12, 삼성카드 : 삼성카드 홍*동님 전자상거래이용\r
09/12 03:12 쿠팡(와우멤 7,890원\r
2026년 9월 15일 오후 1:02, 홍길동 : 이번달 결제 금액 알려줘\r
2026년 10월 3일 오후 4:35, 삼성카드 : [삼성카드]12,060원\r
승인(온누리상품권 12,060원 사용)\r
*결제대금에 미포함\r
`;

describe("extractCardAlerts", () => {
  it("카드 결제 알림만 남기고 안내·광고·내 메시지는 버린다", () => {
    const result = extractCardAlerts(EXPORT);
    expect(result.alerts).toHaveLength(3);
    expect(result.payments).toBe(2);
    expect(result.span).toEqual({ from: "2026-08-12", to: "2026-10-03" });
    const kept = result.alerts.map((a) => a.body).join("\n");
    expect(kept).not.toContain("캔디");
    expect(kept).not.toContain("이번달 결제 금액");
  });

  it("카드 알림방이 아닌 대화를 공유하면 아무것도 남지 않는다", () => {
    const chat = "친구 님과 카카오톡 대화\n2026년 10월 3일 오후 9:24, 친구 : 내일 몇 시에 봐?\n";
    expect(extractCardAlerts(chat)).toEqual({ alerts: [], payments: 0, span: null });
  });
});

describe("readImportedAlerts", () => {
  it("저장된 알림을 읽고 모양이 틀린 항목은 버린다", () => {
    const json = JSON.stringify([
      { body: "삼성1088승인", receivedAt: "2026-10-03" },
      { body: "x", receivedAt: "어제" },
      { body: 1, receivedAt: "2026-10-03" },
    ]);
    expect(readImportedAlerts({ getImportedAlerts: () => json })).toHaveLength(1);
    expect(readImportedAlerts({})).toEqual([]);
    expect(readImportedAlerts({ getImportedAlerts: () => "깨짐" })).toEqual([]);
  });
});
