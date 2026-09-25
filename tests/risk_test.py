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
    cfg = core.load_config(); cfg["grid"].update(dict(simulate=False, coins=["ADA"], unit_krw=5000, profit_krw=250, max_krw=150000,
                                                      cash_warn=0, cash_floor_start=0, cash_floor_all=0), **grid)  # 현금 보호는 19번에서만
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
ex.bal["KRW"] = 10_000_000
e.make_proposal("t", force=True, coins=["BTC"]); p = e.proposal
sells = [i for i, (k, _, o) in enumerate(p["todo"]) if k == "place" and o["side"] == "ask"]
e.execute(p["id"], sells)
ok(len(ex.open) == len(sells) and all(o["side"] == "ask" for o in ex.open.values()),
   f"11c 주문 탭에서 고른 행만 실행 (매도 {len(sells)}건만, 매수 안 함)")
ex.open.clear()
e.make_proposal("t", force=True, coins=["BTC"]); pid = e.proposal["id"]
e.emergency_stop(False); e.execute(pid)
ok(len(ex.open) == 0 and cfg["mode"] == "alert", "11d 긴급 정지 중에는 승인해도 실행 안 함")
e.cfg["stopped"]["grid"] = True; assert not cfg["grid"]["enabled"]
e.resume()
ok(cfg["mode"] == "semi" and cfg["grid"]["enabled"] and not cfg.get("stopped"), "11e 재개하면 정지 전 모드·자동매매로 복귀")
fr.get = orig_get

# 13 하락 코인 자동 추가: 추천 목록 안에서만, 범위·거래대금·유의 필터, 하루 개수 제한, 익절 후 목록에서 빠짐
e, ex, cfg = mk()
g = cfg["grid"]; g["coins"] = ["ADA"]; ex.price.update(ADA=340.0)
g["dip"].update(enabled=True, pool=["XLM", "AVAX", "HBAR", "NEAR", "SUI", "DOT"], per_day=2, max_coins=15)
tick = {"XLM": (-6.0, 300e8), "AVAX": (-8.0, 120e8), "HBAR": (-20.0, 500e8), "NEAR": (-7.0, 10e8), "SUI": (-9.0, 900e8),
        "DOT": (-3.0, 100e8), "DRV": (-12.0, 200e8)}
orig_get = fr.get
def fake_get(path):
    if path.startswith("/market/all"):
        return [{"market": f"KRW-{c}", "market_event": {"warning": c == "SUI", "caution": {}}} for c in tick]
    ms = path.split("markets=")[1].split(",")
    return [{"market": m, "trade_price": 100.0, "signed_change_rate": tick[m[4:]][0] / 100,
             "acc_trade_price_24h": tick[m[4:]][1]} for m in ms]
fr.get = fake_get
added = e.grid_dip()
ok(added == ["AVAX", "XLM"], f"13a 조건 맞는 코인만, 많이 빠진 순서로 하루 2개 (추가: {added}; HBAR −20%·NEAR 거래대금 부족·SUI 유의·DOT −3%·목록 밖 DRV 제외)")
e._dip_ts = 0
ok(e.grid_dip() == [], "13b 하루 한도 다 차면 더 추가 안 함")
st = e.grid_state("AVAX"); ex.price["AVAX"] = 100.0; ex.bal["AVAX"] = 0.0
cfg["grid"]["simulate"] = True
e.grid_step("AVAX", 100.0); st["last_trade_ts"] = 0; e.grid_step("AVAX", 110.0)
ok("AVAX" not in g["coins"] and st["cycles"] == 1 and not st.get("auto"), "13c 자동 추가 코인은 익절로 사이클이 끝나면 목록에서 빠짐")
fr.get = orig_get

# 14 투자일지: 거래를 다시 따라간 실현 손익 합 = 엔진 누적 실현 (절반 매도·익절·물타기 포함)
e, ex, cfg = mk(unit_krw=10000, profit_krw=1000)
for p in (340, 323, 306, 290, 306, 323, 340, 360, 380):
    step(e, ex, p)
tr = core.build_journal(e.db, sim=False)
total = sum(t["pnl"] or 0 for t in tr)
st = e.grid_state("ADA")
ok(abs(total - st["profit_total"]) < 0.5 and st["cycles"] >= 1,
   f"14 투자일지 실현 합계 {total:,.1f}원 = 엔진 누적 실현 {st['profit_total']:,.1f}원 (사이클 {st['cycles']})")
day = core.journal_summary(tr, "date")
ok(abs(sum(d["pnl"] for d in day.values()) - total) < 0.01 and sum(d["buys"] for d in day.values()) == sum(1 for t in tr if t["side"] == "bid"),
   "14b 일별 합계 = 거래별 합계")

# 15 5,000원 미만 청산 → 주문 안 보내고 알림 / 장부 정리 → 장부 0, 목록에서 빠짐, 일지에 '장부 정리'
e, ex, cfg = mk(unit_krw=5000)
step(e, ex, 340)
st = e.grid_state("ADA"); posts = ex.posts
e.prices["ADA"] = 320.0
e.grid_liquidate("ADA"); a = alerts(e)
ok(ex.posts == posts and st["qty"] > 0 and any("5,000원 미만" in x for x in a), "15a 5,000원 미만은 청산 주문을 보내지 않고 알림")
e.grid_forget("ADA")
tr = core.build_journal(e.db, sim=False)
ok(st["qty"] == 0 and "ADA" not in cfg["grid"]["coins"] and tr[-1]["kind"] == "장부 정리 (추정)"
   and abs(sum(t["pnl"] or 0 for t in tr) - st["profit_total"]) < 0.5, "15b 장부 정리: 장부 0, 목록 제외, 일지 합계 = 엔진 누적")

