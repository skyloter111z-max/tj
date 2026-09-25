"""실전 오류 상황 재현 테스트 (가짜 거래소). 실행: python tests/risk_test.py  — 모두 PASS여야 한다."""
import os, sys, queue, tempfile, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fibtrader_core as core, fib_orders as fo, fib_recalc as fr

class Ex:
    """가짜 업비트: 시장가 즉시 체결, identifier 중복 거부, 장애 주입."""
    def __init__(s):
        s.price = {"ADA": 340.0}; s.bal = {"KRW": 1_000_000.0, "ADA": 0.0}; s.orders = {}; s.by_ident = {}
        s.fail_next = None; s.n = 0; s.posts = 0; s.open = {}
    def _fill(s, market, side, amount):
        c = market[4:]; p = s.price[c]
        if side == "bid":
            if s.bal["KRW"] < amount: raise RuntimeError("POST /orders 실패 400: insufficient_funds_bid")
            fee = amount * 0.0005; vol = (amount - fee) / p
            s.bal["KRW"] -= amount; s.bal[c] += vol; funds = amount - fee
        else:
            if s.bal[c] + 1e-12 < amount: raise RuntimeError("POST /orders 실패 400: insufficient_funds_ask")
            vol = amount; funds = vol * p; fee = funds * 0.0005
            s.bal[c] -= vol; s.bal["KRW"] += funds - fee
        return vol, funds, fee
    def _post(s, market, side, amount, identifier):
        s.posts += 1
        if identifier in s.by_ident: raise RuntimeError("POST /orders 실패 400: duplicate identifier")
        mode, s.fail_next = s.fail_next, None
        if mode == "reject": raise RuntimeError("POST /orders 실패 400: insufficient_funds_bid")
        if mode == "lost_before": raise fo.UnknownResult("timeout (주문 안 들어감)")
        vol, funds, fee = s._fill(market, side, amount)
        s.n += 1; u = f"u{s.n}"
        o = {"uuid": u, "identifier": identifier, "state": "done", "executed_volume": str(vol), "paid_fee": str(fee),
             "trades": [{"funds": str(funds)}], "side": side, "market": market}
        s.orders[u] = o; s.by_ident[identifier] = o
        if mode == "lost_after": raise fo.UnknownResult("timeout (주문은 들어감)")
        return {"uuid": u}
    def market_buy(s, m, krw, identifier=None): return s._post(m, "bid", krw, identifier)
    def market_sell(s, m, v, identifier=None): return s._post(m, "ask", v, identifier)
    def get_order(s, uuid=None, identifier=None): return s.by_ident.get(identifier) if identifier else s.orders.get(uuid)
    def filled(s, order_uuid=None, identifier=None, tries=6):
        if s.fail_next == "slow_confirm":
            s.fail_next = None; raise fo.UnknownResult("체결 확인 실패")
        return fo.Upbit.order_result(s.get_order(order_uuid, identifier))
    def call(s, meth, path, params=None):
        if path == "/accounts": return [{"currency": k, "balance": str(v), "locked": "0"} for k, v in s.bal.items()]
        raise RuntimeError("unsupported")
    def open_orders(s, market): return [o for o in s.open.values() if o["market"] == market]
    def holdings(s): return {c: s.bal.get(c, 0.0) for c in fr.COINS}, s.bal["KRW"]
    def cancel(s, u): s.open.pop(u)
    def place(s, m, side, v, p, identifier=None):
        s.n += 1; u = f"L{s.n}"; s.open[u] = {"uuid": u, "market": m, "side": side, "price": str(p), "volume": str(v), "remaining_volume": str(v)}
        return {"uuid": u}

def mk(**grid):
    d = tempfile.mkdtemp(); core.CONFIG_PATH = os.path.join(d, "c.json")
    cfg = core.load_config(); cfg["grid"].update(dict(simulate=False, coins=["ADA"], unit_krw=5000, profit_krw=250, max_krw=150000), **grid)
    e = core.Engine(cfg, core.DB(os.path.join(d, "t.db")), queue.Queue()); ex = Ex(); e.api = ex
    return e, ex, cfg
