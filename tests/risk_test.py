"""실전 오류 상황 재현 테스트 (가짜 거래소). 실행: python tests/risk_test.py  — 모두 PASS여야 한다."""
import os, sys, queue, tempfile, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fibtrader_core as core, fib_orders as fo, fib_recalc as fr

class Ex:
    """가짜 업비트: 시장가 즉시 체결, identifier 중복 거부, 장애 주입."""
    def __init__(s):
        s.price = {"ADA": 340.0}; s.bal = {"KRW": 1_000_000.0, "ADA": 0.0}; s.orders = {}; s.by_ident = {}; s.avg = {}
        s.fail_next = None; s.n = 0; s.posts = 0; s.open = {}
    def _fill(s, market, side, amount):
        c = market[4:]; p = s.price[c]
        if side == "bid":
            if s.bal["KRW"] < amount: raise RuntimeError("POST /orders 실패 400: insufficient_funds_bid")
            fee = amount * 0.0005; vol = (amount - fee) / p
            s.avg[c] = (s.avg.get(c, 0.0) * s.bal[c] + (amount - fee)) / (s.bal[c] + vol)  # 업비트 매수평균가 (수수료 제외)
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
        if path == "/accounts": return [{"currency": k, "balance": str(v), "locked": "0", "avg_buy_price": str(s.avg.get(k, 0))} for k, v in s.bal.items()]
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
                                                      cash_warn=0, cash_floor_start=0, cash_floor_all=0, limit_tp=False, btc_filter=False), **grid)  # 현금 보호는 19번에서만, 지정가 익절은 L번에서만
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
flags = {"ADA": {"warning": False, "caution": {"CONCENTRATION_OF_SMALL_ACCOUNTS": True}}}
fr.get = lambda path: ([{"market": "KRW-ADA", "market_event": flags["ADA"]}] if path.startswith("/market/all") else orig_get(path))
e.grid_check_warnings(force=True)
st = e.grid_state("ADA")
ok(st["qty"] > 0 and st.get("blocked") and e.grid_view()[0]["status"] == "주의 · 새 매수 쉼",
   "18a 주의(소수 계정 거래 집중) 지정: 새 매수만 중지, 보유분 유지, 화면은 '주의 · 새 매수 쉼'")
flags["ADA"] = {"warning": False, "caution": {"DEPOSIT_AMOUNT_SOARING": True, "PRICE_FLUCTUATIONS": True,
                                               "TRADING_VOLUME_SOARING": True, "GLOBAL_PRICE_DIFFERENCES": True}}
e.grid_check_warnings(force=True)
ok(st["qty"] > 0 and not st.get("blocked") and e.grid_view()[0]["status"] == "자동매매 중",
   "18c 입금량·가격 급등락·거래량·해외 가격 차이는 새 매수를 쉬지 않음 (상장폐지 사유 아님)")
flags["ADA"] = {"warning": False, "caution": {"TRADING_VOLUME_SOARING": True, "CONCENTRATION_OF_SMALL_ACCOUNTS": True}}
e.grid_check_warnings(force=True)
ok(st.get("blocked") and st.get("blocked_why") == "caution", "18d 소수 계정 거래 집중이 같이 있으면 새 매수 쉼")
for saved, want in (({"caution_block": ["PRICE_FLUCTUATIONS", "TRADING_VOLUME_SOARING", "GLOBAL_PRICE_DIFFERENCES", "CONCENTRATION_OF_SMALL_ACCOUNTS"]},
                     ["CONCENTRATION_OF_SMALL_ACCOUNTS"]), ({"caution_v": 2, "caution_block": []}, [])):
    d = tempfile.mkdtemp(); _p = core.CONFIG_PATH; core.CONFIG_PATH = os.path.join(d, "c.json")
    open(core.CONFIG_PATH, "w", encoding="utf-8").write(json.dumps({"grid": saved}))
    got = core.load_config()["grid"]["caution_block"]; core.CONFIG_PATH = _p
    ok(got == want, f"18e 설정 이전 {saved} → {got}")
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

# 20 절반 매도 결과가 불명확 → 사후 반영할 때 '절반 판 상태'로 표시 (본전 위에서 절반을 또 팔면 안 됨)
e, ex, cfg = mk(multiplier=1.0, drop_pct=5.0, unit_krw=10000, profit_krw=500, half_at_breakeven=True)
step(e, ex, 340); step(e, ex, 320)
ok(e.grid_state("ADA")["buys"] == 2 and ex.posts == 2, "20a 2회 매수")
ex.fail_next = "lost_after"; step(e, ex, 335)
ok(e.grid_state("ADA").get("pending") and ex.posts == 3, "20b 본전 위 절반 매도 → 결과 불명확 (pending)")
step(e, ex, 335); step(e, ex, 335); step(e, ex, 335)
st = e.grid_state("ADA")
ok(ex.posts == 3 and st.get("halved") and abs(st["qty"] - ex.bal["ADA"]) < 1e-9,
   f"20c 사후 반영 뒤 절반 매도를 다시 하지 않음 (posts={ex.posts}, halved={st.get('halved')}, 장부 {st['qty']:.3f} = 거래소 {ex.bal['ADA']:.3f})")

# 22 기존 보유 합치기 = 업비트와 같은 장부: 예전 5천 원 → 장부 정리 → 1만 원 재시작 → 합치기(업비트 평단) → 익절
e, ex, cfg = mk(unit_krw=5000, profit_krw=500, multiplier=1.5, drop_pct=3.0)
step(e, ex, 300)                                  # 예전 5천 원 매수
e.prices["ADA"] = 320; e.grid_forget("ADA")       # 5천 원 미만이라 장부만 정리 (320원에 판 것으로 추정 → +손익 기록)
cfg["grid"].update(unit_krw=10000, coins=["ADA"])
step(e, ex, 340)                                  # 1만 원으로 새로 시작 → 계좌엔 예전 몫 + 새 몫
posts = ex.posts
e.prices["ADA"] = 340; e.grid_adopt("ADA")
st = e.grid_state("ADA")
up_cost = ex.bal["ADA"] * ex.avg["ADA"] * (1 + core.FEE)
tr = core.build_journal(e.db, False)
forget_pnl = [t["pnl"] for t in tr if t["kind"] == "장부 정리 (추정)"]
ok(ex.posts == posts and abs(st["qty"] - ex.bal["ADA"]) < 1e-9 and abs(st["cost"] - up_cost) < 0.01 and st["buys"] == 1,
   f"22a 합치기: 주문 없음, 수량 = 계좌, 원가 = 업비트 평단 기준 {st['cost']:,.0f}원, 매수 횟수 1 유지")
ok(forget_pnl and abs(forget_pnl[0]) < 0.01 and any(t["kind"] == "기존 보유 편입" for t in tr),
   f"22b 예전 장부 정리 추정 손익 취소 ({forget_pnl}), 일지에 '기존 보유 편입'")
step(e, ex, 345)                                  # 업비트 평단(약 327) 위 +5% → 수수료 뺀 수익 500원 넘으면 익절
st = e.grid_state("ADA"); tr = core.build_journal(e.db, False)
real = ex.bal["KRW"] - 1_000_000
ok(st["cycles"] >= 1 and ex.bal["ADA"] < 1e-9 and abs(sum(t["pnl"] or 0 for t in tr) - real) < 1 and abs(st["profit_total"] - real) < 1,
   f"22c 익절로 전부 매도, 일지 합계 = 엔진 누적 = 실제 현금 증가 {real:,.0f}원 (두 번 잡힌 손익 없음)")
e.grid_adopt("ADA"); ok(True, "22d 이미 맞춘 코인은 다시 눌러도 변화 없음")

# 21 업비트 API 연결 감시: 5분 넘게 실패하면 한 번만 경고, 다시 되면 복구 알림
e, ex, cfg = mk(); alerts(e)
feed = core.PriceFeed(e, e.events)
feed.api_health(False, "GET /accounts 실패 401: no_authorization_ip")
ok(not alerts(e), "21a 실패 직후에는 경고 안 함")
feed.api_fail_since -= 301; feed.api_health(False, "GET /accounts 실패 401: no_authorization_ip")
a = alerts(e)
ok(any("연결 끊김" in x for x in a), f"21b 5분 넘게 실패 → 경고 ({a})")
feed.api_health(False, "401"); ok(not alerts(e), "21c 경고는 한 번만")
feed.api_health(True); a = alerts(e)
ok(any("복구" in x for x in a) and feed.api_fail_since is None, "21d 다시 연결되면 복구 알림")

