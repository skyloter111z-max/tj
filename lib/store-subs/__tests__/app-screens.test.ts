import { describe, expect, it } from "vitest";
import { viaLabel } from "../../billing";
import { inferFromAppScreen } from "../app-screens";
import { ingestPendingOcr, readStoreSubs } from "../bridge";
import { parseStoreScreenshotFor } from "../parse";

// 실제 넷플릭스 앱 '계정' 화면(2026-10, 사용자 캡처). 개인정보(이메일·전화번호) 줄은 뺐다.
const NETFLIX_ACCOUNT_VIA_NAVER = `NETFLIX
계정
결제 정보를 업데이트하거나, 멤버십 또는 다른 계정 관리 기능을
변경하려면 netflix.com의 '계정' 메뉴를 이용하세요.
멤버십 정보
멤버십 시작: 2025년 6월
광고형 스탠다드 멤버십
네이버 멤버십 서비스 추가 옵션을 통해 청구
결제 내역 확인
보안
비밀번호
이메일
휴대폰
디바이스
액세스 및 디바이스`;

// 실제 쿠팡플레이 앱 '프로필' 화면(2026-10, 사용자 캡처). 이름은 바꿨다.
const COUPANG_PLAY_PROFILE = `홍길동 >
WOW! 와우회원
premium 구독하고 광고 없이 시청하세요 >
쿠플클럽
상위 53%
2,330점 >
스포츠패스클럽
지금 가입하면 받는 혜택 >
모든 문제 적중하면 쿠팡캐시와 주식이!
도전하기
혜택 알림 받기
시청기록 >
개별구매 >
WOW! 와우회원 전용
트로이
2026년 8월 4일 만료됨
내 구독내역 >`;

const ids = (subs: { service: { id: string }; amount: number; billedVia?: string }[]) =>
  subs.map((s) => [s.service.id, s.amount, s.billedVia ?? null]);

describe("넷플릭스 앱 계정 화면", () => {
  it("네이버플러스로 청구되는 광고형은 넷플릭스 0원(포함) + 네이버플러스 4,900원", () => {
    expect(ids(inferFromAppScreen(NETFLIX_ACCOUNT_VIA_NAVER, "netflix"))).toEqual([
      ["netflix", 0, "naverplus"],
      ["naverplus", 4900, null],
    ]);
  });

  it("네이버로 스탠다드를 쓰면 업그레이드 차액 6,500원이 네이버플러스로 청구", () => {
    const text = NETFLIX_ACCOUNT_VIA_NAVER.replace("광고형 스탠다드 멤버십", "스탠다드 멤버십");
    expect(ids(inferFromAppScreen(text, "netflix"))[0]).toEqual(["netflix", 6500, "naverplus"]);
  });

  it("넷플릭스에 직접 내면 요금제 가격 그대로", () => {
    const direct = NETFLIX_ACCOUNT_VIA_NAVER.replace("네이버 멤버십 서비스 추가 옵션을 통해 청구", "다음 결제일: 2026년 11월 3일");
    expect(ids(inferFromAppScreen(direct, "netflix"))).toEqual([["netflix", 7000, null]]);
    const premium = direct.replace("광고형 스탠다드 멤버십", "프리미엄 멤버십");
    expect(ids(inferFromAppScreen(premium, "netflix"))).toEqual([["netflix", 17000, null]]);
  });

  it("업그레이드 권유의 '프리미엄'에 속지 않는다", () => {
    const text = `${NETFLIX_ACCOUNT_VIA_NAVER}\n프리미엄으로 업그레이드하고 4K로 시청하세요`;
    expect(ids(inferFromAppScreen(text, "netflix"))[0]).toEqual(["netflix", 0, "naverplus"]);
  });

  it("요금제 고르는 화면(멤버십 정보 없음)은 읽지 않는다", () => {
    const picker = "요금제를 선택하세요\n광고형 스탠다드\n스탠다드\n프리미엄\n다음";
    expect(inferFromAppScreen(picker, "netflix")).toEqual([]);
  });
});

describe("쿠팡플레이 앱 프로필 화면", () => {
  it("와우회원이면 쿠팡 와우 7,890원 + 쿠팡플레이는 와우에 포함", () => {
    expect(ids(inferFromAppScreen(COUPANG_PLAY_PROFILE, "coupangplay"))).toEqual([
      ["coupangwow", 7890, null],
      ["coupangplay", 0, "coupangwow"],
    ]);
  });

  it("'와우회원 전용'·'와우회원이 되어 보세요'만 있으면 회원으로 보지 않는다", () => {
    const nonMember = "홍길동 >\n와우회원이 되어 보세요\n개별구매 >\nWOW! 와우회원 전용";
    expect(inferFromAppScreen(nonMember, "coupangplay")).toEqual([]);
  });

  it("'2,330점'(포인트)을 금액으로 읽지 않는다", () => {
    // 일반 해석은 화면에 금액이 하나뿐이면 그걸 쓰는데, 포인트는 돈이 아니다
    expect(parseStoreScreenshotFor(COUPANG_PLAY_PROFILE, "coupangplay", { trusted: true })).toBeNull();
  });
});

describe("앱 안 화면을 홈까지", () => {
  function fakeBridge(pending: string) {
    let saved = "[]";
    return {
      takePendingOcrText: () => pending,
      getStoreSubs: () => saved,
      saveStoreSubs: (json: string) => {
        saved = json;
      },
    };
  }

  it("넷플릭스·쿠팡플레이 화면을 읽어 묶음 관계까지 저장하고 다시 읽는다", () => {
    const b = fakeBridge(
      JSON.stringify([
        { id: "netflix", text: NETFLIX_ACCOUNT_VIA_NAVER, trusted: true },
        { id: "coupangplay", text: COUPANG_PLAY_PROFILE, trusted: true },
      ]),
    );
    const out = ingestPendingOcr(b);
    expect(ids(out.found).sort()).toEqual([
      ["coupangplay", 0, "coupangwow"],
      ["coupangwow", 7890, null],
      ["naverplus", 4900, null],
      ["netflix", 0, "naverplus"],
    ]);
    // 저장 → 복원해도 "포함" 관계가 남는다
    expect(ids(readStoreSubs(b)).sort()).toEqual(ids(out.found).sort());
  });

  it("표시 문구", () => {
    expect(viaLabel({ amount: 0, billedVia: "naverplus" })).toBe("네이버플러스에 포함");
    expect(viaLabel({ amount: 6500, billedVia: "naverplus" })).toBe("네이버플러스로 청구");
    expect(viaLabel({ amount: 7890 })).toBeNull();
  });
});
