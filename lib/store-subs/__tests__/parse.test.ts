import { describe, expect, it } from "vitest";
import { parseStoreScreenshot } from "../parse";

// 구글플레이 "구독" 화면을 OCR한 모양 (한국어). 실제 화면엔 안내·버튼 문구가 섞인다.
const PLAY = `구독
YouTube Premium
₩14,900/월 · 다음 결제일: 2026. 10. 15.
Netflix
프리미엄
₩17,000/월
Microsoft 365 Personal
₩11,900/월
정기 결제 관리
더보기`;

// 애플 설정 → 구독 화면 OCR 모양
const APPSTORE = `구독
Netflix
프리미엄
₩17,000 · 월
Disney+
₩9,900 · 월
만료일`;

describe("parseStoreScreenshot", () => {
  it("구글플레이 화면에서 서비스·금액·주기를 뽑는다", () => {
    const subs = parseStoreScreenshot(PLAY);
    expect(subs.map((s) => [s.service.id, s.amount, s.cycle])).toEqual([
      ["youtubepremium", 14900, "monthly"],
      ["netflix", 17000, "monthly"],
      ["ms365", 11900, "monthly"],
    ]);
  });

  it("애플 화면에서도 뽑는다", () => {
    const subs = parseStoreScreenshot(APPSTORE);
    expect(subs.map((s) => s.service.id).sort()).toEqual(["disneyplus", "netflix"]);
  });

  it("가격이 없는 이름 줄은 구독으로 치지 않는다", () => {
    expect(parseStoreScreenshot("Netflix\n시청 계속하기\n로그아웃")).toEqual([]);
  });

  it("해외통화 표시는 건너뛴다", () => {
    expect(parseStoreScreenshot("Spotify\nUS$9.99/month")).toEqual([]);
  });

  it("아는 서비스가 없으면 빈 목록", () => {
    expect(parseStoreScreenshot("배달의민족\n₩12,000\n주문하기")).toEqual([]);
  });

  it("연간 구독을 구분한다", () => {
    const subs = parseStoreScreenshot("Microsoft 365\n₩89,000/년");
    expect(subs[0]).toMatchObject({ cycle: "yearly", amount: 89000 });
  });

  it("같은 서비스가 두 번 나와도 한 번만", () => {
    const subs = parseStoreScreenshot("Netflix\n₩17,000/월\nNetflix\n₩17,000/월");
    expect(subs).toHaveLength(1);
  });
});