# 12 설정 파일 손상 → 백업으로 복구
d = tempfile.mkdtemp(); core.CONFIG_PATH = os.path.join(d, "c.json")
c = core.load_config(); c["grid"]["state"] = {"ADA": {"qty": 1.23}}; core.save_config(c); core.save_config(c)
open(core.CONFIG_PATH, "w").write('{"broken": ')
c2 = core.load_config()
ok(c2["grid"]["state"].get("ADA", {}).get("qty") == 1.23, "12 설정 파일이 깨져도 백업(.bak)에서 장부 복구")

# ---------- L: 지정가 익절 (실전) ----------
class LEx(Ex):
    """지정가 매도까지 흉내 내는 가짜 업비트: 주문 수량은 잠김(locked), 가격이 닿으면 지정가로 체결(일부 체결 가능),
    호가 단위·최소 주문 금액 검사, 취소하면 남은 수량 풀림."""
    def __init__(s, tick=1.0):
        super().__init__(); s.tick = tick; s.locked = {}; s.partial = None; s.fill_on_cancel = False; s.fail_place = None
    def _fill(s, market, side, amount):
        c = market[4:]
        if side == "ask" and s.bal[c] + 1e-12 < amount: raise RuntimeError("POST /orders 실패 400: insufficient_funds_ask")
        return super()._fill(market, side, amount)
    def call(s, meth, path, params=None):
        if path == "/accounts":
            return [{"currency": k, "balance": str(v), "locked": str(s.locked.get(k, 0.0)), "avg_buy_price": str(s.avg.get(k, 0))}
                    for k, v in s.bal.items()]
        raise RuntimeError("unsupported")
    def open_all(s): return [dict(o) for o in s.open.values()]
    def get_order(s, uuid=None, identifier=None):
        o = s.by_ident.get(identifier) if identifier else s.orders.get(uuid)
        return json.loads(json.dumps(o)) if o else None
    def place(s, m, side, v, p, identifier=None):
        c = m[4:]; v = float(f"{int(v * 1e8) / 1e8:.8f}"); p = float(fo.price_str(p))
        s.posts += 1
        mode, s.fail_place = s.fail_place, None
        if mode == "lost_before": raise fo.UnknownResult("timeout (주문 안 들어감)")
        if identifier in s.by_ident: raise RuntimeError("POST /orders 실패 400: duplicate identifier")
        if abs(p / s.tick - round(p / s.tick)) > 1e-9: raise RuntimeError("POST /orders 실패 400: invalid_price_ask")
        if v * p < 5000: raise RuntimeError(f"POST /orders 실패 400: under_min_total_{side}")
        if side == "ask":
            if s.bal[c] + 1e-12 < v: raise RuntimeError("POST /orders 실패 400: insufficient_funds_ask")
            s.bal[c] -= v; s.locked[c] = s.locked.get(c, 0.0) + v
        else:
            need = v * p * 1.0005
            if s.bal["KRW"] + 1e-9 < need: raise RuntimeError("POST /orders 실패 400: insufficient_funds_bid")
            s.bal["KRW"] -= need; s.locked["KRW"] = s.locked.get("KRW", 0.0) + need
        s.n += 1; u = f"L{s.n}"
        o = {"uuid": u, "identifier": identifier, "market": m, "side": side, "ord_type": "limit", "state": "wait", "price": str(p),
             "volume": str(v), "remaining_volume": str(v), "executed_volume": "0", "paid_fee": "0", "trades": []}
        s.orders[u] = o; s.by_ident[identifier] = o; s.open[u] = o
        if side == "ask" and s.price[c] >= p: s._exec(o, v, s.price[c])  # 현재가보다 낮게 걸면 바로 체결
        if side == "bid" and s.price[c] <= p: s._exec(o, v, s.price[c])  # 현재가보다 높게 걸면 바로 체결
        if mode == "lost_after": raise fo.UnknownResult("timeout (주문은 들어감)")
        return {"uuid": u}
    def _exec(s, o, v, px):
        c = o["market"][4:]; rem = float(o["remaining_volume"]); v = min(v, rem)
        funds = v * px; fee = funds * 0.0005
        o["trades"].append({"funds": str(funds)})
        o["executed_volume"] = str(float(o["executed_volume"]) + v); o["remaining_volume"] = str(rem - v)
        o["paid_fee"] = str(float(o["paid_fee"]) + fee)
        if o["side"] == "ask":
            s.locked[c] -= v; s.bal["KRW"] += funds - fee
        else:  # 매수: 묶어 둔 원화에서 지정가 기준으로 뺐으니 싸게 사졌으면 차액을 돌려준다
            held = v * float(o["price"]) * 1.0005
            s.locked["KRW"] -= held; s.bal["KRW"] += held - (funds + fee); s.bal[c] += v
            s.avg[c] = (s.avg.get(c, 0.0) * (s.bal[c] - v + s.locked.get(c, 0.0)) + funds) / (s.bal[c] + s.locked.get(c, 0.0))
        if rem - v <= 1e-12: o["state"] = "done"; s.open.pop(o["uuid"], None)
    def move(s, coin, p):
        """가격이 p까지 오름/내림 → 닿은 매도 주문 체결 (partial이 있으면 그 비율만)."""
        s.price[coin] = p
        for o in list(s.open.values()):
            if o["market"] == f"KRW-{coin}" and ((o["side"] == "ask" and p >= float(o["price"])) or (o["side"] == "bid" and p <= float(o["price"]))):
                s._exec(o, float(o["remaining_volume"]) * (s.partial or 1.0), float(o["price"]))
    def cancel(s, u):
        o = s.open.get(u)
        if o is None: raise RuntimeError("DELETE /order 실패 404: order_not_found")
        if s.fill_on_cancel:  # 취소 직전에 체결돼 버림
            s.fill_on_cancel = False; s._exec(o, float(o["remaining_volume"]), float(o["price"]))
            raise RuntimeError("DELETE /order 실패 400: 이미 체결된 주문")
        c = o["market"][4:]; rem = float(o["remaining_volume"])
        if o["side"] == "ask":
            s.locked[c] -= rem; s.bal[c] += rem
        else:
            held = rem * float(o["price"]) * 1.0005; s.locked["KRW"] -= held; s.bal["KRW"] += held
        o["state"] = "cancel"; s.open.pop(u)
        return o

orig_get = fr.get
def lmk(tick=1.0, **grid):
    e, _, cfg = mk(**{**dict(limit_tp=True, limit_add=False, unit_krw=10000, profit_krw=500, multiplier=1.5, drop_pct=3.0, half_at_breakeven=True), **grid})
    ex = LEx(tick); e.api = ex
    fr.get = lambda path: [{"tick_size": str(ex.tick)}] if "instruments" in path else orig_get(path)
    return e, ex, cfg
def lstep(e, ex, p):
    ex.move("ADA", p); step(e, ex, p)
def ada(ex): return ex.bal["ADA"] + ex.locked.get("ADA", 0.0)
def cash_gain(ex): return ex.bal["KRW"] + ex.locked.get("KRW", 0.0) - 1_000_000
def jsum(e): return sum(t["pnl"] or 0 for t in core.build_journal(e.db, False))
def opens(ex): return sorted((o["price"], o["volume"]) for o in ex.open.values())

# L1 시작 매수 → 익절가에 지정가 1건 (호가 단위로 올림, 수량 = 장부 수량)
e, ex, cfg = lmk()
lstep(e, ex, 340)
st = e.grid_state("ADA"); o = list(ex.open.values())
exact = (500 + st["cost"]) / (st["qty"] * (1 - core.FEE))
ok(len(o) == 1 and float(o[0]["price"]) == __import__("math").ceil(exact) and abs(float(o[0]["volume"]) - st["qty"]) < 1e-8
   and abs(ada(ex) - st["qty"]) < 1e-7 and ex.bal["ADA"] < 1e-7,
   f"L1 시작 매수 후 지정가 매도 1건 @{o[0]['price'] if o else '-'} (정확한 익절가 {exact:.2f} 올림), 수량 = 장부 = 계좌(전부 잠김)")
posts = ex.posts; lstep(e, ex, 345); lstep(e, ex, 341)
ok(ex.posts == posts and len(ex.open) == 1, "L1b 가격만 움직이면 주문 그대로 (취소·재주문 없음)")