def step(e, ex, p, skip_rate=True):
    ex.price["ADA"] = p; e.prices["ADA"] = p
    if skip_rate: e.grid_state("ADA")["last_trade_ts"] = 0
    try: e.grid_step("ADA", p)
    except fo.UnknownResult as x: e.alert("fail", "unknown", str(x))
    except Exception as x: e.grid_state("ADA")["pause_until"] = time.time() + 600; e.alert("fail", "err", str(x))
def alerts(e):
    out = []
    while not e.events.empty():
        x = e.events.get()
        if x[0] == "alert": out.append(x[1])
    return out
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m)

# 1 정상 사이클 2번 (실전 경로): 장부 수익 = 거래소 실제 현금 증가
e, ex, cfg = mk()
for p in [340, 323, 306, 340, 355, 330, 313, 330, 345]: step(e, ex, p)
st = e.grid_state("ADA")
real = ex.bal["KRW"] + ex.bal["ADA"] * ex.price["ADA"] * (1 - 0.0005) - 1_000_000
ok(st["cycles"] == 2 and abs(st["profit_total"] - real) < 1 and abs(st["qty"] - ex.bal["ADA"]) < 1e-9,
   f"1 2사이클: 장부 수익 {st['profit_total']:,.0f}원 = 실제 {real:,.0f}원, 장부 수량 = 거래소 수량")

# 2 결과 불명확 + 실제로는 체결됨 → 중복 없이 사후 반영
e, ex, cfg = mk()
ex.fail_next = "lost_after"; step(e, ex, 340)
ok(e.grid_state("ADA").get("pending") and ex.posts == 1, "2a 불명확 → pending 기록")
step(e, ex, 340); step(e, ex, 340)
st = e.grid_state("ADA")
ok(ex.posts == 1 and st["buys"] == 1 and abs(st["qty"] - ex.bal["ADA"]) < 1e-9, f"2b 재확인 후 반영, 추가 주문 없음 (posts={ex.posts}, 장부 {st['qty']:.4f} = 거래소 {ex.bal['ADA']:.4f})")

# 3 결과 불명확 + 실제로 안 들어감 → 1분 뒤 없는 것으로 처리 후 정상 진행
e, ex, cfg = mk()
ex.fail_next = "lost_before"; step(e, ex, 340)
step(e, ex, 340); ok(e.grid_state("ADA").get("pending") and ex.posts == 1, "3a 1분 안에는 재주문 안 함")
e.grid_state("ADA")["pending"]["ts"] -= 61; step(e, ex, 340); step(e, ex, 340)
ok(ex.posts == 2 and e.grid_state("ADA")["buys"] == 1, f"3b 없음 확인 후 새로 1회 매수 (posts={ex.posts})")

# 4 거절(현금 부족) → pending 없음, 10분 정지
e, ex, cfg = mk(); ex.fail_next = "reject"; step(e, ex, 340)
st = e.grid_state("ADA")
ok(not st.get("pending") and st.get("pause_until", 0) > time.time() + 500, "4 거절 → 장부 변화 없음 + 10분 정지")
step(e, ex, 340); ok(ex.posts == 1, "4b 정지 중 재시도 안 함")

# 5 급변 15% → 30분 정지
e, ex, cfg = mk(); step(e, ex, 340); step(e, ex, 280)
ok(e.grid_state("ADA").get("pause_until", 0) > time.time() + 1700 and e.grid_state("ADA")["buys"] == 1, "5 한 번에 -17.6% → 매수 안 하고 30분 정지")

# 6 하루 거래 한도 → 자동매매 꺼짐
e, ex, cfg = mk(max_trades_per_day=3)
for p in [340, 323, 306, 290, 275]: step(e, ex, p)
ok(not cfg["grid"]["enabled"] and ex.posts == 3, f"6 하루 3건 도달 → 자동 정지 (posts={ex.posts})")

