#!/usr/bin/env python3
"""fib-plan.md 3번 공식으로 업비트 캔들 기준 레벨/매도표/매수표를 다시 계산한다.

사용법:
  python3 fib_recalc.py                 # 업비트 API에서 캔들·현재가를 불러와 계산
  python3 fib_recalc.py --input x.json  # 기준점을 직접 넣어 계산 (오프라인 확인용)
  python3 fib_recalc.py --dump raw.json # 불러온 캔들 원본도 저장

--input JSON 형식: {"BTC": {"H_w": .., "L": .., "H_d": .., "price": ..}, ...}
결과는 마크다운으로 stdout에 출력한다. fib-plan.md 2·4~7번 표를 이걸로 바꾸면 된다.
표준 라이브러리만 사용.
"""
import argparse
import json
import time
import urllib.request

COINS = ["BTC", "ETH", "XRP"]
API = "https://api.upbit.com/v1"

# fib-plan.md 1번 표 (수량). 새 캡처를 받으면 여기를 갱신.
HOLDINGS = {"BTC": 0.04532286, "ETH": 1.5967, "XRP": 1128.37215229}
CASH_KRW = 18_223_184
BUY_BUDGET = 9_100_000
BUY_SPLIT = {"BTC": 0.4, "ETH": 0.4, "XRP": 0.2}

WEEKLY_R = [0.786, 0.618, 0.5, 0.382, 0.236]
EXT_E = [2.618, 2.0, 1.618, 1.272]
RETR_R = [0.382, 0.5, 0.618, 0.786]
SELL_STEPS = [("1차", 0.2), ("2차", 0.3), ("3차", 0.2)]
BUY_STEPS = [(0.382, 0.2), (0.5, 0.3), (0.618, 0.5)]
ZONE_TOL = 0.06  # 주봉 레벨과 일봉 확장이 6% 안이면 겹침 구간으로 본다