# L2 가격이 익절가에 닿으면 업비트가 지정가로 팔고 → 사이클 종료, 장부 = 일지 = 실제 현금
tp = float(list(ex.open.values())[0]["price"])
lstep(e, ex, tp)
st = e.grid_state("ADA")
ok(st["cycles"] == 1 and st["qty"] == 0 and ada(ex) < 1e-7 and not st.get("tp") and not ex.open
   and 500 <= st["profit_total"] < 500 + 40 and abs(st["profit_total"] - cash_gain(ex)) < 0.01 and abs(jsum(e) - cash_gain(ex)) < 0.01,
   f"L2 익절가 {tp:g}에 체결 → 수익 {st['profit_total']:,.1f}원 (≥500) = 실제 현금 {cash_gain(ex):,.1f} = 일지 {jsum(e):,.1f}")
lstep(e, ex, tp)
ok(e.grid_state("ADA")["buys"] == 1 and len(ex.open) == 1, "L2b 다음 확인에서 다시 시작 매수 + 새 지정가")

# L3 추가 매수: 기존 주문 취소 → 매수 → 새 수량·새 가격으로 절반(본전) + 나머지(익절) 2건
e, ex, cfg = lmk()
lstep(e, ex, 340); first = list(ex.open)[0]
lstep(e, ex, 329)
st = e.grid_state("ADA"); o = sorted(ex.open.values(), key=lambda x: float(x["price"]))
be = st["cost"] / st["qty"] / (1 - core.FEE)
ok(ex.orders[first]["state"] == "cancel" and first not in ex.open, "L3a 추가 매수 때 기존 지정가 취소")
ok(st["buys"] == 2 and len(o) == 2 and abs(sum(float(x["volume"]) for x in o) - st["qty"]) < 3e-8 and abs(ada(ex) - st["qty"]) < 1e-7
   and float(o[0]["price"]) == __import__("math").ceil(be) and float(o[1]["price"]) > float(o[0]["price"]),
   f"L3b 2회 매수 뒤 새 주문 2건: 절반 @{o[0]['price']} (본전 {be:.2f} 올림) + 나머지 @{o[1]['price']}, 수량 합 = 장부 = 계좌")
# L4 절반 체결 → halved, 나머지 익절가 체결 → 사이클 종료, 수익 ≥ 500, 장부 = 일지 = 현금
lstep(e, ex, float(o[0]["price"]))
st = e.grid_state("ADA")
ok(st["halved"] and st["qty"] > 0 and len(ex.open) == 1 and abs(ada(ex) - st["qty"]) < 1e-7, "L4a 본전에서 절반 체결 → 절반 판 상태, 나머지 주문 유지")
rest = float(list(ex.open.values())[0]["price"])
lstep(e, ex, rest)
st = e.grid_state("ADA")
ok(st["cycles"] == 1 and ada(ex) < 1e-7 and 500 <= st["profit_total"] < 560 and abs(st["profit_total"] - cash_gain(ex)) < 0.01
   and abs(jsum(e) - cash_gain(ex)) < 0.01,
   f"L4b 나머지 {rest:g}에 체결 → 사이클 수익 {st['profit_total']:,.1f}원 = 현금 {cash_gain(ex):,.1f} = 일지 {jsum(e):,.1f}")

# L5 일부 체결 뒤 추가 매수 → 체결분은 장부에 반영, 남은 수량만큼 새로 걸기 → 끝까지 가도 장부 = 일지 = 현금
e, ex, cfg = lmk()
lstep(e, ex, 340); tp = float(list(ex.open.values())[0]["price"])
ex.partial = 0.4; lstep(e, ex, tp); ex.partial = None
st = e.grid_state("ADA")
ok(0 < st["qty"] and abs(ada(ex) - st["qty"]) < 1e-7 and st["cycles"] == 0 and st["realized"] > 0 and len(ex.open) == 1,
   f"L5a 40% 일부 체결 → 장부 반영(실현 {st['realized']:,.1f}원), 사이클은 진행 중")
lstep(e, ex, 329)
st = e.grid_state("ADA")
ok(st["buys"] == 2 and abs(sum(float(x["volume"]) for x in ex.open.values()) - st["qty"]) < 3e-8 and abs(ada(ex) - st["qty"]) < 1e-7,
   "L5b 추가 매수 → 남은 수량 + 새로 산 수량으로 다시 걸기")
for p in sorted(float(x["price"]) for x in ex.open.values()):
    lstep(e, ex, p)
st = e.grid_state("ADA")
ok(st["cycles"] == 1 and ada(ex) < 1e-7 and abs(st["profit_total"] - cash_gain(ex)) < 0.01 and abs(jsum(e) - cash_gain(ex)) < 0.01
   and st["profit_total"] >= 500, f"L5c 사이클 종료: 수익 {st['profit_total']:,.1f} = 현금 {cash_gain(ex):,.1f} = 일지 {jsum(e):,.1f}")

# L6 취소하려는 순간 체결돼 버림 → 익절로 처리하고 추가 매수 안 함
e, ex, cfg = lmk()
lstep(e, ex, 340); posts = ex.posts
ex.fill_on_cancel = True; lstep(e, ex, 329)
st = e.grid_state("ADA")
ok(st["cycles"] == 1 and st["qty"] == 0 and ex.posts == posts and ada(ex) < 1e-7 and abs(st["profit_total"] - cash_gain(ex)) < 0.01,
   f"L6 취소 직전 체결 → 사이클 종료로 반영, 물타기 주문 안 나감 (수익 {st['profit_total']:,.1f} = 현금 {cash_gain(ex):,.1f})")

# L7 지정가 주문이 결과 불명확 → 다음 확인 때 고유 번호로 찾음, 중복 주문 없음
e, ex, cfg = lmk()
ex.fail_place = "lost_after"; lstep(e, ex, 340)
posts = ex.posts; lstep(e, ex, 341); lstep(e, ex, 342)
st = e.grid_state("ADA")
ok(ex.posts == posts and len(ex.open) == 1 and st["tp"][0]["uuid"], "L7a 주문은 들어갔는데 응답 못 받음 → 찾아서 이어감 (재주문 없음)")
e, ex, cfg = lmk()
ex.fail_place = "lost_before"; lstep(e, ex, 340)
lstep(e, ex, 341); ok(len(ex.open) == 0 and len(e.grid_state("ADA")["tp"]) == 1, "L7b 안 들어간 주문: 1분 안에는 재주문 안 함")
e.grid_state("ADA")["tp"][0]["ts"] -= 61; lstep(e, ex, 341); lstep(e, ex, 341)
ok(len(ex.open) == 1 and ada(ex) - e.grid_state("ADA")["qty"] < 1e-9, "L7c 1분 뒤 없는 것 확인 → 새로 1건")

# L8 청산: 지정가 먼저 취소 → 시장가 전량 매도 / 긴급 정지: 자동매매 지정가도 취소
e, ex, cfg = lmk()
lstep(e, ex, 340); lstep(e, ex, 329)
e.grid_liquidate("ADA")
st = e.grid_state("ADA")
ok(not ex.open and ada(ex) < 1e-7 and st["qty"] == 0 and abs(st["profit_total"] - cash_gain(ex)) < 0.01 and "ADA" not in cfg["grid"]["coins"],
   f"L8a 청산: 걸린 주문 취소 후 전량 매도, 손익 {st['profit_total']:,.0f} = 현금 {cash_gain(ex):,.0f}")
e, ex, cfg = lmk()
lstep(e, ex, 340)
e.emergency_stop(True)
ok(not ex.open and not e.grid_state("ADA").get("tp") and not cfg["grid"]["enabled"], "L8b 긴급 정지(주문 취소) → 자동매매 지정가도 취소")

# L9 업비트 앱에서 사용자가 주문을 취소 → 알림 후 장부 수량으로 다시 걸기
e, ex, cfg = lmk()
lstep(e, ex, 340); alerts(e)
ex.cancel(list(ex.open)[0]); lstep(e, ex, 341)
a = alerts(e)
ok(len(ex.open) == 1 and any("취소됨" in x for x in a), "L9 앱에서 취소된 주문 감지 → 다시 걸기")

