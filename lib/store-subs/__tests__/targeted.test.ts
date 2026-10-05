import { describe, expect, it } from "vitest";
import { parseStoreScreenshotFor } from "../parse";

// 넷플릭스 계정 페이지: 이름(로고 옆 글자)과 금액이 멀리 떨어져 있다.
// 일반 파서는 "이름 + 가까운 가격"만 보므로 놓치지만, 타깃 파서는 결제 맥락에 붙은 금액을 잡는다.
const NETFLIX_ACCOUNT = `넷플릭스
멤버십 및 결제
회원정보
프리미엄
다음 결제일: 2026년 11월 3일
₩17,000`;

// 요금제 선택 화면: 금액이 여럿이고 "결제 예정" 같은 맥락이 없다 → 섣불리 찍지 않는다
const PLAN_PICKER = `넷플릭스
광고형 스탠다드 ₩5,500
스탠다드 ₩13,500
프리미엄 ₩17,000`;

describe("특정 OTT 화면 타깃 읽기", () => {
  it("이름과 금액이 떨어져 있어도 결제액을 잡는다", () => {
    const sub = parseStoreScreenshotFor(NETFLIX_ACCOUNT, "netflix");
    expect(sub).not.toBeNull();
    expect([sub!.service.id, sub!.amount, sub!.cycle]).toEqual(["netflix", 17000, "monthly"]);
  });

  it("연간 표시가 있으면 연간으로 본다", () => {
    const sub = parseStoreScreenshotFor("디즈니+\n다음 결제 ₩99,000 / 년", "disneyplus");
    expect([sub!.service.id, sub!.amount, sub!.cycle]).toEqual(["disneyplus", 99000, "yearly"]);
  });

  it("금액이 여럿인데 결제 맥락이 없으면 찍지 않는다", () => {
    expect(parseStoreScreenshotFor(PLAN_PICKER, "netflix")).toBeNull();
  });

  it("그 서비스가 화면에 안 보이면 null", () => {
    expect(parseStoreScreenshotFor("다음 결제 ₩17,000", "netflix")).toBeNull();
  });
});

// 티빙 앱 안 '마이 > 이용권' 화면: 앱 안이라 "티빙"이라는 글자가 화면에 없다
const TVING_IN_APP = `이용권
광고형 스탠다드
월 5,500원
다음 결제일 2026.11.03
결제 수단 삼성카드`;

describe("서비스 앱 안에서 읽은 화면(trusted)", () => {
  it("이름이 화면에 없어도 그 서비스로 읽는다", () => {
    const sub = parseStoreScreenshotFor(TVING_IN_APP, "tving", { trusted: true });
    expect([sub?.service.id, sub?.amount, sub?.cycle]).toEqual(["tving", 5500, "monthly"]);
  });

  it("trusted가 아니면 이름 없는 화면은 여전히 거른다", () => {
    expect(parseStoreScreenshotFor(TVING_IN_APP, "tving")).toBeNull();
  });

  it("trusted라도 금액이 애매하면(결제 맥락 없이 여럿) 찍지 않는다", () => {
    const picker = "이용권 구매\n광고형 스탠다드 5,500원\n스탠다드 13,900원";
    expect(parseStoreScreenshotFor(picker, "tving", { trusted: true })).toBeNull();
  });
});