def get(path):
    req = urllib.request.Request(f"{API}{path}", headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch(coin):
    market = f"KRW-{coin}"
    weeks = get(f"/candles/weeks?market={market}&count=200")
    time.sleep(0.2)
    days = get(f"/candles/days?market={market}&count=200")
    time.sleep(0.2)
    price = get(f"/ticker?markets={market}")[0]["trade_price"]
    return weeks, days, price


def pivots(weeks, days, price):
    """H_w: 2025년 주봉 최고 꼬리, L: 2026년 최저 꼬리, H_d: L 이후 일봉 최고 꼬리."""
    w25 = [c for c in weeks if c["candle_date_time_kst"].startswith("2025")]
    hw = max(w25, key=lambda c: c["high_price"])
    w26 = [c for c in weeks if c["candle_date_time_kst"] >= "2026"]
    d26 = [c for c in days if c["candle_date_time_kst"] >= "2026"]
    lw = min(w26, key=lambda c: c["low_price"])
    # 주봉 저점 주간 안의 정확한 날짜는 일봉에서 찾는다(200일 범위 안일 때)
    ld = min(d26, key=lambda c: c["low_price"]) if d26 else None
    if ld and ld["low_price"] <= lw["low_price"]:
        low, low_date = ld["low_price"], ld["candle_date_time_kst"][:10]
    else:
        low, low_date = lw["low_price"], lw["candle_date_time_kst"][:10] + " 주"
    after = [c for c in days if c["candle_date_time_kst"][:10] >= low_date[:10]]
    hd = max(after, key=lambda c: c["high_price"]) if after else None
    h_d = max(hd["high_price"], price) if hd else price
    h_d_date = hd["candle_date_time_kst"][:10] if hd and hd["high_price"] >= price else "현재가"
    return {
        "H_w": hw["high_price"], "H_w_date": hw["candle_date_time_kst"][:10] + " 주",
        "L": low, "L_date": low_date,
        "H_d": h_d, "H_d_date": h_d_date,
        "price": price,
    }


def levels(p):
    hw, low, hd = p["H_w"], p["L"], p["H_d"]
    return {
        "weekly": {r: low + (hw - low) * r for r in WEEKLY_R},
        "ext": {e: low + (hd - low) * e for e in EXT_E},
        "retr": {r: hd - (hd - low) * r for r in RETR_R},
    }


def sell_zones(lv, price):
    """현재가 위의 주봉 레벨마다 가장 가까운 (아직 안 쓴) 일봉 확장을 짝지음.
    둘이 ZONE_TOL 안이면 겹침 구간, 지정가는 구간 아래쪽 가격."""
    used, zones = set(), []
    for r in sorted(lv["weekly"]):
        w = lv["weekly"][r]
        if w <= price:
            continue
        cands = [(abs(x - w) / w, e, x) for e, x in lv["ext"].items() if e not in used]
        if not cands:
            break
        d, e, x = min(cands)
        if d <= ZONE_TOL:
            used.add(e)
            zones.append({"weekly_r": r, "ext_e": e, "low": min(w, x), "high": max(w, x)})
    # 겹침 구간이 3개가 안 되면 남은 주봉 레벨 단독으로 채운다
    for r in sorted(lv["weekly"]):
        if len(zones) >= 3:
            break
        w = lv["weekly"][r]
        if w > price and all(z["weekly_r"] != r for z in zones):
            zones.append({"weekly_r": r, "ext_e": None, "low": w, "high": w})
    zones.sort(key=lambda z: z["low"])
    return zones


def rnd(coin, v):
    if coin == "XRP":
        return f"{v:,.0f}"
    step = 10_000 if coin == "BTC" else 1_000
    return f"{round(v / step) * step:,.0f}"


def report(data):
    out = []
    out.append("## 2. 기준점 (업비트 캔들)\n")
    out.append("| | 주봉 고점 (H_w) | 저점 (L) | 일봉 고점 (H_d) | 현재가 |")
    out.append("|---|---|---|---|---|")
    for c in COINS:
        p = data[c]
        out.append(
            f"| {c} | {p['H_w']:,.0f} ({p.get('H_w_date', '-')}) | {p['L']:,.0f} ({p.get('L_date', '-')}) "
            f"| {p['H_d']:,.0f} ({p.get('H_d_date', '-')}) | {p['price']:,.0f} |"
        )

    lv = {c: levels(data[c]) for c in COINS}

    out.append("\n## 4. 주봉 레벨\n")
    out.append("| 레벨 | " + " | ".join(COINS) + " |")
    out.append("|---|" + "---|" * len(COINS))
    for r in WEEKLY_R:
        out.append(f"| {r * 100:g}% | " + " | ".join(rnd(c, lv[c]["weekly"][r]) for c in COINS) + " |")

    out.append("\n## 5. 일봉 레벨\n")
    out.append("| 레벨 | " + " | ".join(COINS) + " |")
    out.append("|---|" + "---|" * len(COINS))
    for e in EXT_E:
        out.append(f"| {e:g} 확장 | " + " | ".join(rnd(c, lv[c]["ext"][e]) for c in COINS) + " |")
    for r in RETR_R:
        name = f"{r * 100:g}% 되돌림" + (" (매수 중단선)" if r == 0.786 else "")
        out.append(f"| {name} | " + " | ".join(rnd(c, lv[c]["retr"][r]) for c in COINS) + " |")

    zones = {c: sell_zones(lv[c], data[c]["price"]) for c in COINS}
    out.append("\n## 6. 매도표 (겹침 구간 아래쪽 가격에 지정가)\n")
    out.append("| | 비중 | " + " | ".join(COINS) + " |")
    out.append("|---|---|" + "---|" * len(COINS))
    for i, (name, w) in enumerate(SELL_STEPS):
        cells = []
        for c in COINS:
            z = zones[c]
            if i < len(z):
                cells.append(f"{HOLDINGS[c] * w:.5g} @ {rnd(c, z[i]['low'])}")
            else:
                cells.append("겹침 구간 없음")
        out.append(f"| {name} | {w * 100:g}% | " + " | ".join(cells) + " |")
    out.append("| 나머지 | 30% | " + " | ".join("추적 손절" for _ in COINS) + " |")
    out.append("\n겹침 구간 근거:")
    for c in COINS:
        desc = ", ".join(
            f"주봉 {z['weekly_r'] * 100:g}% ↔ {z['ext_e']:g} 확장 ({rnd(c, z['low'])}~{rnd(c, z['high'])})"
            if z["ext_e"] else f"주봉 {z['weekly_r'] * 100:g}% 단독 ({rnd(c, z['low'])})"
            for z in zones[c][:3]
        )
        out.append(f"- {c}: {desc or '없음'}")

    out.append(f"\n## 7. 매수표 (현금 {CASH_KRW:,} 중 {BUY_BUDGET:,} 사용)\n")
    out.append("| 되돌림 | 배분 | " + " | ".join(f"{c} ({BUY_BUDGET * BUY_SPLIT[c] / 1e4:,.0f}만)" for c in COINS) + " |")
    out.append("|---|---|" + "---|" * len(COINS))
    for r, w in BUY_STEPS:
        cells = [f"{BUY_BUDGET * BUY_SPLIT[c] * w / 1e4:,.0f}만 @ {rnd(c, lv[c]['retr'][r])}" for c in COINS]
        out.append(f"| {r * 100:g}% | {w * 100:g}% | " + " | ".join(cells) + " |")

    out.append("\n## 1. 평가액 (현재가 × 1번 표 수량)\n")
    out.append("| 자산 | 수량 | 현재가 | 평가액(KRW) | 비중 |")
    out.append("|---|---|---|---|---|")
    vals = {c: HOLDINGS[c] * data[c]["price"] for c in COINS}
    total = CASH_KRW + sum(vals.values())
    out.append(f"| KRW | – | – | {CASH_KRW:,} | {CASH_KRW / total * 100:.1f}% |")
    for c in COINS:
        out.append(f"| {c} | {HOLDINGS[c]:g} | {data[c]['price']:,.0f} | {vals[c]:,.0f} | {vals[c] / total * 100:.1f}% |")
    out.append(f"| 합계 | | | {total:,.0f} | |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="기준점 JSON (API 대신 사용)")
    ap.add_argument("--dump", help="불러온 캔들 원본을 저장할 경로")
    args = ap.parse_args()

    if args.input:
        with open(args.input) as f:
            data = json.load(f)
    else:
        data, raw = {}, {}
        for c in COINS:
            weeks, days, price = fetch(c)
            raw[c] = {"weeks": weeks, "days": days, "price": price}
            data[c] = pivots(weeks, days, price)
        if args.dump:
            with open(args.dump, "w") as f:
                json.dump(raw, f, ensure_ascii=False)
    print(report(data))


if __name__ == "__main__":
    main()