# L10 기존 보유 합치기: 걸린 주문 취소 → 합친 수량으로 다시 걸기
e, ex, cfg = lmk()
ex.bal["ADA"] = 20.0; ex.avg["ADA"] = 330.0   # 따로 산 기존 보유
lstep(e, ex, 340)
e.prices["ADA"] = 340; e.grid_adopt("ADA"); lstep(e, ex, 341)
st = e.grid_state("ADA")
ok(abs(st["qty"] - ada(ex)) < 1e-7 and abs(sum(float(x["volume"]) for x in ex.open.values()) - st["qty"]) < 3e-8 and ex.bal["ADA"] < 1e-7,
   f"L10 합치기 → 합친 수량 {st['qty']:.3f} 전부 지정가로 다시 걸림")

# L11 소수 호가 (0.1원 단위): 가격 문자열·올림
ok(fo.price_str(136.7) == "136.7" and fo.price_str(1234.0) == "1234" and core.tick_up(100.01, 0.1) == 100.1 and core.tick_up(340.0, 1) == 340,
   "L11a 가격 문자열 136.7 / 1234, 올림 100.01→100.1")
e, ex, cfg = lmk(tick=0.1)
lstep(e, ex, 136.2)
o = list(ex.open.values())
ok(len(o) == 1 and abs(float(o[0]["price"]) * 10 - round(float(o[0]["price"]) * 10)) < 1e-9, f"L11b 0.1원 단위 코인도 지정가 걸림 @{o[0]['price'] if o else '-'}")
lstep(e, ex, float(o[0]["price"]))
ok(e.grid_state("ADA")["cycles"] == 1 and abs(e.grid_state("ADA")["profit_total"] - cash_gain(ex)) < 0.01 and e.grid_state("ADA")["profit_total"] >= 500,
   f"L11c 0.1원 단위 익절 {e.grid_state('ADA')['profit_total']:,.1f}원")

# L12 지정가 익절을 끄면 걸린 주문을 취소하고 시장가 방식으로
e, ex, cfg = lmk()
lstep(e, ex, 340)
cfg["grid"]["limit_tp"] = False
e.grid_tp_cancel("ADA")  # check_prices가 지정가 끈 걸 보면 하는 일
lstep(e, ex, 360)
st = e.grid_state("ADA")
ok(not ex.open and st["cycles"] == 1 and abs(st["profit_total"] - cash_gain(ex)) < 0.01, "L12 지정가 끄면 시장가 방식으로 익절")
fr.get = orig_get

# ---------- M: 지정가 물타기 (실전) ----------
def mmk(**grid):
    e, ex, cfg = lmk(**{"limit_add": True, **grid}); return e, ex, cfg
def bids(ex): return [o for o in ex.open.values() if o["side"] == "bid"]
def asks(ex): return [o for o in ex.open.values() if o["side"] == "ask"]
def books_ok(e, ex):  # 장부 수량 = 계좌 코인(잠긴 것 포함)
    return abs(e.grid_state("ADA")["qty"] - ada(ex)) < 1e-7

# M1 시작 매수 → 익절 지정가 + 다음 물타기 지정가(340×0.97 → 329원, 1.5만)
e, ex, cfg = mmk()
lstep(e, ex, 340)
b = bids(ex)
ok(len(asks(ex)) == 1 and len(b) == 1 and float(b[0]["price"]) == 329 and abs(float(b[0]["volume"]) * 329 - 15000) < 1
   and abs(ex.locked["KRW"] - 15000 * 1.0005) < 1, f"M1 익절 매도 1건 + 물타기 매수 1건 @{b[0]['price'] if b else '-'} 1.5만 (원화 묶임 {ex.locked.get('KRW', 0):,.0f})")
# M2 가격이 329에 닿음 → 업비트가 사 줌 → 장부 반영, 익절 다시 걸기(절반+나머지), 다음 물타기(319원, 2.25만)
lstep(e, ex, 329)
st = e.grid_state("ADA"); b = bids(ex); a = sorted(asks(ex), key=lambda o: float(o["price"]))
ok(st["buys"] == 2 and books_ok(e, ex) and abs(st["cost"] - (10000 + 15000 * 1.0005)) < 2 and len(a) == 2
   and abs(sum(float(o["volume"]) for o in a) - st["qty"]) < 3e-8 and len(b) == 1 and float(b[0]["price"]) == 319
   and abs(float(b[0]["volume"]) * 319 - 22500) < 1,
   f"M2 329원 체결 → 2회, 원가 {st['cost']:,.0f}, 익절 2건(절반 @{a[0]['price'] if a else '-'}) 다시 걸림, 다음 물타기 @{b[0]['price'] if b else '-'} 2.25만")
# M3 반등 → 절반·나머지 익절 → 사이클 끝 → 걸어 둔 물타기 취소, 수익 = 현금 = 일지
for o in list(a):
    lstep(e, ex, float(o["price"]))
lstep(e, ex, float(a[-1]["price"]))
st = e.grid_state("ADA")
ok(st["cycles"] == 1 and not bids(ex) or (st["cycles"] == 1 and st["buys"] == 1),
   "M3a 익절로 사이클 끝 → 예전 물타기 주문 취소 (새 사이클이면 새 주문만)")
ok(st["cycles"] == 1 and st["profit_total"] >= 500 and abs(cash_gain(ex) + st["cost"] - st["profit_total"]) < 1
   and abs(jsum(e) - st["profit_total"]) < 0.01,
   f"M3b 사이클 수익 {st['profit_total']:,.1f}원 (≥500) = 일지 {jsum(e):,.1f} = 현금 증가 + 새 사이클 원가")

# M4 연속 급락: 329 → 319 → 309 체결, 매번 장부·익절·다음 물타기 갱신, 원화 = 계산과 일치
e, ex, cfg = mmk()
lstep(e, ex, 340)
for p in (329, 319, 309):
    lstep(e, ex, p)
st = e.grid_state("ADA")
spent = 1_000_000 - (ex.bal["KRW"] + ex.locked.get("KRW", 0.0))
ok(st["buys"] == 4 and books_ok(e, ex) and abs(st["cost"] - spent) < 2 and len(bids(ex)) == 1 and len(asks(ex)) == 2,
   f"M4 3번 연속 지정가 물타기 → 4회, 장부 원가 {st['cost']:,.0f} = 실제 쓴 돈 {spent:,.0f}, 익절 2건 + 다음 매수 1건")

# M5 자동매매 끄기 → 걸어 둔 매수 취소 (익절은 그대로 두고 체결되면 반영) / 긴급 정지 → 전부 취소
e, ex, cfg = mmk()
lstep(e, ex, 340)
fr_get0 = fr.get
fr.get = lambda path: ([{"tick_size": str(ex.tick)}] if "instruments" in path else
                       [{"market": m, "trade_price": ex.price.get(m[4:], 1.0)} for m in path.split("markets=")[1].split(",")] if "ticker" in path
                       else fr_get0(path))
cfg["grid"]["enabled"] = False; e.levels = {}
e.check_prices()
ok(not bids(ex) and len(asks(ex)) == 1 and ex.locked.get("KRW", 0) < 1e-6, "M5a 자동매매 끔 → 물타기 매수 취소, 원화 풀림, 익절은 유지")
cfg["grid"]["enabled"] = True; lstep(e, ex, 341)
ok(len(bids(ex)) == 1, "M5b 다시 켜면 물타기 매수 다시 걸림")
e.emergency_stop(True)
ok(not ex.open and ex.locked.get("KRW", 0) < 1e-6, "M5c 긴급 정지(주문 취소) → 매수·매도 모두 취소")
fr.get = lambda path: [{"tick_size": str(ex.tick)}] if "instruments" in path else orig_get(path)

# M6 전체 한도: 걸어 둔 매수 금액도 한도에 포함 → 한도 넘으면 안 걸고, 시장가로도 안 삼
e, ex, cfg = mmk(total_max_krw=20000)
lstep(e, ex, 340); lstep(e, ex, 300)
ok(not bids(ex) and e.grid_state("ADA")["buys"] == 1, "M6 1만 + 다음 1.5만 > 전체 한도 2만 → 물타기 주문 안 걸고 안 삼")

# M7 매수 주문이 거절되면 10분간 예전(시장가) 방식으로 물타기
e, ex, cfg = mmk()
orig_place = ex.place
def rej(m, side, v, p, identifier=None):
    if side == "bid": raise RuntimeError("POST /orders 실패 400: invalid_price_bid")
    return orig_place(m, side, v, p, identifier)
