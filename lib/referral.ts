/**
 * 겜스고 어필리에이트 링크 (spec/v5 다음 단계).
 *
 * 구독모아는 파티 거래를 중개하지 않는다. 모집만 하고 결제는 겜스고로 보낸다.
 * 자금을 보유하지 않으므로 전자금융업·PG·분쟁 책임이 발생하지 않는다.
 *
 * 커미션: 첫 구매 10%, 갱신·재구매 5%.
 *
 * 중요: 대가를 받고 추천하므로 공정위 추천·보증 심사지침에 따라
 * 링크가 노출되는 모든 화면에 경제적 이해관계를 고지해야 한다.
 * DISCLOSURE 상수를 UI에서 반드시 함께 렌더링한다.
 */

export const DISCLOSURE =
  "이 링크로 가입하면 구독모아가 겜스고로부터 수수료를 받습니다. 구독모아는 결제·계정·분쟁의 당사자가 아닙니다.";

/** 겜스고 어필리에이트 신청 후 발급받는 전용 프로모션 코드 */
const PROMO_CODE = process.env.NEXT_PUBLIC_GAMSGO_PROMO ?? "";

const BASE_URL = "https://www.gamsgo.com/ko";

export type ReferralTarget = {
  /** 겜스고 상품 슬러그 (예: "chatgpt", "netflix") */
  slug: string;
  /** 클릭 출처 추적용. 어느 파티에서 눌렀는지 */
  partyId?: string;
};

/**
 * 겜스고 상품 페이지로 가는 어필리에이트 링크를 만든다.
 * 프로모션 코드가 설정돼 있지 않으면 일반 링크를 돌려준다 —
 * 코드 없이 링크를 내보내면 커미션이 집계되지 않으므로 운영 시 반드시 설정한다.
 */
export function buildReferralUrl(target: ReferralTarget): string {
  const url = new URL(`${BASE_URL}/details/${target.slug}`);
  if (PROMO_CODE) url.searchParams.set("code", PROMO_CODE);
  if (target.partyId) url.searchParams.set("utm_content", target.partyId);
  url.searchParams.set("utm_source", "submoa");
  url.searchParams.set("utm_medium", "referral");
  return url.toString();
}

export function hasPromoCode(): boolean {
  return PROMO_CODE.length > 0;
}