# 16 마틴게일(배수 2): 추가 매수 1만 → 2만 → 4만, 코인 한도를 넘는 다음 매수는 안 함
e, ex, cfg = mk(unit_krw=10000, multiplier=2.0, max_krw=70000, profit_krw=100000)
ex.bal["KRW"] = 10_000_000
for p in (340, 323, 306, 290, 275, 260):
    step(e, ex, p)
tr = [t for t in core.build_journal(e.db, sim=False) if t["side"] == "bid"]
amts = [round(t["krw"]) for t in tr]
ok(amts == [10000, 20000, 40000], f"16 마틴게일 매수 금액 {amts} (4번째 8만은 한도 7만 초과라 안 삼)")

# 17 수익 재투자: 전체 한도 = 설정 한도 + 누적 실현 수익 (끄면 설정 한도 그대로)
e, ex, cfg = mk(unit_krw=10000, total_max_krw=20000, max_krw=100000, profit_krw=100000)
cfg["grid"]["state"]["XRPX"] = {"qty": 0, "cost": 0, "buys": 0, "ref": None, "halved": False, "realized": 0, "cycles": 3, "profit_total": 5000.0}
for p in (340, 323, 306):
    step(e, ex, p)
ok(e.grid_state("ADA")["buys"] == 2 and e.grid_total_cap() == 25000, f"17a 재투자 켬: 한도 2만 + 수익 5천 = 2.5만 → 2회까지 (buys={e.grid_state('ADA')['buys']})")
cfg["grid"]["reinvest"] = False
ok(e.grid_total_cap() == 20000, "17b 재투자 끄면 설정 한도 그대로")

# 18 투자유의 지정 → 자동매매 보유분 자동 청산 / 주의 지정 → 매수만 중지, 보유 유지
e, ex, cfg = mk(unit_krw=10000)
step(e, ex, 340)
orig_get = fr.get
flags = {"ADA": {"warning": False, "caution": {"PRICE_FLUCTUATIONS": True}}}
fr.get = lambda path: ([{"market": "KRW-ADA", "market_event": flags["ADA"]}] if path.startswith("/market/all") else orig_get(path))
e.grid_check_warnings(force=True)
st = e.grid_state("ADA")
ok(st["qty"] > 0 and st.get("blocked"), "18a 주의(가격 급등락) 지정: 새 매수만 중지, 보유분 유지")
flags["ADA"] = {"warning": True, "caution": {}}
e.grid_check_warnings(force=True)
ok(st["qty"] == 0 and "ADA" not in cfg["grid"]["coins"] and ex.bal["ADA"] < 1e-9, "18b 투자유의 지정: 자동매매 보유분 즉시 청산, 목록에서 제외")
fr.get = orig_get

# 19 현금 보호: 주문 가능 원화가 보호선 아래면 새 시작 매수 중지, 비상선 아래면 물타기도 중지
e, ex, cfg = mk(unit_krw=10000, cash_floor_start=100_000, cash_floor_all=50_000, cash_warn=200_000)
ex.bal["KRW"] = 105_000
step(e, ex, 340)
ok(e.grid_state("ADA")["qty"] == 0, "19a 사고 나면 10만 원(위험선) 아래 → 새 시작 매수 안 함")
ex.bal["KRW"] = 200_000; e._krw_cache = None
step(e, ex, 340)
ok(e.grid_state("ADA")["buys"] == 1, "19b 현금 충분 → 시작 매수")
ex.bal["KRW"] = 55_000; e._krw_cache = None
step(e, ex, 320)  # 5.9% 하락 = 물타기 조건
ok(e.grid_state("ADA")["buys"] == 1, "19c 물타기 조건이어도 사고 나면 5만 원(비상선) 아래 → 물타기 안 함")
ex.bal["KRW"] = 90_000; e._krw_cache = None
step(e, ex, 320)
ok(e.grid_state("ADA")["buys"] == 2, "19d 위험 단계(10만 아래)여도 비상선 위면 물타기는 함")
e._krw_cache = None; e.cash_stage_check()
ok(cfg["grid"]["cash_stage"] == 2, f"19e 현금 단계 알림 (위험 단계={cfg['grid'].get('cash_stage')})")

# 12 설정 파일 손상 → 백업으로 복구
d = tempfile.mkdtemp(); core.CONFIG_PATH = os.path.join(d, "c.json")
c = core.load_config(); c["grid"]["state"] = {"ADA": {"qty": 1.23}}; core.save_config(c); core.save_config(c)
open(core.CONFIG_PATH, "w").write('{"broken": ')
c2 = core.load_config()
ok(c2["grid"]["state"].get("ADA", {}).get("qty") == 1.23, "12 설정 파일이 깨져도 백업(.bak)에서 장부 복구")