ex.place = rej
lstep(e, ex, 340); lstep(e, ex, 329)
ok(e.grid_state("ADA")["buys"] == 2 and e.grid_state("ADA").get("bid_fail_until", 0) > time.time() and books_ok(e, ex),
   "M7 지정가 매수 거절 → 10분간 시장가로 물타기 (2회)")
ex.place = orig_place

# M8 매수 주문 결과 불명확 → 고유 번호로 찾아 이어감, 중복 없음
e, ex, cfg = mmk()
lstep(e, ex, 340)
e.grid_state("ADA").get("bid") and None
st = e.grid_state("ADA"); rid = st["bid"]["uuid"]
ex.cancel(rid); e.grid_state("ADA").pop("bid")   # 새로 걸 때 응답을 못 받는 상황 만들기
ex.fail_place = "lost_after"; lstep(e, ex, 341)
posts = ex.posts; lstep(e, ex, 341); lstep(e, ex, 342)
ok(len(bids(ex)) == 1 and ex.posts == posts and e.grid_state("ADA")["bid"]["uuid"], "M8 매수 주문 응답 못 받음 → 찾아서 이어감 (중복 주문 없음)")

# M9 매수 일부 체결 → 반영, 1분 지나면 나머지 취소하고 다음 단계로
e, ex, cfg = mmk()
lstep(e, ex, 340)
ex.partial = 0.5; lstep(e, ex, 329); ex.partial = None
st = e.grid_state("ADA")
ok(st["buys"] == 2 and books_ok(e, ex) and len(bids(ex)) == 1 and float(bids(ex)[0]["price"]) == 329,
   "M9a 절반만 사짐 → 2회로 반영, 나머지 주문은 1분 대기")
st["bid"]["fill_ts"] -= 61; lstep(e, ex, 335)
b = bids(ex); st = e.grid_state("ADA")
spent = 1_000_000 - (ex.bal["KRW"] + ex.locked.get("KRW", 0.0))
tr = [t for t in core.build_journal(e.db, False) if t["side"] == "bid"]
ok(len(b) == 1 and float(b[0]["price"]) == 319 and st["buys"] == 2 and abs(st["cost"] - spent) < 2 and books_ok(e, ex)
   and tr[-1]["kind"] == "물타기 2회", f"M9b 1분 뒤 나머지 취소 → 다음 물타기 @{b[0]['price'] if b else '-'}, 원가 = 실제 쓴 돈, 일지 '물타기 2회'")

# M10 투자유의·주의 지정(새 매수 중지) → 걸어 둔 매수 취소
e, ex, cfg = mmk()
lstep(e, ex, 340)
e.grid_state("ADA")["blocked"] = True; lstep(e, ex, 341)
ok(not bids(ex) and len(asks(ex)) == 1, "M10 새 매수 중지 지정 → 걸어 둔 물타기 매수 취소 (익절은 유지)")

# M11 청산: 매수·매도 주문 모두 취소 → 시장가 전량 매도, 손익 = 현금
e, ex, cfg = mmk()
lstep(e, ex, 340); lstep(e, ex, 329)
e.grid_liquidate("ADA")
st = e.grid_state("ADA")
ok(not ex.open and ada(ex) < 1e-7 and abs(st["profit_total"] - cash_gain(ex)) < 0.01, f"M11 청산: 주문 모두 취소 후 전량 매도, 손익 {st['profit_total']:,.0f} = 현금 {cash_gain(ex):,.0f}")
fr.get = orig_get

# N1 본전 매도 = 1회 금액(1만)어치: 2회 매수(1만+1.5만) 뒤 본전 주문은 약 1만 원어치, 나머지는 익절가
e, ex, cfg = lmk(limit_add=True)
lstep(e, ex, 340); lstep(e, ex, 329)
a = sorted((o for o in ex.open.values() if o["side"] == "ask"), key=lambda o: float(o["price"]))
st = e.grid_state("ADA")
ok(len(a) == 2 and abs(float(a[0]["volume"]) * float(a[0]["price"]) - 10000) < 40 and abs(sum(float(o["volume"]) for o in a) - st["qty"]) < 3e-8,
   f"N1 본전 매도 {float(a[0]['volume']) * float(a[0]['price']):,.0f}원어치 @{a[0]['price']} (1만), 나머지 {float(a[1]['volume']) * float(a[1]['price']):,.0f}원어치 @{a[1]['price']}")
lstep(e, ex, float(a[0]["price"]))
v = e.grid_view()[0]
ok(v["halved"] and st["halved"], "N1b 본전 매도 체결 → 화면에 '본전 매도함' 표시용 상태")
cfg["grid"]["be_sell"] = "half"
e2, ex2, _ = lmk(limit_add=True, be_sell="half")
lstep(e2, ex2, 340); lstep(e2, ex2, 329)
a2 = sorted((o for o in ex2.open.values() if o["side"] == "ask"), key=lambda o: float(o["price"]))
ok(abs(float(a2[0]["volume"]) - float(a2[1]["volume"])) < 1e-7, "N1c 설정을 '절반'으로 하면 예전처럼 반씩")
fr.get = orig_get

# N2 본전 매도 = 직전 단계 금액어치(기본): 3회(1만·1.5만·2.25만)면 1.5만, 4회면 2.25만어치. 나머지는 익절가, 수량 합 = 장부
e, ex, cfg = lmk(limit_add=True)
lstep(e, ex, 340); lstep(e, ex, 329); lstep(e, ex, 319)
st = e.grid_state("ADA")
a = sorted((o for o in ex.open.values() if o["side"] == "ask"), key=lambda o: float(o["price"]))
w = float(a[0]["volume"]) * float(a[0]["price"]) if a else 0
ok(st["buys"] == 3 and len(a) == 2 and abs(w - 15000) < 40 and abs(sum(float(o["volume"]) for o in a) - st["qty"]) < 3e-8,
   f"N2a 3회 매수 → 본전 매도 {w:,.0f}원어치 (1.5만)")
lstep(e, ex, 309)
st = e.grid_state("ADA")
a = sorted((o for o in ex.open.values() if o["side"] == "ask"), key=lambda o: float(o["price"]))
w = float(a[0]["volume"]) * float(a[0]["price"]) if a else 0
ok(st["buys"] == 4 and len(a) == 2 and abs(w - 22500) < 40 and abs(sum(float(o["volume"]) for o in a) - st["qty"]) < 3e-8 and books_ok(e, ex),
   f"N2b 4회 매수 → 취소 후 다시 걸린 본전 매도 {w:,.0f}원어치 (2.25만), 장부 일치")
lstep(e, ex, float(a[0]["price"]))
st = e.grid_state("ADA")
a = [o for o in ex.open.values() if o["side"] == "ask"]
ok(st["halved"] and len(a) == 1 and abs(float(a[0]["volume"]) - st["qty"]) < 3e-8 and books_ok(e, ex),
   "N2c 본전 매도 체결 → 나머지 전량은 익절가 1건")
fr.get = orig_get

# N3 설정 이전: 예전 저장 파일의 "unit"은 한 번만 "prev"로, "half"와 이전 뒤 고른 "unit"은 그대로
for saved, want in (({"be_sell": "unit"}, "prev"), ({"be_sell": "half"}, "half"), ({"be_sell": "unit", "be_sell_v": 2}, "unit"), ({}, "prev")):
    d = tempfile.mkdtemp(); core.CONFIG_PATH = os.path.join(d, "c.json")
    open(core.CONFIG_PATH, "w", encoding="utf-8").write(json.dumps({"grid": saved}))
    got = core.load_config()["grid"]["be_sell"]
    ok(got == want, f"N3 저장 {saved} → {got}")

# V1 음성 알림: 매수·익절 알림에 읽을 문장이 붙는다 (한국어 금액)
import fib_voice as fv
e, ex, cfg = lmk(limit_add=True)
lstep(e, ex, 340)
evs = [x for x in list(e.events.queue) if x[0] == "alert" and len(x) > 4 and x[4]]
tp = float([o for o in ex.open.values() if o["side"] == "ask"][0]["price"]); lstep(e, ex, tp)
evs += [x for x in list(e.events.queue) if x[0] == "alert" and len(x) > 4 and x[4] and x not in evs]
says = [x[4] for x in evs]
ok(("buy", "에이다, 만 원 샀습니다") in says and any(s[0] == "tp" and s[1].startswith("에이다 익절, 오백") for s in says),
   f"V1 음성 문장: {says}")
