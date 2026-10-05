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
