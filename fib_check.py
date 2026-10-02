#!/usr/bin/env python3
"""플랜 레벨 기준 현황 체크: 4시간봉·1시간봉·1분봉 흐름, 레벨까지 거리, 체결 가능성, 규칙 조건.

사용법:
  python3 fib_check.py                 # 최근 1시간 동안 레벨 터치 여부 포함
  python3 fib_check.py --since-hours 4
표준 라이브러리만 사용 (API 키 불필요, 공개 시세만 조회).
"""
import argparse
import datetime
import time

import fib_recalc as fr

KST = datetime.timezone(datetime.timedelta(hours=9))


def candles(unit, coin, count):
    path = f"/candles/minutes/{unit}" if isinstance(unit, int) else f"/candles/{unit}"
    time.sleep(0.12)
    return list(reversed(fr.get(f"{path}?market=KRW-{coin}&count={count}")))  # 오래된 것 → 최신


def rsi(closes, n=14):
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def ma(closes, n):
    return sum(closes[-n:]) / min(n, len(closes))


def trend(cs, n=20):
    closes = [c["trade_price"] for c in cs]
    m = ma(closes, n)
    slope = (ma(closes, n) - ma(closes[:-3], n)) / m * 100
    side = "위" if closes[-1] > m else "아래"
    return f"MA{n} {side}({(closes[-1] / m - 1) * 100:+.1f}%, 기울기 {slope:+.2f}%) RSI {rsi(closes):.0f}"


def pct(a, b):
    return (a / b - 1) * 100


def check(coin, since_hours):
    weeks, days, price = fr.fetch(coin)
    pv = fr.pivots(weeks, days, price)
    lv = fr.levels(pv)
    zones = fr.sell_zones(lv, price)
    step = {"BTC": 10_000, "ETH": 1_000, "XRP": 1}[coin]
    snap = lambda v: round(v / step) * step  # noqa: E731  fib_orders.py와 같은 호가 단위
    sells = [(f"{n} 매도", snap(z["low"])) for (n, _), z in zip(fr.SELL_STEPS, zones)]
    buys = [(f"{i + 1}차 매수", snap(lv["retr"][r])) for i, (r, _) in enumerate(fr.BUY_STEPS)]
    stop = snap(lv["retr"][0.786])

    h4 = candles(240, coin, 60)
    h1 = candles(60, coin, 60)
    m1 = candles(1, coin, 60)
    recent = candles(60, coin, max(1, since_hours))
    hi = max(c["high_price"] for c in recent)
    lo = min(c["low_price"] for c in recent)

    m1_chg = pct(m1[-1]["trade_price"], m1[0]["opening_price"])
    vol = [c["candle_acc_trade_price"] for c in m1]
    spike = vol[-5:] and sum(vol[-5:]) / 5 / (sum(vol) / len(vol) or 1)
    day24 = pct(price, h1[-24]["opening_price"])

    out = [f"■ {coin} {price:,.0f} (24h {day24:+.1f}%, 최근 {since_hours}h 범위 {lo:,.0f}~{hi:,.0f})"]
    out.append(f"  4h: {trend(h4)} | 1h: {trend(h1)} | 1m: 60분 {m1_chg:+.2f}%, 최근5분 거래대금 평균대비 x{spike:.1f}")
    ns = min(sells, key=lambda s: s[1] - price if s[1] > price else 1e18) if sells else None
    nb = max(buys, key=lambda b: b[1] if b[1] < price else -1)
    out.append(f"  가까운 매도: {ns[0]} {ns[1]:,.0f} ({pct(ns[1], price):+.1f}%)" if ns else "  매도 레벨 없음")
    out.append(f"  가까운 매수: {nb[0]} {nb[1]:,.0f} ({pct(nb[1], price):+.1f}%)  | 매수 중단선 {stop:,.0f}")
    touched = [f"{n} {p:,.0f}" for n, p in sells if hi >= p] + [f"{n} {p:,.0f}" for n, p in buys if lo <= p]
    if touched:
        out.append(f"  ⚠ 최근 {since_hours}h 안에 닿음 → 체결 가능: {', '.join(touched)}")
    last_day = days[1] if days[0]["candle_date_time_kst"][:10] == datetime.datetime.now(KST).strftime("%Y-%m-%d") else days[0]
    if last_day["trade_price"] < stop:
        out.append(f"  ⚠ 직전 일봉 종가 {last_day['trade_price']:,.0f} < 매수 중단선")
    if weeks[1]["trade_price"] < pv["L"]:
        out.append(f"  ⚠ 직전 주봉 종가 {weeks[1]['trade_price']:,.0f} < 저점 L {pv['L']:,.0f} → 1/3 축소")
    if pv["H_d_date"] == "현재가":
        out.append(f"  ℹ 현재가가 일봉 고점(H_d) 위 → 주봉 종가가 넘으면 월요일에 재계산")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-hours", type=int, default=1)
    args = ap.parse_args()
    print(datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"))
    for coin in fr.COINS:
        print(check(coin, args.since_hours))


if __name__ == "__main__":
    main()