ok(fv.won(22500) == "이만이천오백 원" and fv.won(15000) == "만오천 원", "V1b 금액 읽기 2.25만 → 이만이천오백 원")
fr.get = orig_get

# R1 재진입 대기(2%): 익절 뒤 바로 안 사고, 판 가격 2% 아래에 지정가 매수 → 체결되면 새 사이클 (익절·물타기 다시 걸림)
e, ex, cfg = lmk(limit_add=True, reentry_pct=2.0)
lstep(e, ex, 340)
tp = float([o for o in ex.open.values() if o["side"] == "ask"][0]["price"])
lstep(e, ex, tp)                      # 익절
st = e.grid_state("ADA"); posts = ex.posts
lstep(e, ex, tp)                      # 다음 확인: 바로 안 사고 재진입 주문만
b = [o for o in ex.open.values() if o["side"] == "bid"]
target = int(tp * 0.98)
ok(st["qty"] == 0 and st["cycles"] == 1 and len(b) == 1 and float(b[0]["price"]) == target and abs(float(b[0]["volume"]) * target - 10000) < 1,
   f"R1a 익절 뒤 바로 안 삼 → {target}원(판 가격 {tp:g}의 −2%)에 1만 원 재진입 주문")
lstep(e, ex, target)                  # 내려와서 체결
st = e.grid_state("ADA")
a = [o for o in ex.open.values() if o["side"] == "ask"]; b = [o for o in ex.open.values() if o["side"] == "bid"]
ok(st["buys"] == 1 and books_ok(e, ex) and len(a) == 1 and len(b) == 1 and "last_exit" not in st and float(b[0]["price"]) < target,
   "R1b 재진입 체결 → 새 사이클 1회, 익절 매도 + 다음 물타기 매수 다시 걸림")
ok(abs(cash_gain(ex) + st["cost"] - st["profit_total"]) < 1 and abs(jsum(e) - st["profit_total"]) < 0.01, "R1c 장부 = 현금 = 일지")

# R2 24시간 안 내려오면 주문 취소하고 지금 가격에 삼
e, ex, cfg = lmk(limit_add=True, reentry_pct=2.0)
lstep(e, ex, 340)
tp = float([o for o in ex.open.values() if o["side"] == "ask"][0]["price"])
lstep(e, ex, tp); lstep(e, ex, tp + 5)
st = e.grid_state("ADA"); st["last_exit"]["ts"] -= 25 * 3600
lstep(e, ex, tp + 5)
st = e.grid_state("ADA"); b = [o for o in ex.open.values() if o["side"] == "bid"]
ok(st["buys"] == 1 and books_ok(e, ex) and len(b) == 1 and float(b[0]["price"]) < tp and "last_exit" not in st,
   "R2 24시간 지나도 안 내려옴 → 재진입 주문 취소, 지금 가격에 시작 매수 (다음 물타기 주문만 남음)")

# R3 모의(지정가 없음): 가격이 목표 아래로 보이면 그때 시장가로
e, ex, cfg = mk(unit_krw=10000, profit_krw=500, reentry_pct=2.0)
step(e, ex, 340); step(e, ex, 360)
st = e.grid_state("ADA")
step(e, ex, 358); c1 = st["cycles"], st["qty"]
step(e, ex, 352)
ok(c1[0] == 1 and c1[1] == 0 and st["qty"] > 0, "R3 시장가 방식: 358원(−0.6%)엔 안 사고 352원(−2.2%)에 다시 삼")

# ---------- T: 검토 후 수정 ----------
# T1 호가 단위는 자동매매 코인 전부를 한 번에 조회 (코인마다 따로 물으면 업비트 초당 조회 한도 429에 걸림), 실패하면 예전 값
e, ex, cfg = lmk(limit_add=True)
cfg["grid"]["coins"] = ["ADA", "XLM", "DOGE", "ETC"]
calls = []
def g1(path):
    calls.append(path)
    if "instruments" in path:
        return [{"market": m, "tick_size": "1" if m != "KRW-ETC" else "10"} for m in path.split("markets=")[1].split(",")]
    return orig_get(path)
fr.get = g1
ticks = [e.grid_tick(c) for c in ("ADA", "XLM", "DOGE", "ETC")]
ok(len([c for c in calls if "instruments" in c]) == 1 and ticks == [1.0, 1.0, 1.0, 10.0], f"T1a 코인 4개 호가 단위를 조회 1번으로 ({ticks})")
def g429(path):
    raise RuntimeError("HTTP Error 429: Too Many Requests")
fr.get = g429
e.ticks["ADA"] = (0, 1.0)
ok(e.grid_tick("ADA") == 1.0, "T1b 조회 실패(429)해도 예전 호가 단위로 계속")
fr.get = orig_get

# T2 조회 한도 초과(429)는 코인을 10분 정지시키지 않고 알림도 없이 다음 확인 때 다시
e, ex, cfg = lmk(limit_add=True)
fr.get = lambda path: ([{"market": m, "trade_price": 340.0} for m in path.split("markets=")[1].split(",")] if "ticker" in path
                       else [{"tick_size": "1"}] if "instruments" in path else orig_get(path))
e.levels = {}; alerts(e)
def boom(coin, price): raise RuntimeError("HTTP Error 429: Too Many Requests")
e.grid_step = boom
e.check_prices()
a = alerts(e)
ok(not e.grid_state("ADA").get("pause_until") and not any("오류" in x for x in a), "T2 429 → 정지·오류 알림 없음")
fr.get = orig_get

# T3 '지정가 익절 걸어 둠' 같은 정보 알림은 조용히 (팝업·소리 없이 기록만, 종류 order)
e, ex, cfg = lmk(limit_add=True)
lstep(e, ex, 340)
evs = [x for x in list(e.events.queue) if x[0] == "alert"]
tpa = [x for x in evs if "걸어 둠" in x[1]]
ok(tpa and all(x[3] == "order" and x[5] for x in tpa) and any(x[3] == "grid" and x[4] for x in evs),
   "T3 '걸어 둠'은 조용한 알림(order), 시작 매수는 소리 알림")

# T4 전체 한도: 다른 코인에 걸어 둔 매수 금액도 포함 → 시장가 시작 매수가 한도를 넘지 않음
e, ex, cfg = lmk(limit_add=True, total_max_krw=30_000)
cfg["grid"]["coins"] = ["ADA", "XLM"]; ex.price["XLM"] = 300.0; ex.bal["XLM"] = 0.0
lstep(e, ex, 340)                       # ADA 1만 + 물타기 1.5만 걸림 = 2.5만 예약
ex.price["XLM"] = 300.0; e.prices["XLM"] = 300.0; e.grid_state("XLM")["last_trade_ts"] = 0
e.grid_step("XLM", 300.0)
ok(e.grid_state("XLM")["qty"] == 0, "T4 ADA 원가 1만 + 걸어 둔 매수 1.5만 + XLM 1만 > 한도 3만 → XLM 시작 안 함")

# T5 오류로 잠깐 정지한 동안에는 걸어 둔 물타기 매수를 취소하지 않음 (급변·투자유의만 취소)
e, ex, cfg = lmk(limit_add=True)
lstep(e, ex, 340)
e.grid_state("ADA")["pause_until"] = time.time() + 600
ex.price["ADA"] = 341; e.prices["ADA"] = 341; e.grid_step("ADA", 341)
ok(len([o for o in ex.open.values() if o["side"] == "bid"]) == 1, "T5 오류 정지 중에도 물타기 매수 주문 유지")

# T6 현금 보호: 자동매매가 걸어 둔 매수에 묶인 원화는 쓸 수 있는 돈으로 계산
e, ex, cfg = lmk(limit_add=True)
lstep(e, ex, 340)
e._krw_cache = None
free = e.krw_free()
ok(abs(free - (ex.bal["KRW"] + ex.locked["KRW"])) < 1, f"T6 보호 계산 원화 {free:,.0f} = 주문 가능 {ex.bal['KRW']:,.0f} + 묶인 {ex.locked['KRW']:,.0f}")

# T7 비트코인 약세 필터: 전날 종가 < 20일 평균이면 새 시작 매수만 쉼, 들고 있는 코인의 물타기·익절은 그대로
def btc_days(closes):
    return lambda path: ([{"trade_price": 1.0}] + [{"trade_price": c} for c in closes] if "candles/days" in path
                         else [{"tick_size": "1"}] if "instruments" in path else orig_get(path))
