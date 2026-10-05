import { describe, expect, it } from "vitest";
import { parseStoreScreenshot } from "../parse";

// 실제 구글플레이 "정기 결제" 화면을 OCR한 글자 (사용자 스크린샷 그대로)
const REAL_PLAY = `정기 결제
Google에서는 개발자가 정기 결제 서비스를 제공할 수 있도록 사용자를
개인적으로 식별하지 않는 정기 결제 데이터를 개발자와 공유할 수 있습니다.
정기 결제에 관해 자세히 알아보기
내가 보유한 용량:
1
Google Play를 통해 이용 중인 정기 결제 수
정기 결제 시 Play 포인트 적립
가입하기
활성
YouTube
YouTube Premium
다음 결제: 2026. 11. 1.에 ₩14,900 결제 예정
요금제에 포함된 항목
광고 없는 동영상
오프라인 저장 중
백그라운드 재생`;

describe("실제 구글플레이 정기결제 화면", () => {
  it("YouTube Premium 14,900원을 뽑는다", () => {
    const subs = parseStoreScreenshot(REAL_PLAY);
    expect(subs.map((s) => [s.service.id, s.amount, s.cycle])).toEqual([
      ["youtubepremium", 14900, "monthly"],
    ]);
  });
});
