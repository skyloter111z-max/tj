import { describe, expect, it } from "vitest";
import { ingestPendingOcr } from "../bridge";

function fakeBridge(pending: string) {
  let saved = "[]";
  return {
    takePendingOcrText: () => pending,
    getStoreSubs: () => saved,
    saveStoreSubs: (json: string) => {
      saved = json;
    },
    get saved() {
      return saved;
    },
  };
}

const PLAY = `정기 결제
활성
YouTube
YouTube Premium
다음 결제: 2026. 11. 1.에 ₩14,900 결제 예정`;

// 넷플릭스 계정 페이지: 이름과 금액이 멀리 떨어져 있어 일반 해석은 놓친다 → id 힌트로 잡는다
const NETFLIX = `넷플릭스
멤버십 및 결제
프리미엄
다음 결제일: 2026년 11월 3일
₩17,000`;

describe("ingestPendingOcr: 여러 화면 읽기", () => {
  it("화면마다 id로 해석해 여러 OTT를 한 번에 잡는다", () => {
    const b = fakeBridge(
      JSON.stringify([
        { id: "", text: PLAY },
        { id: "netflix", text: NETFLIX },
      ]),
    );
    const out = ingestPendingOcr(b);
    expect(out.readText).toBe(true);
    expect(out.found.map((s) => [s.service.id, s.amount]).sort()).toEqual([
      ["netflix", 17000],
      ["youtubepremium", 14900],
    ]);
  });

  it("빈 큐면 읽은 글자 없음", () => {
    const out = ingestPendingOcr(fakeBridge("[]"));
    expect(out).toEqual({ found: [], readText: false });
  });

  it("글자는 읽었지만 아는 구독이 없으면 readText만 true", () => {
    const out = ingestPendingOcr(fakeBridge(JSON.stringify([{ id: "netflix", text: "로그인\n이메일\n비밀번호" }])));
    expect(out).toEqual({ found: [], readText: true });
  });

  it("앱 안에서 읽은 화면(trusted)은 이름 없이도 그 서비스로 잡는다", () => {
    const tving = "이용권\n광고형 스탠다드\n월 5,500원\n다음 결제일 2026.11.03";
    const out = ingestPendingOcr(fakeBridge(JSON.stringify([{ id: "tving", text: tving, trusted: true }])));
    expect(out.found.map((s) => [s.service.id, s.amount])).toEqual([["tving", 5500]]);
  });

  it("옛 형식(글자 하나)도 일반 해석으로 받는다", () => {
    const out = ingestPendingOcr(fakeBridge(PLAY));
    expect(out.found.map((s) => s.service.id)).toEqual(["youtubepremium"]);
  });
});