e, ex, cfg = lmk(limit_add=True, btc_filter=True)
cfg["grid"]["coins"] = ["ADA", "XLM"]; ex.price["XLM"] = 300.0; ex.bal["XLM"] = 0.0
fr.get = btc_days([100.0] * 20)          # 평균과 같음 → 약세 아님
lstep(e, ex, 340)
ok(e.grid_state("ADA")["buys"] == 1, "T7a 비트코인 평균 이상 → 시작 매수")
e.btc_bear = None
fr.get = btc_days([90.0] + [100.0] * 19)  # 전날 종가가 평균 아래
e.prices["XLM"] = 300.0; e.grid_state("XLM")["last_trade_ts"] = 0; e.grid_step("XLM", 300.0)
lstep(e, ex, 329)                        # ADA 물타기는 그대로
v = {r["coin"]: r for r in e.grid_view()}
ok(e.grid_state("XLM")["qty"] == 0 and e.grid_state("ADA")["buys"] == 2 and v["XLM"]["status"] == "새 시작 쉼",
   "T7b 약세 → XLM 새 시작 쉼(화면 '새 시작 쉼'), ADA 물타기는 그대로 체결")
e.btc_bear = None
fr.get = btc_days([110.0] + [100.0] * 19)
e.grid_state("XLM")["last_trade_ts"] = 0; e.grid_step("XLM", 300.0)
ok(e.grid_state("XLM")["buys"] == 1 and any("회복" in x for x in alerts(e)), "T7c 회복 → 다시 시작 + 알림")
fr.get = orig_get

# T8 설정을 바꿔도 진행 중 사이클은 시작할 때 금액·익절액 그대로, 새 사이클부터 새 설정
e, ex, cfg = lmk(limit_add=False)
lstep(e, ex, 340)                                   # 1만 · 익절 500으로 시작
cfg["grid"].update(unit_krw=20_000, profit_krw=1000)  # 설정 변경: 2만 · 1,000
st = e.grid_state("ADA")
ok(e.grid_next_amount(st) == 15_000 and e.cycle_profit(st) == 500, "T8a 진행 중 사이클: 다음 물타기 1.5만(1만 기준), 익절 500 유지")
tp = float([o for o in ex.open.values() if o["side"] == "ask"][0]["price"])
lstep(e, ex, tp); lstep(e, ex, tp)
st = e.grid_state("ADA")
ok(st["cycles"] == 1 and abs(st["cost"] - 20_000) < 1 and st["unit"] == 20_000 and st["profit"] == 1000,
   f"T8b 익절 뒤 새 사이클은 2만 · 익절 1,000 (원가 {st['cost']:,.0f})")
fr.get = orig_get

# T9 배수·하락폭도 사이클 시작 때 기준 그대로: 1.5배·3%로 시작한 사이클은 설정을 1.1배·5%로 바꿔도 끝까지 1.5배·3%
e, ex, cfg = lmk(limit_add=True)
lstep(e, ex, 340); lstep(e, ex, 329)                # 1만 → 1.5만 (2회)
cfg["grid"].update(unit_krw=25_000, profit_krw=1250, multiplier=1.1, drop_pct=5.0)
lstep(e, ex, 330)                                   # 설정 바꾼 뒤 확인 주기
st = e.grid_state("ADA")
b = [o for o in ex.open.values() if o["side"] == "bid"]
a = sorted((o for o in ex.open.values() if o["side"] == "ask"), key=lambda o: float(o["price"]))
ok(len(b) == 1 and float(b[0]["price"]) == int(329 * 0.97) and abs(float(b[0]["volume"]) * float(b[0]["price"]) - 22_500) < 1,
   f"T9a 진행 중 사이클 다음 물타기: {b[0]['price'] if b else '-'}원(3% 아래)에 2.25만 (1.5배) 그대로")
lstep(e, ex, int(329 * 0.97))                       # 3회째 체결
a = sorted((o for o in ex.open.values() if o["side"] == "ask"), key=lambda o: float(o["price"]))
w = float(a[0]["volume"]) * float(a[0]["price"]) if a else 0
ok(e.grid_state("ADA")["buys"] == 3 and abs(w - 15_000) < 40 and books_ok(e, ex), f"T9b 본전 매도도 1.5배 기준 직전 단계 {w:,.0f}원어치 (1.5만)")
st = e.grid_state("ADA")
st_px = float(max(a, key=lambda o: float(o["price"]))["price"])
lstep(e, ex, float(a[0]["price"])); lstep(e, ex, st_px); lstep(e, ex, st_px)  # 본전 → 익절 → 새 사이클
st = e.grid_state("ADA")
b = [o for o in ex.open.values() if o["side"] == "bid"]
ok(st["cycles"] == 1 and st["buys"] == 1 and st["mult"] == 1.1 and st["drop"] == 5.0 and len(b) == 1
   and abs(float(b[0]["price"]) - int(st["ref"] * 0.95)) <= 1 and abs(float(b[0]["volume"]) * float(b[0]["price"]) - 27_500) < 30,
   f"T9c 새 사이클은 2.5만 · 1.1배 · 5%: 다음 물타기 {b[0]['price'] if b else '-'}원에 2.75만")
fr.get = orig_get

# T11 한 코인 몰림 방지: wide_after회 산 뒤부터 하락 간격을 넓힌다 (사이클 시작 때 값으로 도장)
e, ex, cfg = lmk(limit_add=True, multiplier=1.1, drop_pct=5.0, wide_after=3, wide_drop_pct=8.0)
lstep(e, ex, 1000)
b = [o for o in ex.open.values() if o["side"] == "bid"]
ok(len(b) == 1 and float(b[0]["price"]) == 950, f"T11a 1회 뒤 다음 물타기 5% 아래 ({b[0]['price'] if b else '-'})")
lstep(e, ex, 950)
b = [o for o in ex.open.values() if o["side"] == "bid"]
ok(len(b) == 1 and float(b[0]["price"]) == 902, f"T11b 2회 뒤도 5% 아래 ({b[0]['price'] if b else '-'})")
cfg["grid"].update(wide_after=10, wide_drop_pct=12.0)  # 진행 중 사이클은 시작할 때 값(3회·8%) 그대로
lstep(e, ex, 902)
st = e.grid_state("ADA")
b = [o for o in ex.open.values() if o["side"] == "bid"]
ok(st["buys"] == 3 and len(b) == 1 and float(b[0]["price"]) == int(902 * 0.92) and books_ok(e, ex),
   f"T11c 3회 뒤부터 8% 아래 ({b[0]['price'] if b else '-'} = 902의 −8%), 설정을 바꿔도 사이클 도장 유지")
v = e.grid_view()[0]
ok(abs(v["next_buy"] - 902 * 0.92) < 1e-6, "T11d 화면의 다음 추가매수가도 8% 기준")
fr.get = orig_get

# T10 장부 이전: 도장 전 진행 중 사이클 → 1.5배·3% 도장 (한 번만), 끝난 사이클·이미 이전된 장부는 그대로
for saved, want in (({"state": {"ADA": {"qty": 1.0}}}, (1.5, 3.0)), ({"state": {"ADA": {"qty": 0.0}}}, (None, None)),
                    ({"cycle_v": 2, "state": {"ADA": {"qty": 1.0}}}, (None, None)),
                    ({"state": {"ADA": {"qty": 1.0, "mult": 1.1, "drop": 5.0}}}, (1.1, 5.0))):
    d = tempfile.mkdtemp(); core.CONFIG_PATH = os.path.join(d, "c.json")
    open(core.CONFIG_PATH, "w", encoding="utf-8").write(json.dumps({"grid": {**saved, "multiplier": 1.1, "drop_pct": 5.0}}))
    s = core.load_config()["grid"]["state"]["ADA"]
    ok((s.get("mult"), s.get("drop")) == want, f"T10 저장 {saved} → 배수·하락 {(s.get('mult'), s.get('drop'))}")

# G1 텔레그램 (조회 전용): 주인 채팅만 응답, 주인 번호 없으면 번호만 알려 줌, 알림은 주인에게만, 현황 글 생성
import fib_telegram as ftg
got = []
tg = ftg.Telegram(got.append, token="x", chat_id="111")
tg.handle({"chat": {"id": 222}, "text": "/status"})
tg.handle({"chat": {"id": 111}, "text": "현황"})
tg.handle({"chat": {"id": 111}, "text": "/today@FibBot"})
tg.handle({"chat": {"id": 111}, "text": "/sell BTC"})
sent = [tg.out.get_nowait() for _ in range(tg.out.qsize())]
ok(got == ["status", "today"] and len(sent) == 1 and sent[0][0] == "111" and "조회 전용" in sent[0][1],
   f"G1a 남의 채팅 무시, 주인 명령만 처리, 모르는 명령(매도 등)엔 안내만: {got}")
