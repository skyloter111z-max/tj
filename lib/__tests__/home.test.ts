import { describe, expect, it } from "vitest";
import { buildLiveHome, knownKeys, markSeen } from "../home";

const online = (mmdd: string, merchant: string, amount: string, receivedAt: string) => ({
  body: `삼성카드 홍*동님 전자상거래이용\n${mmdd} 03:12 ${merchant} ${amount}원`,
  receivedAt,
});

const WOW = [
  online("08/12", "쿠팡(와우멤", "7,890", "2026-08-12"),
  online("09/12", "쿠팡(와우멤", "7,890", "2026-09-12"),
];

describe("seen map", () => {
  it("처음 본 날로부터 7일이 지나야 이미 아는 구독이 된다", () => {
    const seen = { "svc:coupangwow": "2026-09-28" };
    expect(knownKeys(seen, "2026-10-04").has("svc:coupangwow")).toBe(false);
    expect(knownKeys(seen, "2026-10-05").has("svc:coupangwow")).toBe(true);
  });

  it("이미 본 키의 날짜를 덮어쓰지 않는다", () => {
    expect(markSeen({ a: "2026-01-01" }, ["a", "b"], "2026-10-04")).toEqual({ a: "2026-01-01", b: "2026-10-04" });
  });
});

describe("buildLiveHome", () => {
  it("결제 알림이 쌓이기 전에는 구독 없이 최근 결제만 보인다", () => {
    const home = buildLiveHome([online("10/03", "테스트상점", "12,000", "2026-10-03")], "2026-10-04", {});
    expect(home.subs).toEqual([]);
    expect(home.paymentCount).toBe(1);
    expect(home.recent[0]).toMatchObject({ merchantRaw: "테스트상점", amount: 12000 });
  });

  it("처음 찾은 구독은 새로 찾은 것으로, 일주일 뒤에는 아닌 것으로 본다", () => {
    const first = buildLiveHome(WOW, "2026-09-12", {});
    expect(first.subs.map((s) => [s.service?.id, s.isNew])).toEqual([["coupangwow", true]]);
    expect(first.seen).toEqual({ "svc:coupangwow": "2026-09-12" });

    const later = buildLiveHome(WOW, "2026-09-20", first.seen);
    expect(later.subs[0]!.isNew).toBe(false);
  });

  it("해지한 구독은 목록에서 빼고 개수만 센다", () => {
    const old = [
      online("01/05", "앱구독서비", "9,900", "2026-01-05"),
      online("02/05", "앱구독서비", "9,900", "2026-02-05"),
      online("03/05", "앱구독서비", "9,900", "2026-03-05"),
    ];
    const home = buildLiveHome([...old, ...WOW], "2026-10-04", {});
    expect(home.subs.map((s) => s.service?.id)).toEqual(["coupangwow"]);
    expect(home.ended).toBe(1);
  });

  it("최근 결제는 최신순 5건", () => {
    const many = Array.from({ length: 7 }, (_, i) =>
      online(`09/${String(i + 1).padStart(2, "0")}`, `가게${i + 1}`, "1,000", `2026-09-0${i + 1}`),
    );
    expect(buildLiveHome(many, "2026-10-04", {}).recent.map((t) => t.merchantRaw)).toEqual([
      "가게7", "가게6", "가게5", "가게4", "가게3",
    ]);
  });
});
