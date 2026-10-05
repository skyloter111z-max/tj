import { describe, expect, it } from "vitest";
import { findService } from "../merchants";

// 예전에 cancelUrl이 한 칸씩 밀려 엉뚱한 서비스 페이지를 가리킨 적이 있다(cursor→midjourney 등).
// 각 서비스의 해지/관리 링크가 자기 도메인을 가리키는지 못박아 재발을 막는다.
const EXPECT_HOST: Record<string, string> = {
  netflix: "netflix.com",
  disneyplus: "disneyplus.com",
  tving: "tving.com",
  wavve: "wavve.com",
  coupangplay: "coupang.com",
  youtubepremium: "youtube.com",
  chatgpt: "chatgpt.com",
  claude: "claude.ai",
  gemini: "one.google.com",
  perplexity: "perplexity.ai",
  cursor: "cursor.com",
  midjourney: "midjourney.com",
  spotify: "spotify.com",
  melon: "melon.com",
  coupangwow: "coupang.com",
  naverplus: "naver.com",
  ms365: "microsoft.com",
};

describe("서비스 해지/관리 링크", () => {
  for (const [id, host] of Object.entries(EXPECT_HOST)) {
    it(`${id}의 cancelUrl은 ${host}를 가리킨다`, () => {
      const url = findService(id)?.cancelUrl;
      expect(url, `${id} cancelUrl 없음`).toBeTruthy();
      expect(new URL(url!).hostname).toContain(host);
    });
  }
});