tg2 = ftg.Telegram(got.append, token="x", chat_id="")
tg2.handle({"chat": {"id": 333}, "text": "/status"}); tg2.notify("알림", "내용")
sent = [tg2.out.get_nowait() for _ in range(tg2.out.qsize())]
ok(len(sent) == 1 and sent[0][0] == "333" and "333" in sent[0][1] and "[자동매매" not in sent[0][1] and got == ["status", "today"],
   "G1b 주인 번호 없을 때: 말 건 채팅에 번호만 알려 주고 현황·알림은 안 보냄")
ok(not ftg.Telegram(got.append, token="", chat_id="1").enabled, "G1c 토큰 없으면 꺼짐")
e, ex, cfg = lmk(limit_add=True)
e.tg = ftg.Telegram(lambda c: None, token="x", chat_id="111")
lstep(e, ex, 340); lstep(e, ex, 329)
fr.get = lambda path: [{"market": m, "trade_price": 330.0, "signed_change_rate": -0.02} for m in path.split("=")[1].split(",")] if "ticker" in path else orig_get(path)
txt = e.tg_status_text(); day = e.tg_day_text(core.now().strftime("%Y-%m-%d"), "오늘")
msgs = [e.tg.out.get_nowait()[1] for _ in range(e.tg.out.qsize())]
ok("[자동매매" in txt and "ADA 330" in txt and "2회" in txt and "매수 2번" in day and any("물타기" in m for m in msgs),
   "G1d 현황·오늘 글 생성, 매수 알림은 텔레그램으로도 보냄")
# G2 추가 조회 명령 11가지: 말 → 명령 연결, 코인 이름만 보내도 됨, 글이 오류 없이 만들어짐
got = []
tg = ftg.Telegram(got.append, token="x", chat_id="111")
for text in ("수익", "/month", "시세", "/balance", "주문", "플랜", "/risk", "알림", "점검", "어제", "xrp", "/coin ada", "/coin", "/sell", "매도 BTC"):
    tg.handle({"chat": {"id": 111}, "text": text})
sent = [tg.out.get_nowait()[1] for _ in range(tg.out.qsize())]
ok(got == ["pnl", "month", "price", "balance", "orders", "plan", "risk", "alerts", "check", "yesterday", "coin:XRP", "coin:ADA"]
   and len(sent) == 3 and "코인 이름" in sent[0] and all("조회 전용" in m for m in sent[1:]),
   f"G2a 명령 연결 (주문·매도 같은 말은 안내만): {got}")
e.tg.out = __import__("queue").Queue()
fake_get = fr.get
def no_zzz(path):  # 업비트는 없는 마켓이 섞이면 404로 거절한다
    if "ZZZ" in path: raise RuntimeError("GET 실패 404")
    return fake_get(path)
fr.get = no_zzz
for c in got + ["status", "today", "coin:ZZZ"]:
    e.tg_command(c)
outs = [e.tg.out.get_nowait()[1] for _ in range(e.tg.out.qsize())]
ok(len(outs) == len(got) + 3 and not any("오류" in m for m in outs) and any("ADA" in m and "지금 손익" in m for m in outs)
   and any("걸린 주문" in m for m in outs) and any("정상 작동" in m or "확인이 늦어" in m for m in outs) and "없는 코인" in outs[-1],
   "G2b 11가지 조회 글이 오류 없이 만들어짐 (없는 코인은 안내)")
fr.get = orig_get

# T12 장부 3판 바로잡기: 새 설정(2.5만·1.1배·5%)으로 시작했는데 2판 이전에 1.5배·3%로 도장된 사이클(ADA)만 새 설정으로,
#     예전 1회 금액(1만)으로 시작한 사이클(SOL)·이미 제대로 도장된 사이클(XLM)·끝난 사이클은 그대로
base = {"unit_krw": 25000, "profit_krw": 1250, "multiplier": 1.1, "drop_pct": 5.0, "wide_after": 15, "wide_drop_pct": 8.0}
cases = [
    ({**base, "cycle_v": 2, "state": {
        "ADA": {"qty": 75.3, "cost": 25012.5, "buys": 1, "ref": 332.0, "unit": 25000, "profit": 1250, "mult": 1.5, "drop": 3.0},
        "SOL": {"qty": 0.2, "cost": 32500.0, "buys": 3, "ref": 162000.0, "unit": 10000, "profit": 500, "mult": 1.5, "drop": 3.0},
        "XLM": {"qty": 80.0, "cost": 25012.5, "buys": 1, "ref": 313.0, "unit": 25000, "profit": 1250, "mult": 1.1, "drop": 5.0,
                "wide_after": 15, "wide_drop": 8.0},
        "BCH": {"qty": 0.0, "cost": 0.0, "buys": 0, "unit": 25000, "mult": 1.5, "drop": 3.0}}},
     {"ADA": (1.1, 5.0, 15), "SOL": (1.5, 3.0, None), "XLM": (1.1, 5.0, 15), "BCH": (1.5, 3.0, None)}),
    ({**base, "state": {  # 1판(도장 전)에서 바로 올라오는 경우도 같은 결과
        "ADA": {"qty": 75.3, "cost": 25012.5, "buys": 1, "ref": 332.0, "unit": 25000, "profit": 1250},
        "SOL": {"qty": 0.2, "cost": 32500.0, "buys": 3, "ref": 162000.0, "unit": 10000, "profit": 500}}},
     {"ADA": (1.1, 5.0, 15), "SOL": (1.5, 3.0, None)}),
]
for saved, want in cases:
    d = tempfile.mkdtemp(); core.CONFIG_PATH = os.path.join(d, "c.json")
    open(core.CONFIG_PATH, "w", encoding="utf-8").write(json.dumps({"grid": saved}))
    c = core.load_config()
    got = {k: (v.get("mult"), v.get("drop"), v.get("wide_after")) for k, v in c["grid"]["state"].items()}
    ok(got == want and c["grid"]["cycle_v"] == 3, f"T12a 장부 바로잡기 {got}")
    e12 = core.Engine(c, core.DB(os.path.join(d, "t.db")), queue.Queue())
    ada_st = c["grid"]["state"]["ADA"]
    ok(e12.grid_next_amount(ada_st) == 27500 and abs(e12.cycle_drop(ada_st) - 0.05) < 1e-12,
       f"T12b ADA 다음 물타기 {e12.grid_next_amount(ada_st):,}원 · {e12.cycle_drop(ada_st) * 100:g}% 아래 (2.75만 · 5%)")
    sol_st = c["grid"]["state"]["SOL"]
    ok(e12.grid_next_amount(sol_st) == 33750 and abs(e12.cycle_drop(sol_st) - 0.03) < 1e-12 and abs(e12.grid_be_qty(sol_st, 162000) * 162000 - 15000) < 1,
       f"T12c SOL(예전 사이클) 다음 물타기 {e12.grid_next_amount(sol_st):,}원 · 3%, 본전 매도 1.5만어치 그대로")
# T12d 바로잡은 뒤 다음 확인 때: 업비트에 걸려 있던 예전 물타기 주문(3% 아래·1.5배)을 취소하고 새 기준(5% 아래·1.1배)으로 다시 건다
e, ex, cfg = lmk(limit_add=True, multiplier=1.5, drop_pct=3.0)
lstep(e, ex, 340)
b0 = [o for o in ex.open.values() if o["side"] == "bid"]
st = e.grid_state("ADA"); st.update(mult=1.1, drop=5.0, wide_after=15, wide_drop=8.0)
lstep(e, ex, 338)
b = [o for o in ex.open.values() if o["side"] == "bid"]
ok(len(b0) == 1 and float(b0[0]["price"]) == 329 and len(b) == 1 and float(b[0]["price"]) == 323
   and abs(float(b[0]["volume"]) * 323 - 11000) < 5 and books_ok(e, ex),
   f"T12d 예전 주문 {b0[0]['price'] if b0 else '-'}원 취소 → {b[0]['price'] if b else '-'}원에 1.1만 다시 걸림")
fr.get = orig_get
