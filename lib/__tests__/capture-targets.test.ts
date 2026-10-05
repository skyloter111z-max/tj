import { describe, expect, it } from "vitest";
import { buildQueue, captureGroups, captureUrlOf, defaultSelection } from "../capture-targets";
import { findService } from "../merchants";

describe("capture-targets", () => {
  it("OTT와 AI를 모두 대상으로 올린다", () => {
    const labels = captureGroups().map((g) => g.label);
    expect(labels).toContain("영상 (OTT)");
    expect(labels).toContain("AI");
    const aiKeys = captureGroups().find((g) => g.label === "AI")!.targets.map((t) => t.key);
    expect(aiKeys).toEqual(expect.arrayContaining(["chatgpt", "claude", "gemini", "perplexity"]));
  });

  it("기본 선택은 애플 스토어만 빼고 전부", () => {
    const def = defaultSelection();
    expect(def.has("store-play")).toBe(true);
    expect(def.has("store-apple")).toBe(false);
    expect(def.has("netflix")).toBe(true);
    expect(def.has("chatgpt")).toBe(true);
  });

  it("같은 주소는 큐에서 한 번만 연다 (유튜브 프리미엄 = 구글플레이)", () => {
    const yt = captureUrlOf(findService("youtubepremium")!);
    expect(yt).toContain("play.google.com");
    const q = buildQueue(new Set(["store-play", "youtubepremium"]));
    expect(q.filter((t) => t.url.includes("play.google.com"))).toHaveLength(1);
  });

  it("고른 것만 큐에 담는다", () => {
    const q = buildQueue(new Set(["netflix", "claude"]));
    expect(q.map((t) => t.id).sort()).toEqual(["claude", "netflix"]);
    expect(q.every((t) => t.url.startsWith("https://"))).toBe(true);
  });
});
