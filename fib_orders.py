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

    def place(self, market, side, volume, price):
        return self.call("POST", "/orders", {
            "market": market, "side": side, "ord_type": "limit",
            "volume": f"{volume:.8f}", "price": f"{price:.0f}",
        })


def snap(coin, v):
    step = PRICE_STEP[coin]
    return round(v / step) * step


def plan_orders(coin, holding):
    weeks, days, price = fr.fetch(coin)
    pv = fr.pivots(weeks, days, price)
    lv = fr.levels(pv)
    zones = fr.sell_zones(lv, price)
    orders = []
    for (name, w), z in zip(fr.SELL_STEPS, zones):
        orders.append({"side": "ask", "label": f"{name} 매도 {w * 100:g}%",
                       "price": snap(coin, z["low"]), "volume": int(holding * w * 1e8) / 1e8})
    budget = fr.BUY_BUDGET * fr.BUY_SPLIT[coin]
    for i, (r, w) in enumerate(fr.BUY_STEPS):
        p = snap(coin, lv["retr"][r])
        if p >= price:
            continue
        orders.append({"side": "bid", "label": f"{i + 1}차 매수 {r * 100:g}% ({w * 100:g}%)",
                       "price": p, "volume": int(budget * w / p * 1e8) / 1e8})
    return price, [o for o in orders if o["price"] * o["volume"] >= MIN_ORDER_KRW]


def same(o, plan):
    return (o["side"] == plan["side"] and float(o["price"]) == plan["price"]
            and abs(float(o["remaining_volume"]) - plan["volume"]) <= plan["volume"] * 0.01)


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

    todo = []
    for coin in args.coins:
        market = f"KRW-{coin}"
        price, plan = plan_orders(coin, holdings[coin])
        existing = api.open_orders(market) if api else []
        print(f"\n== {coin} 현재가 {price:,.0f} / 보유 {holdings[coin]:g} ==")
        for p in plan:
            match = next((o for o in existing if same(o, p)), None)
            if match:
                existing.remove(match)
                status = "유지 (이미 걸림)"
            else:
                todo.append(("place", market, p))
                status = "새로 걸기"
            print(f"  {p['label']:<18} {p['price']:>14,.0f} × {p['volume']:<14g}"
                  f" ≈ {p['price'] * p['volume']:>12,.0f}원  [{status}]")
        for o in existing:
            side = "매도" if o["side"] == "ask" else "매수"
            act = "취소" if args.replace else "그대로 둠 (--replace면 취소)"
            print(f"  플랜 밖 {side:<14} {float(o['price']):>14,.0f} × {float(o['remaining_volume']):<14g}  [{act}]")
            if args.replace:
                todo.insert(0, ("cancel", market, o))

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
                print(f"취소  {market} {o['side']} {float(o['price']):,.0f}")
            else:
                r = api.place(market, o["side"], o["volume"], o["price"])
                print(f"주문  {market} {o['label']} {o['price']:,.0f} × {o['volume']:g}  uuid={r.get('uuid')}")
        except RuntimeError as e:
            print(f"실패  {market}: {e}")


if __name__ == "__main__":
    main()