# 7 전체 한도
e, ex, cfg = mk(total_max_krw=12000)
for p in [340, 323, 306, 290]: step(e, ex, p)
ok(e.grid_state("ADA")["cost"] <= 12000 and ex.posts == 2, f"7 전체 한도 1.2만 → 2회에서 멈춤 (원가 {e.grid_state('ADA')['cost']:,.0f})")

# 8 1분 안 연속 매매 금지
e, ex, cfg = mk(); step(e, ex, 340); step(e, ex, 300, skip_rate=False)
ok(ex.posts == 1, "8 직전 매매 1분 이내 → 대기")

# 9 체결 확인 지연 → pending → 사후 반영, 중복 없음
e, ex, cfg = mk(); ex.fail_next = "slow_confirm"
ex_fail = ex.fail_next
ex.fail_next = None
orig = ex.filled
ex.filled = lambda **k: (_ for _ in ()).throw(fo.UnknownResult("체결 확인 실패"))
step(e, ex, 340); ex.filled = orig
step(e, ex, 340); step(e, ex, 340)
ok(ex.posts == 1 and e.grid_state("ADA")["buys"] == 1, f"9 확인 지연 → 사후 반영, 추가 주문 없음 (posts={ex.posts})")

# 10 지나간 매도가 안 걸기
lv = {"price": 125_000_000, "sells": [123_310_000, 134_110_000, 144_910_000], "buys": [106_420_000, 102_970_000, 99_520_000], "stop": 94_600_000}
_, plan = fo.plan_orders("BTC", 0.05, levels=lv)
ok(all(o["price"] > 125_000_000 for o in plan if o["side"] == "ask"), "10 현재가 1.25억일 때 1차 매도 1.2331억은 안 걸음")

# 11 승인 사이 상태 변경 → 실행 안 함 / 현금 부족 → 실행 안 함
e, ex, cfg = mk(); ex.bal.update(BTC=0.05, ETH=0, XRP=0, KRW=10_000_000)
cfg["simulate"] = False
cfg["levels"] = {c: {"sells": [9e12, 9.1e12, 9.2e12], "buys": [1, 1, 1], "stop": 1} for c in fr.COINS}
cfg["levels"]["BTC"] = {"sells": [123_310_000, 134_110_000, 144_910_000], "buys": [106_420_000, 102_970_000, 99_520_000], "stop": 94_600_000}
orig_get = fr.get
fr.get = lambda path: [{"market": "KRW-BTC", "trade_price": 115_000_000}] if "ticker" in path else orig_get(path)
e.make_proposal("t", force=True, coins=["BTC"]); pid = e.proposal["id"]
ex.place("KRW-BTC", "ask", 0.01, 123_310_000)  # 승인 사이 누가 주문을 걸었다
e.execute(pid); a = alerts(e)
done = [x for x in list(e.events.queue)]
ok(len(ex.open) == 1, f"11a 승인 사이 변경 → 실행 안 함 (거래소 주문 {len(ex.open)}건 그대로)")
ex.open.clear(); ex.bal["KRW"] = 100_000
e.make_proposal("t", force=True, coins=["BTC"]); pid = e.proposal["id"]; e.execute(pid)
ok(len(ex.open) == 0, "11b 매수 주문 필요 현금 > 보유 현금 → 실행 안 함")
fr.get = orig_get

# 12 설정 파일 손상 → 백업으로 복구
d = tempfile.mkdtemp(); core.CONFIG_PATH = os.path.join(d, "c.json")
c = core.load_config(); c["grid"]["state"] = {"ADA": {"qty": 1.23}}; core.save_config(c); core.save_config(c)
open(core.CONFIG_PATH, "w").write('{"broken": ')
c2 = core.load_config()
ok(c2["grid"]["state"].get("ADA", {}).get("qty") == 1.23, "12 설정 파일이 깨져도 백업(.bak)에서 장부 복구")
