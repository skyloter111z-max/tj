#!/usr/bin/env python3
"""PC에서 켜 두는 실시간 감시: 가격이 플랜 레벨에 가까워지거나 닿을 때, 주문이 체결될 때 윈도우 알림과 소리.

사용법 (윈도우 명령 프롬프트, fib_recalc.py·fib_orders.py와 같은 폴더):
  python fib_watch.py              # 30초마다 확인, 레벨 1% 안이면 알림
  python fib_watch.py --near 0.5   # 0.5% 안에 들어올 때 알림
창을 닫거나 Ctrl+C로 끝낸다. PC가 켜져 있고 창이 떠 있는 동안만 동작한다.
UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY가 있으면 미체결 주문이 체결될 때도 알린다 (주문은 넣지 않음).
표준 라이브러리만 사용.
"""
import argparse
import datetime
import os
import sys
import threading
import time

import fib_orders as fo
import fib_recalc as fr

KST = datetime.timezone(datetime.timedelta(hours=9))


def notify(title, msg):
    stamp = datetime.datetime.now(KST).strftime("%H:%M:%S")
    print(f"\n[{stamp}] {title}\n  {msg}", flush=True)
    if sys.platform != "win32":
        return
    import ctypes
    import winsound
    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    # 0x40000(맨 위) | 0x30(경고 아이콘). 창을 닫을 때까지 기다리지 않도록 스레드로 띄운다.
    threading.Thread(target=ctypes.windll.user32.MessageBoxW,
                     args=(0, msg, title, 0x40030), daemon=True).start()


def plan_levels():
    levels = {}
    for coin in fr.COINS:
        weeks, days, price = fr.fetch(coin)
        lv = fr.levels(fr.pivots(weeks, days, price))
        zones = fr.sell_zones(lv, price)
        items = [(f"{n} 매도", fo.snap(coin, z["low"])) for (n, _), z in zip(fr.SELL_STEPS, zones)]
        items += [(f"{i + 1}차 매수 ({r * 100:g}%)", fo.snap(coin, lv["retr"][r]))
                  for i, (r, _) in enumerate(fr.BUY_STEPS)]
        items.append(("매수 중단선 (78.6%)", fo.snap(coin, lv["retr"][0.786])))
        levels[coin] = items
    return levels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--near", type=float, default=1.0, help="레벨 몇 %% 안이면 알릴지 (기본 1)")
    ap.add_argument("--every", type=int, default=30, help="확인 간격 초 (기본 30)")
    args = ap.parse_args()
    watch(args.near, args.every)


def watch(near=1.0, every=30, alert=notify, on_tick=None, stop=None):
    """감시 루프. alert(title, msg)로 알리고, on_tick(가격 dict)으로 현재가를 넘긴다. stop(Event)이 set되면 끝."""
    access, secret = os.environ.get("UPBIT_ACCESS_KEY"), os.environ.get("UPBIT_SECRET_KEY")
    api = fo.Upbit(access, secret) if access and secret else None
    levels, loaded = plan_levels(), time.time()
    for coin, items in levels.items():
        print(f"{coin}: " + ", ".join(f"{n} {p:,.0f}" for n, p in items))
    print(f"\n감시 시작 ({every}초 간격, 레벨 ±{near}% 안이면 알림"
          f"{', 체결 알림 켜짐' if api else ', API 키 없어 체결 알림 꺼짐'}). 끝내려면 Ctrl+C")

    state = {}          # (coin, level name) -> "near" / "hit"
    known = None        # 미체결 주문 uuid -> 주문
    last_price = {}
    while not (stop and stop.is_set()):
        try:
            if time.time() - loaded > 3600:
                levels, loaded = plan_levels(), time.time()
            tickers = fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in fr.COINS))
            for t in tickers:
                coin, price = t["market"][4:], t["trade_price"]
                prev = last_price.get(coin, price)
                last_price[coin] = price
                for name, lvl in levels[coin]:
                    key = (coin, name)
                    dist = (price / lvl - 1) * 100
                    crossed = (prev - lvl) * (price - lvl) <= 0 and prev != price
                    if crossed and state.get(key) != "hit":
                        state[key] = "hit"
                        alert(f"{coin} {name} 도달", f"{coin} {price:,.0f}원이 {name} {lvl:,.0f}원에 닿았습니다.")
                    elif abs(dist) <= near and key not in state:
                        state[key] = "near"
                        alert(f"{coin} {name} 근접", f"{coin} {price:,.0f}원, {name} {lvl:,.0f}원까지 {(lvl / price - 1) * 100:+.2f}%")
                    elif abs(dist) > near * 2 and key in state:
                        del state[key]  # 멀어지면 다음에 다시 알림
            if api:
                current = {}
                for coin in fr.COINS:
                    for o in api.open_orders(f"KRW-{coin}"):
                        current[o["uuid"]] = o
                if known is not None:
                    for uid, o in known.items():
                        if uid in current:
                            continue
                        detail = api.call("GET", "/order", {"uuid": uid})
                        side = "매도" if o["side"] == "ask" else "매수"
                        if detail.get("state") == "done" or float(detail.get("executed_volume", 0)) > 0:
                            alert(f"{o['market']} {side} 체결",
                                   f"{o['market']} {side} {float(o['price']):,.0f}원 × {float(o['volume']):g} 체결. "
                                   "레벨 재계산이 필요할 수 있습니다.")
                known = current
            stamp = datetime.datetime.now(KST).strftime("%H:%M:%S")
            print(f"\r[{stamp}] " + "  ".join(f"{c} {p:,.0f}" for c, p in last_price.items()), end="", flush=True)
            if on_tick:
                on_tick(dict(last_price), levels)
        except Exception as e:  # 네트워크 오류 등은 다음 주기에 다시 시도
            print(f"\n오류 (다시 시도): {e}", flush=True)
        if stop:
            stop.wait(every)
        else:
            time.sleep(every)


if __name__ == "__main__":
    main()
