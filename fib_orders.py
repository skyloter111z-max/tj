#!/usr/bin/env python3
"""fib-plan.md의 피보나치 매수·매도 지정가 주문을 업비트에 걸어 둔다.

사용법 (윈도우 명령 프롬프트):
  python fib_orders.py                    # 모의 실행: 걸 주문만 보여 주고 아무것도 안 함
  python fib_orders.py --live             # 실제 주문 (확인 질문에 yes 입력해야 진행)
  python fib_orders.py --live --replace   # 플랜과 다른 기존 주문(BTC·ETH·XRP)을 취소하고 다시 건다
  python fib_orders.py --coins XRP        # 특정 코인만

동작:
  - 가격은 fib_recalc.py와 같은 방식으로 업비트 캔들에서 계산한다.
  - 매도 수량은 업비트 잔고(주문에 묶인 수량 포함) × 20/30/20%. 스테이킹 물량은 잔고에 없어서 빠진다.
  - 매수 금액은 BUY_BUDGET × 코인 비중 × 20/30/50%. 현재가보다 높은 매수 레벨은 건너뛴다.
  - 가격과 수량이 같은 주문이 이미 있으면 그대로 두고 새로 걸지 않는다.
  - 1차가 체결된 뒤에 다시 실행하면 수량 기준이 바뀌므로, 체결 후에는 레벨을 먼저 다시 계산할 것.

API 키 (본인 PC에만 저장, 출금 권한은 끄고 허용 IP 등록):
  setx UPBIT_ACCESS_KEY "발급받은_access_key"
  setx UPBIT_SECRET_KEY "발급받은_secret_key"
  (setx 뒤에는 명령 프롬프트를 새로 열어야 적용됨)
키가 없으면 fib_recalc.py의 HOLDINGS로 모의 실행만 한다.
표준 라이브러리만 사용.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import fib_recalc as fr

MIN_ORDER_KRW = 5_000
PRICE_STEP = {"BTC": 10_000, "ETH": 1_000, "XRP": 1}


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt_token(access, secret, params=None):
    payload = {"access_key": access, "nonce": str(uuid.uuid4())}
    if params:
        q = urllib.parse.urlencode(params).encode()
        payload["query_hash"] = hashlib.sha512(q).hexdigest()
        payload["query_hash_alg"] = "SHA512"
    head = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64url(json.dumps(payload).encode())
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64url(sig)}"


class Upbit:
    def __init__(self, access, secret):
        self.access, self.secret = access, secret

    def call(self, method, path, params=None):
        url = f"{fr.API}{path}"
        data = None
        headers = {"Authorization": f"Bearer {jwt_token(self.access, self.secret, params)}",
                   "accept": "application/json"}
        if params and method in ("GET", "DELETE"):
            url += "?" + urllib.parse.urlencode(params)
        elif params:
            data = json.dumps(params).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} 실패 {e.code}: {e.read().decode(errors='replace')}")
        finally:
            time.sleep(0.15)

    def holdings(self):
        acc = {a["currency"]: a for a in self.call("GET", "/accounts")}
        out = {c: float(acc[c]["balance"]) + float(acc[c]["locked"]) if c in acc else 0.0 for c in fr.COINS}
        krw = float(acc["KRW"]["balance"]) if "KRW" in acc else 0.0
        return out, krw

    def open_orders(self, market):
        return self.call("GET", "/orders/open", {"market": market, "state": "wait", "limit": 100})

    def cancel(self, order_uuid):
        return self.call("DELETE", "/order", {"uuid": order_uuid})

    def market_buy(self, market, krw):
        """시장가 매수 (금액 지정)."""
        return self.call("POST", "/orders", {"market": market, "side": "bid", "ord_type": "price", "price": f"{krw:.0f}"})

    def market_sell(self, market, volume):
        """시장가 매도 (수량 지정)."""
        return self.call("POST", "/orders", {"market": market, "side": "ask", "ord_type": "market",
                                             "volume": f"{int(volume * 1e8) / 1e8:.8f}"})  # 내림: 잔고 초과 방지

    def filled(self, order_uuid, tries=6):
        """체결 결과 (수량, 체결금액, 수수료). 시장가는 보통 1~2초 안에 끝난다."""
        for _ in range(tries):
            time.sleep(0.7)
            o = self.call("GET", "/order", {"uuid": order_uuid})
            if o.get("state") in ("done", "cancel") and o.get("trades"):
                funds = sum(float(t["funds"]) for t in o["trades"])
                return float(o["executed_volume"]), funds, float(o.get("paid_fee") or 0)
        raise RuntimeError(f"주문 {order_uuid} 체결 확인 실패")

    def place(self, market, side, volume, price):
        return self.call("POST", "/orders", {
            "market": market, "side": side, "ord_type": "limit",
            "volume": f"{volume:.8f}", "price": f"{price:.0f}",
        })


def snap(coin, v):
    step = PRICE_STEP[coin]
    return round(v / step) * step


def compute_levels(coin):
    """지금 캔들로 계산한 플랜 레벨. sells: 1·2·3차 매도가, buys: 1·2·3차 매수가, stop: 매수 중단선."""
    weeks, days, price = fr.fetch(coin)
    lv = fr.levels(fr.pivots(weeks, days, price))
    zones = fr.sell_zones(lv, price)
    return {"price": price,
            "sells": [snap(coin, z["low"]) for z in zones[:len(fr.SELL_STEPS)]],
            "buys": [snap(coin, lv["retr"][r]) for r, _ in fr.BUY_STEPS],
            "stop": snap(coin, lv["retr"][0.786])}


def plan_orders(coin, holding, sell_done=0, buy_done=0, levels=None):
    """플랜 주문 목록. sell_done/buy_done: 이미 체결된 단계 수 (그 단계는 건너뛴다).
    levels를 주면 그 고정 레벨을 쓰고, 없으면 지금 캔들로 계산한다.
    매도 수량 기준은 체결 전 보유량으로 되돌려 계산한다 (예: 1차 20% 체결 뒤엔 현재 보유 / 0.8)."""
    lv = levels or compute_levels(coin)
    price = lv.get("price") or fr.get(f"/ticker?markets=KRW-{coin}")[0]["trade_price"]
    done_w = sum(w for _, w in fr.SELL_STEPS[:sell_done])
    base = holding / (1 - done_w) if done_w < 1 else 0
    orders = []
    for i, (name, w) in enumerate(fr.SELL_STEPS):
        if i < sell_done or i >= len(lv["sells"]):
            continue
        orders.append({"side": "ask", "step": i, "label": f"{name} 매도 {w * 100:g}%",
                       "price": lv["sells"][i], "volume": int(base * w * 1e8) / 1e8})
    budget = fr.BUY_BUDGET * fr.BUY_SPLIT[coin]
    for i, (r, w) in enumerate(fr.BUY_STEPS):
        p = lv["buys"][i]
        if i < buy_done or p >= price:
            continue
        orders.append({"side": "bid", "step": i, "label": f"{i + 1}차 매수 {r * 100:g}% ({w * 100:g}%)",
                       "price": p, "volume": int(budget * w / p * 1e8) / 1e8})
    return price, [o for o in orders if o["price"] * o["volume"] >= MIN_ORDER_KRW]


def same(o, plan, tol=0.03):
    return (o["side"] == plan["side"] and float(o["price"]) == plan["price"]
            and abs(float(o["remaining_volume"]) - plan["volume"]) <= plan["volume"] * tol)


def diff(api, holdings, coins=None, replace=True, progress=None, tol=0.03, levels=None):
    """플랜과 실제 미체결 주문 비교.
    rows: (상태, 코인, 주문) 목록. 상태는 유지/주문/취소/플랜 밖.
    todo: 실행할 (cancel|place, market, 주문) 목록, 취소가 먼저 온다."""
    rows, todo = [], []
    for coin in coins or fr.COINS:
        market = f"KRW-{coin}"
        pg = (progress or {}).get(coin, {})
        lv = dict(levels[coin], price=None) if levels and coin in levels else None
        price, plan = plan_orders(coin, holdings[coin], pg.get("sell_done", 0), pg.get("buy_done", 0), lv)
        existing = list(api.open_orders(market)) if api else []
        for p in plan:
            match = next((o for o in existing if same(o, p, tol)), None)
            if match:
                existing.remove(match)
                rows.append(("유지", coin, p))
            else:
                todo.append(("place", market, p))
                rows.append(("주문", coin, p))
        for o in existing:
            item = {"side": o["side"], "label": "플랜 밖", "price": float(o["price"]),
                    "volume": float(o["remaining_volume"]), "uuid": o["uuid"]}
            rows.append(("취소" if replace else "플랜 밖", coin, item))
            if replace:
                todo.insert(0, ("cancel", market, item))
    return rows, todo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="실제로 주문한다")
    ap.add_argument("--replace", action="store_true", help="플랜과 다른 기존 주문을 취소한다")
    ap.add_argument("--coins", nargs="+", default=fr.COINS, choices=fr.COINS)
    args = ap.parse_args()

    access, secret = os.environ.get("UPBIT_ACCESS_KEY"), os.environ.get("UPBIT_SECRET_KEY")
    api = Upbit(access, secret) if access and secret else None
    if args.live and not api:
        raise SystemExit("UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 환경변수가 없습니다.")
    if api:
        holdings, krw = api.holdings()
        print(f"업비트 잔고 기준 (주문 가능 KRW {krw:,.0f})")
    else:
        holdings = fr.HOLDINGS
        print("API 키 없음: fib_recalc.py의 HOLDINGS로 모의 실행")

    rows, todo = diff(api, holdings, args.coins, args.replace)
    status = {"유지": "유지 (이미 걸림)", "주문": "새로 걸기", "취소": "취소", "플랜 밖": "그대로 둠 (--replace면 취소)"}
    last = None
    for st, coin, p in rows:
        if coin != last:
            print(f"\n== {coin} / 보유 {holdings[coin]:g} ==")
            last = coin
        side = "매도" if p["side"] == "ask" else "매수"
        label = p["label"] if p["label"] != "플랜 밖" else f"플랜 밖 {side}"
        print(f"  {label:<18} {p['price']:>14,.0f} × {p['volume']:<14g}"
              f" ≈ {p['price'] * p['volume']:>12,.0f}원  [{status[st]}]")

    if not args.live:
        print("\n모의 실행이라 아무 주문도 넣지 않았습니다. 실제로 걸려면 --live")
        return
    if not todo:
        print("\n할 일이 없습니다.")
        return
    if input(f"\n위 내용대로 {len(todo)}건 실행할까요? (yes 입력) ").strip().lower() != "yes":
        print("취소했습니다.")
        return
    for kind, market, o in todo:
        try:
            if kind == "cancel":
                api.cancel(o["uuid"])
                print(f"취소  {market} {o['side']} {o['price']:,.0f}")
            else:
                r = api.place(market, o["side"], o["volume"], o["price"])
                print(f"주문  {market} {o['label']} {o['price']:,.0f} × {o['volume']:g}  uuid={r.get('uuid')}")
        except RuntimeError as e:
            print(f"실패  {market}: {e}")


if __name__ == "__main__":
    main()
