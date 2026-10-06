/**
 * 서비스 앱 안의 "멤버십 상태" 화면 읽기.
 *
 * 앱 안 화면에는 금액이 안 나오는 경우가 많다. 넷플릭스 '계정'은 요금제 이름과 "어디로 청구되는지"만,
 * 쿠팡플레이 '프로필'은 "WOW! 와우회원"만 보여 준다(실제 화면 2026-10 확인). 대신 요금제·회원 등급은
 * 값이 정해져 있어 금액을 안다. 묶음 구독(네이버플러스 안의 넷플릭스, 쿠팡 와우 안의 쿠팡플레이)은
 * 실제로 돈이 나가는 멤버십과 "그 안에 포함된" 서비스로 나눠 두 번 세지 않는다.
 *
 * 가격(2026-10 확인): 넷플릭스 광고형 스탠다드 7,000 · 스탠다드 13,500 · 프리미엄 17,000.
 * 네이버플러스에 넷플릭스 광고형 포함(추가 0원), 스탠다드 +6,500 · 프리미엄 +10,000. 쿠팡 와우 7,890.
 * 네이버플러스 자체 요금은 넣지 않는다 — 네이버 패밀리로 가족 대표가 내는 경우가 있어, 넷플릭스 화면만으로는
 * 본인이 내는지 알 수 없다(사용자 사례 2026-10).
 */

import { findService } from "../merchants";
import type { StoreSubscription } from "./parse";

type NetflixPlan = "ads" | "standard" | "premium";

const NETFLIX_DIRECT: Record<NetflixPlan, number> = { ads: 7000, standard: 13500, premium: 17000 };
const NETFLIX_VIA_NAVER_EXTRA: Record<NetflixPlan, number> = { ads: 0, standard: 6500, premium: 10000 };
const COUPANG_WOW_MONTHLY = 7890;

function planOf(name: string): NetflixPlan {
  if (/광고형/.test(name)) return "ads";
  if (/프리미엄/.test(name)) return "premium";
  return "standard";
}

/** 지금 쓰는 요금제. "○○ 멤버십" 줄을 먼저 본다 — 업그레이드 권유 문구의 "프리미엄"에 속지 않으려고 */
function netflixPlan(text: string): NetflixPlan | null {
  const line = text.match(/(광고형\s*스탠다드|스탠다드|프리미엄)\s*멤버십/);
  if (line) return planOf(line[1]!);
  if (/광고형\s*스탠다드/.test(text)) return "ads";
  if (/프리미엄/.test(text)) return "premium";
  if (/스탠다드/.test(text)) return "standard";
  return null;
}

/** 쿠팡 와우 회원 표시: 이름 아래 "WOW! 와우회원" 한 줄. "와우회원 전용"·"와우회원이 되어 보세요"는 아니다 */
const WOW_MEMBER_LINE = /^\W*(?:wow\W*)?와우\s*회원\s*$/i;

function monthly(id: string, amount: number, billedVia?: string): StoreSubscription | null {
  const service = findService(id);
  if (!service) return null;
  return { service, amount, cycle: "monthly", ...(billedVia ? { billedVia } : {}) };
}

/**
 * 그 서비스 앱 안에서 읽은 화면(targetId를 안다)에서 구독을 알아낸다. 모르는 화면이면 빈 배열.
 */
export function inferFromAppScreen(text: string, targetId: string): StoreSubscription[] {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const out: (StoreSubscription | null)[] = [];

  if (targetId === "netflix") {
    // 계정의 멤버십 정보 화면이어야 한다(요금제 고르는 화면엔 "멤버십 시작/정보"가 없다)
    if (!/멤버십\s*(시작|정보)/.test(text)) return [];
    const plan = netflixPlan(text);
    if (!plan) return [];
    if (/네이버\s*(플러스\s*)?멤버십/.test(text)) {
      // 이 화면이 증명하는 건 "넷플릭스가 네이버 멤버십으로 청구된다"까지다. 네이버플러스를 누가 내는지
      // (본인인지, 네이버 패밀리로 가족 대표가 내는지)·월간인지 연간인지는 알 수 없으므로 네이버플러스
      // 금액은 넣지 않는다. 본인이 내면 카드 결제로 잡힐 때 실제 금액이 들어간다.
      out.push(monthly("netflix", NETFLIX_VIA_NAVER_EXTRA[plan], "naverplus"));
    } else {
      out.push(monthly("netflix", NETFLIX_DIRECT[plan]));
    }
  } else if (targetId === "coupangplay" || targetId === "coupangwow") {
    if (lines.some((l) => WOW_MEMBER_LINE.test(l)) || /와우\s*멤버십\s*(이용\s*중|회원)/.test(text)) {
      out.push(monthly("coupangwow", COUPANG_WOW_MONTHLY), monthly("coupangplay", 0, "coupangwow"));
    }
  }

  return out.filter((s): s is StoreSubscription => s !== null);
}
