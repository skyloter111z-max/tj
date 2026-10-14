"""FibTrader 엔진: 설정, 기록 DB, 감시(가격·체결), 재계산 제안, 승인 후 실행.

화면(fibtrader.pyw)과는 queue로만 주고받는다. 표준 라이브러리만 사용.
이벤트: ("prices", {coin: price}), ("board", {coin: 현황}), ("alert", 제목, 내용),
        ("proposal", 제안), ("done", 실행 결과 문자열 목록), ("status", 문자열)
"""
import datetime
import json
import math
import os
import queue
import sqlite3
import threading
import time

import fib_check as fc
import fib_orders as fo
import fib_recalc as fr
import fib_telegram as ftg
import fib_voice as fv
import fib_ws as fws

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "fibtrader_config.json")
DB_PATH = os.path.join(HERE, "fibtrader.db")
KST = datetime.timezone(datetime.timedelta(hours=9))

DIP_POOL = ("SOL", "XLM", "DOGE", "ADA", "LINK", "BCH", "TRX", "AVAX", "HBAR", "DOT")  # 추천 목록: 대형 알트 10개
OLD_DIP_POOL = ["ADA", "TRX", "LINK", "BCH", "SOL", "DOGE", "XLM", "AVAX", "HBAR", "NEAR",
                "DOT", "SUI", "APT", "UNI", "ETC", "AAVE", "ATOM", "ARB", "POL", "ONDO"]
DEFAULTS = {
    "mode": "semi",                 # "alert"(알림만) / "semi"(반자동: 제안 → 승인 → 실행)
    "simulate": True,               # 모의 모드: 승인해도 실제 주문 안 함
    "buy_budget": fr.BUY_BUDGET,
    "buy_split": dict(fr.BUY_SPLIT),
    "near_pct": 1.0,
    "every_sec": 30,
    "max_order_krw": 3_000_000,     # 1건 최대 금액
    "max_orders_per_day": 20,
    "volume_tol_pct": 10,           # 매도 수량이 이 % 안에서만 다르면 그대로 둠 (매일 모으기로 보유량이 조금씩 늘어서)
    "dca_daily": {"BTC": 25_000, "ETH": 30_000, "XRP": 15_000},  # 업비트 코인 모으기 (매일 05시대)
    "progress": {c: {"sell_done": 0, "buy_done": 0} for c in fr.COINS},
    "ui": {"charts_open": [], "inv_charts_open": [], "near_highlight_pct": 5},  # 화면 상태 (차트 펼침, 근접 강조 %)
    "auto_apply_drift": False,      # 레벨이 유의적으로 바뀌면 자동으로 주문을 새 레벨로 바꿀지
    "stopped": None,                # 긴급 정지 상태 {"at", "mode", "grid"} (재개할 때 되돌릴 값). None이면 정상
    "levels": {},                   # 고정 플랜 레벨 {coin: {sells, buys, stop, at}}
    "grid": {                       # 자동매매(물타기): 피보나치와 별개, 승인 없이 자동 주문
        "enabled": True,
        "simulate": True,           # 켜 두면 가상으로만 사고판다
        "coins": ["BCH", "SOL", "DOGE"],
        "unit_krw": 10_000,         # 1회 매수 금액 (시작 매수)
        "multiplier": 1.0,          # 추가 매수 금액 배수: 1 = 매번 같은 금액, 2 = 마틴게일 (1만 → 2만 → 4만 …)
        "drop_pct": 5.0,            # 마지막 매수가(또는 절반 매도가) 대비 이만큼 떨어지면 추가 매수
        "profit_krw": 500,          # 사이클 수익(수수료 뺀 뒤)이 이 금액 이상이면 전량 매도
        "half_at_breakeven": True,  # 2회 이상 산 뒤 본전(수수료 포함)에 오면 일부 매도
        "btc_filter": True,         # 비트코인 약세 필터: 전날 일봉 종가가 최근 N일 평균 아래면 새 코인 시작 매수만 쉼 (물타기·익절은 계속)
        "btc_filter_days": 20,
        "reentry_pct": 0.0,         # 익절 뒤 재진입: 0 = 바로 다시 삼, 2 = 판 가격보다 2% 아래에 지정가 매수로 기다림
        "reentry_hours": 24,        # 그만큼 안 내려오면 이 시간 뒤 그냥 산다
        "wide_after": 15,           # 한 코인 몰림 방지: 이만큼 산 뒤부터는 하락 간격을 넓힌다 (0 = 안 씀)
        "wide_drop_pct": 8.0,       # 넓힌 하락 간격 % (9년 백테스트: 15회부터 8% → 수익 거의 그대로, 한 코인 최대 500만 → 243만)
        "be_sell": "prev",          # 본전에서 파는 양: "prev" = 직전 단계 금액어치(2회 1회 금액, 3회 1회×배수, 4회 1회×배수² …),
                                    # "unit" = 1회 금액(시작 매수 금액)어치, "half" = 보유의 절반
        "be_sell_v": 2,             # 설정 판: 1 → 2 때 "unit"을 "prev"로 한 번 바꿈
        "cycle_v": 3,               # 장부 판: 1 → 2 때 진행 중 사이클에 배수·하락 도장 (그전 사이클은 모두 1.5배·3%로 시작),
                                    # 2 → 3 때 지금 1회 금액으로 시작한 사이클은 지금 배수·하락으로 바로잡음
        "limit_tp": True,           # 실전: 매수 직후 익절가(본전 절반 포함)에 지정가 매도를 걸어 둔다. 추가 매수 때 취소 후 다시 건다
        "max_krw": 500_000,         # 코인별 최대 투입(보유 원가) 한도
        "total_max_krw": 1_500_000, # 자동매매 전체 원가 한도 (여러 코인이 같이 빠질 때)
        "reinvest": True,           # 수익 재투자: 실현 수익만큼 전체 한도를 늘린다 (내 돈은 설정한 한도까지만)
        "auto_exit_warning": True,  # 투자유의(상장폐지 심사) 지정되면 자동매매 보유분을 바로 청산
        # 업비트 "주의" 중 새 매수를 쉬는 종류 (상장폐지 사유 아님, 보유분은 그대로).
        # 가격 급등락·거래량 급등·입금량 급등·해외 가격 차이는 쉬지 않고, 소수 계정 거래 집중(작전성)만 쉰다.
        "caution_block": ["CONCENTRATION_OF_SMALL_ACCOUNTS"],
        "caution_v": 2,             # 설정 판: 1 → 2 때 예전 기본 목록을 새 기본으로 한 번 바꿈
        "cash_warn": 7_000_000,     # 현금 보호 (실전): 주문 가능 원화가 이 아래면 '주의' 알림 (코인 모으기 줄이기)
        "cash_floor_start": 4_000_000,  # 이 아래로 내려가면 새 코인 시작 매수 중지 (물타기는 계속) + 모으기 중지 알림
        "cash_floor_all": 2_000_000,    # 이 아래로 내려가면 자동매매 매수 전부 중지 (매도는 계속)
        "max_trades_per_day": 200,  # 하루 실전 거래가 이보다 많으면 버그·폭주로 보고 자동매매를 끈다
        "state": {},
        "dip": {                    # 하락 코인 자동 추가: 추천 목록(대형 알트) 안에서만, 잡코인 제외
            "enabled": False,
            "pool": list(DIP_POOL),
            "min_pct": 5.0,         # 전일 대비 이만큼 이상 떨어졌을 때
            "max_pct": 15.0,        # 이보다 더 빠진 건 악재일 수 있어 제외
            "min_vol_eok": 20,      # 24시간 거래대금(억 원) 이상 (대형이라도 조용한 날 DOT·TRX가 30~40억)
            "per_day": 2,           # 하루에 새로 추가할 최대 개수
            "max_coins": 15,        # 자동매매 목록 최대 코인 수 (이미 차 있으면 추가 안 함)
            "day": "", "added": 0,
        },
    },
}
GRID_BLOCKED = set(fr.COINS)  # 피보나치 코인은 자동매매 금지
FEE = 0.0005
MIN_SELL_KRW = 5_500  # 업비트 최소 주문 5,000원 + 수수료·가격 변동 여유


def tick_up(x, tick):
    """x 이상인 가장 가까운 호가 (익절가를 내림하면 목표 수익보다 덜 남으므로 항상 올림)."""
    return round(math.ceil(x / tick - 1e-9) * tick, 8)


def fmtp(v):
    """가격 표시 (지수 표기 금지). 1,000 이상은 정수, 그 아래는 가격대에 맞는 소수 자리."""
    if v is None:
        return "-"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    d = 1 if a >= 100 else 2 if a >= 10 else 3 if a >= 1 else 6
    t = f"{v:,.{d}f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def now():
    return datetime.datetime.now(KST)


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    saved = None
    for path in (CONFIG_PATH, CONFIG_PATH + ".bak"):  # 본 파일이 깨졌으면 백업으로
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    saved = json.load(f)
                break
            except (OSError, ValueError):
                continue
    if saved is not None:
        cfg.update({k: v for k, v in saved.items() if k in DEFAULTS and k != "grid"})
        cfg["grid"].update(saved.get("grid", {}))
        if saved.get("grid", {}).get("be_sell_v", 1) < 2:  # 예전 기본 "1회 금액어치" → "직전 단계 금액어치" (9년 백테스트로 결정)
            if cfg["grid"].get("be_sell") == "unit":
                cfg["grid"]["be_sell"] = "prev"
            cfg["grid"]["be_sell_v"] = 2
        if saved.get("grid", {}).get("caution_v", 1) < 2:  # 예전 기본(4종류 쉼) → 소수 계정 거래 집중만 쉼 (사용자 결정)
            cfg["grid"]["caution_block"] = list(DEFAULTS["grid"]["caution_block"])
            cfg["grid"]["caution_v"] = 2
        if saved.get("grid", {}).get("cycle_v", 1) < 2:  # 배수·하락 도장 전에 시작한 사이클 = 1.5배·3% 설정으로 시작한 것 → 끝까지 그 방식
            for st in cfg["grid"].get("state", {}).values():
                if st.get("qty", 0) > 0 and "mult" not in st:
                    st["mult"], st["drop"] = 1.5, 3.0
            cfg["grid"]["cycle_v"] = 2
        if saved.get("grid", {}).get("cycle_v", 1) < 3:
            # 2판 이전 때 1.5배·3%로 도장한 사이클 중, 1회 금액이 지금 설정과 같은 것은 지금 설정(1.1배·5% 등)으로 바꾼 뒤 시작한 사이클이다
            # (예: 2.5만으로 시작한 ADA가 1.5배·3%로 잘못 도장됨). 예전 1회 금액(1만·2만)으로 시작한 사이클은 그대로 둔다.
            g = cfg["grid"]
            cur = (max(1.0, float(g.get("multiplier", 1.0))), float(g["drop_pct"]))
            for st in g.get("state", {}).values():
                if (st.get("qty", 0) > 0 and st.get("unit") == g["unit_krw"] and (st.get("mult"), st.get("drop")) == (1.5, 3.0)
                        and "wide_after" not in st and cur != (1.5, 3.0)):
                    st["mult"], st["drop"] = cur
                    st["wide_after"], st["wide_drop"] = int(g.get("wide_after", 0)), float(g.get("wide_drop_pct", 0.0))
            g["cycle_v"] = 3
        cfg["grid"]["dip"] = dip = {**DEFAULTS["grid"]["dip"], **saved.get("grid", {}).get("dip", {})}
        if dip["pool"] == OLD_DIP_POOL:  # 예전 기본 20개를 안 고치고 썼으면 대형 10개로 바꾼다
            dip["pool"] = list(DIP_POOL)
            if dip["min_vol_eok"] == 50:
                dip["min_vol_eok"] = 20
        for c in fr.COINS:
            cfg["progress"].setdefault(c, {"sell_done": 0, "buy_done": 0})
    apply_config(cfg)
    return cfg


SAVE_LOCK = threading.RLock()  # 화면·엔진 두 스레드가 동시에 저장하지 않도록


def save_config(cfg):
    """임시 파일에 쓰고 한 번에 교체 → 저장 중 PC가 꺼져도 설정·자동매매 장부가 깨지지 않는다."""
    with SAVE_LOCK:
        data = json.dumps(cfg, ensure_ascii=False, indent=2)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(CONFIG_PATH):
            try:
                os.replace(CONFIG_PATH, CONFIG_PATH + ".bak")
            except OSError:
                pass
        os.replace(tmp, CONFIG_PATH)
        apply_config(cfg)


def apply_config(cfg):
    fr.BUY_BUDGET = cfg["buy_budget"]
    fr.BUY_SPLIT = dict(cfg["buy_split"])


class DB:
    def __init__(self, path=DB_PATH):
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (ts TEXT, kind TEXT, title TEXT, msg TEXT);
            CREATE TABLE IF NOT EXISTS fills (ts TEXT, market TEXT, side TEXT, price REAL, volume REAL, uuid TEXT);
            CREATE TABLE IF NOT EXISTS actions (ts TEXT, simulated INTEGER, kind TEXT, market TEXT,
                                                side TEXT, price REAL, volume REAL, result TEXT);
            CREATE TABLE IF NOT EXISTS grid_trades (ts TEXT, simulated INTEGER, coin TEXT, side TEXT,
                                                    price REAL, qty REAL, krw REAL, note TEXT);
            CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY, ts TEXT, reason TEXT,
                                                  todo TEXT, status TEXT);
        """)

    def add(self, table, *vals):
        with self.lock:
            self.conn.execute(f"INSERT INTO {table} VALUES ({','.join('?' * len(vals))})", vals)
            self.conn.commit()

    def run(self, sql, *args):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def query(self, sql, *args):
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def alert(self, kind, title, msg):
        self.add("alerts", now().strftime("%Y-%m-%d %H:%M:%S"), kind, title, msg)

    def actions_today(self):
        day = now().strftime("%Y-%m-%d")
        return self.query("SELECT COUNT(*) FROM actions WHERE ts LIKE ? AND simulated = 0 AND result = 'ok'",
                          day + "%")[0][0]


def candle_row(c):
    """업비트 캔들 → 차트용 (시가, 고가, 저가, 종가, KST 시각 'YYYY-MM-DDTHH:MM', 거래대금)."""
    return (c["opening_price"], c["high_price"], c["low_price"], c["trade_price"],
            c.get("candle_date_time_kst", "")[:16], c.get("candle_acc_trade_price", 0.0))


def build_journal(db, sim=None):
    """투자일지: 자동매매 거래 기록(grid_trades)을 처음부터 다시 따라가며 거래마다 수수료·실현 손익을 계산한다.
    엔진과 같은 방식(판 비율만큼 원가를 덜어냄)이라 매도 손익을 모두 더하면 엔진의 누적 실현과 같다.
    sim=None이면 전체, True면 모의만, False면 실전만. 모의와 실전 장부는 따로 따라간다."""
    rows = db.query("SELECT rowid, ts, simulated, coin, side, price, qty, krw, note FROM grid_trades ORDER BY rowid")
    book, out = {}, []
    for rid, ts, s_, coin, side, price, qty, krw, note in rows:
        s_ = bool(s_)
        if sim is not None and s_ != sim:
            continue
        b = book.setdefault((s_, coin), {"qty": 0.0, "cost": 0.0, "buys": 0})
        t = {"id": rid, "ts": ts[:19].replace("T", " "), "date": ts[:10], "month": ts[:7], "sim": s_, "coin": coin,
             "side": side, "price": price, "qty": qty, "krw": krw, "pnl": None, "base": None}
        if side == "bid":
            adopt = note == "기존 보유 편입"  # 주문 없이 장부에만 넣은 것 (매수 횟수로 세지 않음)
            more = note == "지정가 물타기 추가 체결"  # 같은 주문의 나머지 체결 (매수 횟수는 이미 셈)
            b["qty"] += qty
            b["cost"] += krw
            b["buys"] += 0 if (adopt or more) and b["buys"] else 1
            t.update(fee=max(krw - qty * price, 0.0),
                     kind="기존 보유 편입" if adopt else "시작 매수" if b["buys"] == 1 else f"물타기 {b['buys']}회",
                     avg=b["cost"] / b["qty"] if b["qty"] else None, hold_cost=b["cost"])
        else:
            t["fee"] = max(qty * price - krw, 0.0)
            if b["qty"] > 0:
                frac = min(qty / b["qty"], 1.0)
                base = b["cost"] * frac
                b["qty"] -= qty
                b["cost"] -= base
                part = note == "지정가 부분 체결"  # 주문이 아직 남아 있음 → 사이클 안 끝남
                full = frac >= 0.999 or (not part and b["qty"] * price < 5_000)
                if full:
                    b.update(qty=0.0, cost=0.0, buys=0)
                t.update(pnl=krw - base, base=base, kind="장부 정리 (추정)" if note == "장부 정리" else
                         "전량 매도" if full else "부분 체결" if part else "본전 매도", full=full, hold_cost=b["cost"])
            else:
                t.update(kind="매도 (장부 없음)", full=False, hold_cost=0.0)
        out.append(t)
    return out


def journal_summary(trades, key):
    """거래 목록을 key("date"/"month"/"coin")로 묶어 합계."""
    agg = {}
    for t in trades:
        a = agg.setdefault(t[key], {"key": t[key], "buys": 0, "buy_krw": 0.0, "sells": 0, "sell_krw": 0.0,
                                    "pnl": 0.0, "base": 0.0, "fee": 0.0, "cycles": 0})
        if t["side"] == "bid":
            a["buys"] += 1
            a["buy_krw"] += t["krw"]
        else:
            a["sells"] += 1
            a["sell_krw"] += t["krw"]
            a["pnl"] += t["pnl"] or 0.0
            a["base"] += t["base"] or 0.0
            a["cycles"] += 1 if t.get("full") else 0
        a["fee"] += t["fee"]
    return agg


CAUTION_NAMES = {"PRICE_FLUCTUATIONS": "가격 급등락", "TRADING_VOLUME_SOARING": "거래량 급등", "DEPOSIT_AMOUNT_SOARING": "입금량 급등",
                 "GLOBAL_PRICE_DIFFERENCES": "해외 가격 차이", "CONCENTRATION_OF_SMALL_ACCOUNTS": "소수 계정 거래 집중"}


def make_api():
    access, secret = os.environ.get("UPBIT_ACCESS_KEY"), os.environ.get("UPBIT_SECRET_KEY")
    return fo.Upbit(access, secret) if access and secret else None


def todo_key(todo):
    return json.dumps([(k, m, o["side"], o["price"], round(o["volume"], 6)) for k, m, o in todo])


class PriceFeed(threading.Thread):
    """화면용 시세: 업비트 웹소켓 실시간(끊기면 2초마다 REST로 대신), 10초마다 + 체결 직후 잔고(평단 포함),
    5분마다 + 체결 직후 체결 내역. 주문·알림 판단은 Engine이 한다 (자동매매 판단 주기는 그대로)."""

    TICK = 0.25        # 화면으로 보내는 최소 간격 (초당 최대 4번)
    REST_EVERY = 2.0   # 웹소켓이 안 될 때 REST 시세 간격
    ACC_EVERY = 10     # 잔고 조회 간격

    def __init__(self, engine, events, every=2.0):
        super().__init__(daemon=True)
        self.engine, self.events, self.every = engine, events, every
        self.stop_event = engine.stop_event
        self.last_hold = self.last_hist = self.last_rest = 0
        self.krw_markets = None
        self.held = []           # 원화마켓이 있는 보유 코인
        self.want_history = threading.Event()
        self.api_fail_since, self.api_alerted = None, False
        self.ws = None
        self.source = "REST"     # 지금 시세를 어디서 받는지 (화면 표시용)

    def ws_for(self, coins):
        """코인 목록이 바뀌면 웹소켓을 새 목록으로 다시 연다."""
        if self.ws and self.ws.coins == sorted(set(coins)) and self.ws.is_alive():
            return self.ws
        if self.ws:
            self.ws.stop()
        self.ws = fws.TickerStream(coins)
        self.ws.start()
        return self.ws

    def run(self):
        while not self.stop_event.is_set():
            try:
                if self.krw_markets is None:
                    self.krw_markets = {m["market"][4:] for m in fr.get("/market/all") if m["market"].startswith("KRW-")}
                coins = [c for c in dict.fromkeys(fr.COINS + self.engine.grid_tracked() + self.held) if c in self.krw_markets]
                ws = self.ws_for(coins)
                if ws.healthy():
                    snap = ws.take()
                    if snap:
                        self.events.put(("live", snap))
                    self.source = "실시간"
                elif time.time() - self.last_rest >= self.REST_EVERY:  # 웹소켓 연결 전·끊김 → REST로 대신
                    self.last_rest = time.time()
                    self.source = "REST"
                    ts = fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in coins))
                    self.events.put(("live", {t["market"][4:]: (t["trade_price"], t["signed_change_rate"] * 100,
                                                                t["signed_change_price"]) for t in ts}))
                api = self.engine.api
                poke = self.engine.poke.is_set()  # 자동매매·피보나치 체결 직후 → 잔고·체결 내역 바로 갱신
                if poke:
                    self.engine.poke.clear()
                    self.want_history.set()
                if api and (poke or time.time() - self.last_hold > self.ACC_EVERY):
                    self.last_hold = time.time()  # 실패해도 간격을 지켜 다시 (업비트를 두드리지 않게)
                    try:
                        acc = api.call("GET", "/accounts")
                    except Exception as e:
                        self.api_health(False, str(e))
                        raise
                    self.api_health(True)
                    hold = {a["currency"]: float(a["balance"]) + float(a["locked"]) for a in acc}
                    self.held = [a["currency"] for a in acc if a["currency"] in self.krw_markets
                                 and float(a["balance"]) + float(a["locked"]) > 0]
                    self.events.put(("hold", hold))
                    self.events.put(("accounts", [
                        {"currency": a["currency"], "qty": float(a["balance"]) + float(a["locked"]),
                         "locked": float(a["locked"]), "avg": float(a.get("avg_buy_price") or 0)} for a in acc]))
                if api and (time.time() - self.last_hist > 300 or self.want_history.is_set()):
                    self.want_history.clear()
                    self.last_hist = time.time()
                    try:
                        self.events.put(("history", api.closed_orders()))
                    except Exception as e:
                        self.events.put(("history_error", str(e)))
            except Exception:
                pass  # 다음 주기에 다시
            self.stop_event.wait(self.TICK)
        if self.ws:
            self.ws.stop()

    API_FAIL_ALERT_SEC = 300  # 업비트 개인 API(잔고 조회)가 이만큼 계속 실패하면 경고

    def api_health(self, ok, err=""):
        """업비트 개인 API 연결 감시. 5분 넘게 계속 실패하면 한 번 경고, 다시 되면 복구 알림.
        허용 IP가 바뀌면(공유기 재부팅 등) 모든 주문이 거절돼 익절 매도도 못 하므로 빨리 알아야 한다."""
        t = time.time()
        if ok:
            if self.api_alerted:
                mins = int((t - self.api_fail_since) // 60)
                self.engine.alert("grid", "업비트 API 연결 복구", f"약 {mins}분 동안 끊겼다가 다시 연결됐습니다. 자동매매가 이어서 동작합니다.")
            self.api_fail_since, self.api_alerted = None, False
            return
        if self.api_fail_since is None:
            self.api_fail_since = t
        if not self.api_alerted and t - self.api_fail_since >= self.API_FAIL_ALERT_SEC:
            self.api_alerted = True
            hint = ("허용 IP가 바뀌었을 수 있습니다. 업비트 > 마이페이지 > Open API 관리에서 지금 IP를 허용 IP로 다시 등록하세요."
                    if any(k in err for k in ("401", "no_authorization_ip", "invalid_access_key", "jwt"))
                    else "인터넷 연결이나 업비트 점검 여부를 확인하세요.")
            self.engine.alert("fail", "업비트 API 연결 끊김",
                              f"{int((t - self.api_fail_since) // 60)}분째 잔고 조회가 실패합니다. 이 동안 자동매매 주문(익절 포함)이 "
                              f"나가지 않습니다.\n{hint}\n오류: {err[:200]}")


class Engine(threading.Thread):
    def __init__(self, cfg, db, events):
        super().__init__(daemon=True)
        self.cfg, self.db, self.events = cfg, db, events
        self.api = make_api()
        self.stop_event = threading.Event()
        self.poke = threading.Event()  # 체결 직후 화면 잔고를 바로 갱신하라는 신호 (PriceFeed가 받음)
        self.commands = queue.Queue()
        self.tg = ftg.Telegram(lambda cmd: self.request("tg_command", cmd))  # 휴대폰 조회 전용 (토큰 없으면 꺼짐)
        self.levels = {}          # coin -> [(이름, 가격)]
        self.prices = {}
        self.alert_state = {}
        self.known_orders = None
        self.proposal = None
        self.dismissed = set()
        self.last_levels = self.last_board = 0
        self.grid_prev = {}       # 자동매매 급변 감지용 직전 가격
        self.grid_capped = {}     # 한도 알림 시각
        self.ticks = {}           # 코인별 호가 단위 캐시 {coin: (시각, 단위)}
        self.open_snap = None     # 이번 확인 주기의 미체결 주문 {uuid: 주문} (지정가 익절 체결 확인용)
        self.btc_bear = None      # 비트코인 약세 필터 상태 (약세 여부, 전날 종가, N일 평균) — 화면 표시용
        self.last_exec = 0
        for st in cfg["grid"]["state"].values():  # 이 기능 전에 시작한 사이클: 지금 설정(= 그 사이클을 시작한 설정)으로 도장
            if st.get("qty", 0) > 0 and "unit" not in st:
                st["unit"], st["profit"] = cfg["grid"]["unit_krw"], cfg["grid"]["profit_krw"]

    # ---------- 외부(화면)에서 부르는 것: 명령 큐에 넣고 엔진 스레드가 처리 ----------
    def request(self, cmd, *args):
        self.commands.put((cmd, args))

    def emit(self, *ev):
        if ev[0] == "done":  # 승인 주문 실행 결과 → 잔고 바로 갱신
            self.poke.set()
        self.events.put(ev)

    def alert(self, kind, title, msg, say=None, quiet=False):
        """say: 음성으로 읽을 것 (효과음 종류 "buy"/"tp"/"sell", 문장). 없으면 화면·트레이 알림만 (오류·정지는 화면 쪽에서 읽음).
        quiet: 주문 걸기 같은 정보 알림 → 기록만 남기고 팝업·소리·빨간 아이콘 없음 (기록 종류 "order", 알림 탭 '매매'에서만 보임)."""
        if quiet:
            kind = "order"
        self.db.alert(kind, title, msg)
        if kind in ("grid", "fill"):  # 자동매매 매매·피보나치 체결 → 잔고·체결 내역 바로 갱신
            self.poke.set()
        self.emit("alert", title, msg, kind, say, quiet)
        if not quiet:
            self.tg.notify(title, msg)

    # ---------- 레벨 (설정에 고정 저장, 체결·재계산 때만 바뀜) ----------
    def level_items(self, coin):
        lv = self.cfg["levels"][coin]
        return ([(f"{i + 1}차 매도", p) for i, p in enumerate(lv["sells"])]
                + [(f"{i + 1}차 매수", p) for i, p in enumerate(lv["buys"])]
                + [("매수 중단선", lv["stop"])])

    def load_levels(self):
        self.levels = {c: self.level_items(c) for c in fr.COINS}

    def recalc_levels(self, reason="재계산"):
        """지금 캔들로 다시 계산. 이미 체결된 단계의 가격은 그대로 두고 남은 단계만 새로 채운다."""
        old_all = self.cfg.get("levels") or {}
        new_all = {}
        for coin in fr.COINS:
            fresh = fo.compute_levels(coin)
            old = old_all.get(coin)
            pg = self.cfg["progress"][coin]
            sd, bd = (pg["sell_done"], pg["buy_done"]) if old else (0, 0)
            sells = old["sells"][:sd] if old else []
            floor = sells[-1] * 1.005 if sells else 0
            sells += [p for p in fresh["sells"] if p > floor][:len(fr.SELL_STEPS) - sd]
            buys = (old["buys"][:bd] if old else []) + fresh["buys"][bd:]
            new_all[coin] = {"sells": sells, "buys": buys, "stop": fresh["stop"], "at": now().strftime("%Y-%m-%d %H:%M")}
        self.cfg["levels"] = new_all
        save_config(self.cfg)
        self.load_levels()
        self.alert_state.clear()
        kind = "info" if reason.startswith("처음") else "levels"  # 첫 실행은 팝업 없이 기록만
        self.alert(kind, "레벨 재계산", reason + "\n" + "\n".join(
            f"{c}: 매도 {', '.join(f'{p:,.0f}' for p in v['sells'])} / 매수 {', '.join(f'{p:,.0f}' for p in v['buys'])}"
            for c, v in new_all.items()))

    def check_drift(self, manual=False):
        """고정 레벨과 지금 계산이 유의미하게(0.5% 넘게) 달라졌는지. 화면 알림판에 띄우고, 자동 반영이 켜져 있으면 반영.
        manual=True(버튼): 변화가 없어도 코인별 기준점과 레벨 비교표를 결과 창으로 보낸다."""
        drift, report = {}, {}
        for coin in fr.COINS:
            fresh, lv, pg = fo.compute_levels(coin), self.cfg["levels"][coin], self.cfg["progress"][coin]
            done_sells = lv["sells"][:pg["sell_done"]]
            floor = done_sells[-1] * 1.005 if done_sells else 0
            new_sells = [p for p in fresh["sells"] if p > floor]
            pairs = [(f"{i + 1}차 매수", a, b) for i, (a, b) in enumerate(zip(lv["buys"], fresh["buys"])) if i >= pg["buy_done"]]
            pairs += [(f"{pg['sell_done'] + i + 1}차 매도", a, b)
                      for i, (a, b) in enumerate(zip(lv["sells"][pg["sell_done"]:], new_sells))]
            changed = [(n, a, b) for n, a, b in pairs if abs(b / a - 1) > 0.005]
            if changed:
                drift[coin] = changed
            pv = fresh["pivots"]
            report[coin] = {"price": fresh["price"], "H_w": pv["H_w"], "H_w_date": pv["H_w_date"], "L": pv["L"],
                            "L_date": pv["L_date"], "H_d": pv["H_d"], "H_d_date": pv["H_d_date"],
                            "rows": sorted(pairs, key=lambda x: -x[1]) + [("매수 중단선", lv["stop"], fresh["stop"])]}
        self.last_levels = time.time()
        if manual:  # 결과 창 하나로 보여 주고 (알림 팝업은 따로 안 띄움), 변화가 있으면 알림판도 켠다
            self.emit("drift_report", report, drift)
            self._drift_sig = json.dumps(drift, sort_keys=True)
            self.emit("drift", drift)
            return
        sig = json.dumps(drift, sort_keys=True)
        if sig == getattr(self, "_drift_sig", None):
            return
        self._drift_sig = sig
        self.emit("drift", drift)
        if drift:
            lines = [f"{c} {n}: {a:,.0f} → {b:,.0f} ({(b / a - 1) * 100:+.1f}%)" for c, ch in drift.items() for n, a, b in ch]
            self.alert("drift", "피보나치 금액이 유의적으로 바뀌었습니다", "\n".join(lines))
            if self.cfg.get("auto_apply_drift"):
                self.apply_plan(recalc=True, reason="레벨 변경 자동 반영")

    def apply_plan(self, recalc=False, coins=None, reason="플랜대로 다시 걸기"):
        """(필요하면 재계산 후) 플랜과 다른 주문을 취소하고 플랜대로 다시 건다. 사용자가 누른 버튼이 곧 승인."""
        if recalc:
            self.recalc_levels(reason)
            self._drift_sig = None
            self.emit("drift", {})
        self.make_proposal(reason, force=True, coins=coins)
        if self.proposal and self.proposal["todo"]:
            self.execute(self.proposal["id"])
        else:
            self.emit("done", [f"{reason}: 바꿀 주문이 없습니다."])

    def load_candles(self, key, coin, unit, count):
        """차트용 캔들. unit: 분(int) 또는 'days'. 결과는 ("candles", key, [(시가, 고가, 저가, 종가, 시각, 거래대금)])."""
        cs = fc.candles(unit, coin, count)
        self.emit("candles", key, [candle_row(c) for c in cs])

    def cancel_orders(self, coins=None, uuids=None):
        """피보나치 코인의 미체결 주문 취소 (uuids를 주면 그 주문만). 사용자가 직접 누른 취소라 모의 모드와 상관없이 실제로 취소."""
        if not self.api:
            self.emit("done", ["API 키가 없어 취소할 수 없습니다."])
            return
        msgs = []
        for coin in coins or fr.COINS:
            for o in self.api.open_orders(f"KRW-{coin}"):
                if uuids and o["uuid"] not in uuids:
                    continue
                word = "매도" if o["side"] == "ask" else "매수"
                try:
                    self.api.cancel(o["uuid"])
                    res = "ok"
                except RuntimeError as e:
                    res = f"실패: {e}"
                self.db.add("actions", now().isoformat(), 0, "cancel", o["market"], o["side"], float(o["price"]),
                            float(o["remaining_volume"]), res)
                msgs.append(f"취소 {o['market']} {word} {float(o['price']):,.0f} × {float(o['remaining_volume']):g} → {res}")
        self.known_orders = None
        self.alert("cancel", "예약 주문 취소", "\n".join(msgs) or "취소할 주문이 없습니다.")
        self.emit("done", msgs or ["취소할 주문이 없습니다."])
        self.check_fills()

    def refresh_board(self):
        board = {"_levels_at": min((v.get("at", "") for v in self.cfg["levels"].values()), default="")}
        for coin in fr.COINS:
            h4, h1 = fc.candles(240, coin, 60), fc.candles(60, coin, 60)
            ind = []
            for label, cs in (("4h", h4), ("1h", h1)):
                closes = [c["trade_price"] for c in cs]
                m = fc.ma(closes, 20)
                slope = (m - fc.ma(closes[:-3], 20)) / m * 100
                ind.append((label, "위" if closes[-1] > m else "아래", (closes[-1] / m - 1) * 100, slope, fc.rsi(closes)))
            board[coin] = {"price": self.prices.get(coin), "levels": self.levels.get(coin, []),
                           "trend": f"4h {fc.trend(h4)}\n1h {fc.trend(h1)}", "ind": ind,
                           "candles": [candle_row(c) for c in h4[-48:]],
                           "change24": fc.pct(h1[-1]["trade_price"], h1[-24]["opening_price"])}
        dca = sum(self.cfg["dca_daily"].values())
        board["_dca"] = dca
        if self.api:
            board["_krw_free"] = self.api.holdings()[1]
        if self.api and dca:
            board["_cash"] = f"주문 가능 현금 {board['_krw_free']:,.0f}원 · 모으기 하루 {dca:,}원 → 약 {board['_krw_free'] / dca:,.0f}일분"
        elif dca:
            board["_cash"] = f"모으기 하루 {dca:,}원 (한 달 약 {dca * 30:,}원)"
        self.last_board = time.time()
        self.emit("board", board)

    # ---------- 감시 ----------
    def check_prices(self):
        coins = fr.COINS + [c for c in self.grid_tracked() if c not in fr.COINS]
        tickers = fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in coins))
        near = self.cfg["near_pct"]
        for t in tickers:
            coin, price = t["market"][4:], t["trade_price"]
            prev = self.prices.get(coin, price)
            self.prices[coin] = price
            if coin not in fr.COINS:
                continue
            for name, lvl in self.levels.get(coin, []):
                key = (coin, name)
                dist = (price / lvl - 1) * 100
                if (prev - lvl) * (price - lvl) <= 0 and prev != price and self.alert_state.get(key) != "hit":
                    self.alert_state[key] = "hit"
                    self.alert("hit", f"{coin} {name} 도달", f"{coin} {price:,.0f}원이 {name} {lvl:,.0f}원에 닿았습니다.")
                elif abs(dist) <= near and key not in self.alert_state:
                    self.alert_state[key] = "near"
                    self.alert("near", f"{coin} {name} 근접",
                               f"{coin} {price:,.0f}원, {name} {lvl:,.0f}원까지 {(lvl / price - 1) * 100:+.2f}%")
                elif abs(dist) > near * 2 and key in self.alert_state:
                    del self.alert_state[key]
        self.emit("prices", dict(self.prices))
        g = self.cfg["grid"]
        if self.api and not g["simulate"]:  # 결과 확인 중 주문은 자동매매가 꺼졌거나 목록에서 빠져도 끝까지 확정
            tp_coins = [c for c in self.grid_tracked() if self.grid_state(c).get("tp") or self.grid_state(c).get("bid")]
            self.open_snap = None
            if tp_coins:
                try:
                    rows = self.api.open_all()
                    self.open_snap = {o["uuid"]: o for o in rows} if len(rows) < 100 else None
                except Exception:
                    self.open_snap = None
            for coin in self.grid_tracked():
                idle = not g["enabled"] or coin not in self.grid_coins()
                if self.grid_state(coin).get("pending") and idle:
                    try:
                        self.grid_resolve_pending(coin)
                    except Exception as e:
                        self.alert("fail", f"{coin} 주문 확인 오류", str(e))
                elif coin in tp_coins and (idle or not self.grid_limit_on() or not self.grid_bid_on()):
                    try:
                        st_ = self.grid_state(coin)
                        if st_.get("bid") and (idle or not self.grid_bid_on()):
                            self.grid_bid_cancel(coin)  # 자동매매를 껐거나 목록에서 뺀 코인은 새로 사지 않는다 (체결분은 반영)
                        if st_.get("tp"):
                            if self.grid_limit_on():
                                self.grid_tp_check(coin)  # 걸어 둔 익절은 꺼져 있어도 체결되므로 장부에 반영
                            else:  # 지정가 익절을 끈 경우: 걸어 둔 주문을 취소하고 시장가 방식으로
                                self.grid_tp_cancel(coin)
                    except Exception as e:
                        self.alert("fail", f"{coin} 지정가 체결 확인 오류", str(e))
        if self.cfg["grid"]["enabled"]:
            try:
                self.grid_check_warnings()
            except Exception:
                pass  # 조회 실패 시 다음 시간에 다시
            try:
                self.grid_dip()
            except Exception as e:  # 조회 실패 시 5분 뒤 다시
                print("dip", e)
            if time.time() - getattr(self, "_cash_ts", 0) > 300:  # 현금 단계 5분마다
                self._cash_ts = time.time()
                try:
                    self.cash_stage_check()
                except Exception as e:
                    print("cash", e)
            for coin in self.grid_coins():
                if coin in self.prices:
                    try:
                        self.grid_step(coin, self.prices[coin])
                    except fo.UnknownResult as e:
                        self.alert("fail", f"{coin} 주문 결과 확인 중", f"{e}\n다음 확인 때 업비트에서 조회해 반영합니다 (중복 주문 안 함).")
                    except Exception as e:  # 현금 부족·IP 변경·네트워크 등: 10분 쉬고 재시도 (30초마다 반복 실패 방지)
                        if " 429" in str(e):  # 업비트 조회 한도(초당 횟수) 초과: 정지·알림 없이 다음 확인 때 다시
                            continue
                        self.grid_state(coin)["pause_until"] = time.time() + 600
                        save_config(self.cfg)
                        self.alert("fail", f"{coin} 자동매매 오류 · 10분 정지", str(e))
        self.emit("grid", self.grid_view())

    def step_of(self, coin, side, price):
        """체결된 주문 가격이 고정 레벨의 몇 번째 단계인지 (0부터). 못 찾으면 None."""
        lv = self.cfg["levels"][coin]
        for i, p in enumerate(lv["sells"] if side == "ask" else lv["buys"]):
            if abs(price / p - 1) < 0.005:
                return i
        return None

    def check_fills(self):
        if not self.api:
            return
        current = {}
        for coin in fr.COINS:
            for o in self.api.open_orders(f"KRW-{coin}"):
                current[o["uuid"]] = o
        if self.known_orders is not None:
            filled = []
            for uid, o in self.known_orders.items():
                if uid in current:
                    continue
                detail = self.api.call("GET", "/order", {"uuid": uid})
                if float(detail.get("executed_volume") or 0) <= 0:
                    continue  # 취소된 주문
                coin, side, price = o["market"][4:], o["side"], float(o["price"])
                vol = float(detail["executed_volume"])
                self.db.add("fills", now().isoformat(), o["market"], side, price, vol, uid)
                word = "매도" if side == "ask" else "매수"
                step = self.step_of(coin, side, price)
                if step is not None:
                    key = "sell_done" if side == "ask" else "buy_done"
                    self.cfg["progress"][coin][key] = max(self.cfg["progress"][coin][key], step + 1)
                    save_config(self.cfg)
                label = f" ({step + 1}차)" if step is not None else ""
                self.alert("fill", f"{coin} {word} 체결{label}", f"{coin} {word} {price:,.0f}원 × {vol:g} 체결",
                           say=("sell" if side == "ask" else "buy", f"{fv.kname(coin)} {f'{step + 1}차 ' if step is not None else ''}{word} 체결"))
                filled.append(f"{coin} {word}{label} {price:,.0f}")
            if filled:
                self.recalc_levels("체결 후 재계산: " + ", ".join(filled))
                self.make_proposal("체결: " + ", ".join(filled), force=True)
        self.known_orders = current
        by_coin = {c: [] for c in fr.COINS}
        for o in current.values():
            by_coin.setdefault(o["market"][4:], []).append(
                {"uuid": o["uuid"], "side": o["side"], "price": float(o["price"]), "volume": float(o["remaining_volume"])})
        self.emit("open_orders", by_coin)

    # ---------- 제안·실행 ----------
    def make_proposal(self, reason, force=False, coins=None):
        if self.cfg["mode"] != "semi" and not force:
            return
        holdings = self.api.holdings()[0] if self.api else fr.HOLDINGS
        rows, todo = fo.diff(self.api, holdings, coins=coins, replace=True, progress=self.cfg["progress"],
                             tol=self.cfg["volume_tol_pct"] / 100, levels=self.cfg["levels"])
        key = todo_key(todo)
        if not todo:
            self.proposal = None
            self.emit("proposal", {"reason": reason, "rows": rows, "todo": [], "id": None})
            return
        if not force and key in self.dismissed:
            return
        cur = self.db.run("INSERT INTO proposals (ts, reason, todo, status) VALUES (?,?,?,?)",
                          now().isoformat(), reason, key, "pending")
        self.proposal = {"id": cur.lastrowid, "reason": reason, "rows": rows, "todo": todo, "key": key}
        self.emit("proposal", self.proposal)
        if self.cfg["mode"] == "semi":
            self.alert("proposal", "주문 변경 제안", f"{reason}\n변경 {len(todo)}건. 대시보드 '주문' 탭에서 승인하세요.")

    def execute(self, proposal_id, selected=None):
        """selected: 실행할 todo 번호 목록 (주문 탭에서 체크한 행). None이면 전부."""
        p = self.proposal
        if not p or p["id"] != proposal_id:
            self.emit("done", ["제안이 바뀌었습니다. 다시 확인하세요."])
            return
        if self.cfg.get("stopped"):
            self.emit("done", ["긴급 정지 중이라 실행하지 않았습니다. 상단의 [재개]를 누른 뒤 다시 승인하세요."])
            return
        pick = set(range(len(p["todo"]))) if selected is None else set(selected)
        chosen = [t for i, t in enumerate(p["todo"]) if i in pick]
        if not chosen:
            self.emit("done", ["선택한 주문이 없습니다."])
            return
        sim = self.cfg["simulate"] or not self.api
        if not sim:
            # 승인과 실행 사이에 체결·취소가 있었을 수 있다 → 지금 다시 비교해서 같을 때만 실행
            holdings, krw_free = self.api.holdings()
            coins = sorted({m[4:] for _, m, _ in p["todo"]})
            rows, todo = fo.diff(self.api, holdings, coins=coins, replace=True, progress=self.cfg["progress"],
                                 tol=self.cfg["volume_tol_pct"] / 100, levels=self.cfg["levels"])
            if todo_key(todo) != todo_key(p["todo"]):
                self.proposal = None
                self.emit("done", ["승인 사이에 업비트 주문 상태가 바뀌어 실행하지 않았습니다. 새 제안을 확인하세요."])
                self.make_proposal("상태 변경 후 다시 비교", force=True)
                return
            need = sum(o["price"] * o["volume"] for k, _, o in chosen if k == "place" and o["side"] == "bid")
            freed = sum(o["price"] * o["volume"] for k, _, o in chosen if k == "cancel" and o["side"] == "bid")
            if need > krw_free + freed + 1:
                self.emit("done", [f"현금 부족으로 실행하지 않았습니다: 새 매수 주문 {need:,.0f}원 / 주문 가능 {krw_free + freed:,.0f}원"])
                self.alert("fail", "주문 실행 중단 · 현금 부족", f"필요 {need:,.0f}원, 가능 {krw_free + freed:,.0f}원")
                return
        results, count, failed = [], self.db.actions_today(), []
        for kind, market, o in chosen:
            krw = o["price"] * o["volume"]
            tag = "[모의] " if sim else ""
            if kind == "place" and krw > self.cfg["max_order_krw"]:
                res = f"건너뜀: 1건 한도 {self.cfg['max_order_krw']:,}원 초과 ({krw:,.0f}원)"
            elif not sim and count >= self.cfg["max_orders_per_day"]:
                res = f"건너뜀: 하루 주문 한도 {self.cfg['max_orders_per_day']}건 도달"
            else:
                try:
                    if not sim:
                        if kind == "cancel":
                            self.api.cancel(o["uuid"])
                        else:
                            self.api.place(market, o["side"], o["volume"], o["price"],
                                           identifier=f"ff-{market}-{o['side']}-{o['price']:.0f}-{int(time.time() * 1000)}")
                        count += 1
                    res = "ok"
                except fo.UnknownResult as e:
                    res = f"결과 불명확: {e}"
                    failed.append(res)
                    word = "취소" if kind == "cancel" else "주문"
                    results.append(f"{word} {market} {o['price']:,.0f} → {res}")
                    self.db.add("actions", now().isoformat(), 0, kind, market, o["side"], o["price"], o["volume"], res)
                    results.append("⚠ 결과가 불명확해 나머지는 실행하지 않았습니다. 업비트 앱에서 미체결 주문을 확인한 뒤 '플랜과 다시 비교'를 누르세요.")
                    break
                except RuntimeError as e:
                    res = f"실패: {e}"
                    failed.append(res)
            word = "취소" if kind == "cancel" else "주문"
            side = "매도" if o["side"] == "ask" else "매수"
            self.db.add("actions", now().isoformat(), int(sim), kind, market, o["side"], o["price"], o["volume"], res)
            results.append(f"{tag}{word} {market} {side} {o['price']:,.0f} × {o['volume']:g} → {res}")
        self.db.run("UPDATE proposals SET status=? WHERE id=?", "simulated" if sim else "executed", p["id"])
        self.proposal = None
        self.known_orders = None  # 방금 취소한 주문을 체결로 오인하지 않도록 다시 읽는다
        self.last_exec = time.time()
        self.emit("done", results)
        self.emit("proposal", None)  # 실행한 제안은 화면·배지에서 내린다 (실전은 아래에서 다시 비교)
        if failed:
            self.alert("fail", f"주문 실행 중 {len(failed)}건 실패", "\n".join(failed[:5]))
        if not sim:
            time.sleep(2)  # 업비트 반영 대기 후 확인 (바로 조회하면 방금 건 주문이 안 보일 수 있음)
            self.make_proposal("실행 후 확인")

    def dismiss(self, proposal_id):
        if self.proposal and self.proposal["id"] == proposal_id:
            self.dismissed.add(self.proposal["key"])
            self.db.run("UPDATE proposals SET status='dismissed' WHERE id=?", proposal_id)
            self.proposal = None
            self.emit("proposal", None)

    # ---------- 자동매매 (물타기 그리드) ----------
    def grid_coins(self):
        """자동매매 대상(코인 칸에 적힌 것). 이 코인만 사고판다."""
        return [c for c in self.cfg["grid"]["coins"] if c not in GRID_BLOCKED]

    def grid_tracked(self):
        """화면·한도 계산에 넣을 코인: 대상 코인 + 목록에서 뺐지만 자동매매로 산 수량(또는 확인 중 주문)이 남은 코인."""
        extra = [c for c, st in self.cfg["grid"]["state"].items()
                 if c not in GRID_BLOCKED and (st.get("qty", 0) > 0 or st.get("pending"))]
        return list(dict.fromkeys(self.grid_coins() + extra))

    def grid_state(self, coin):
        return self.cfg["grid"]["state"].setdefault(coin, {
            "qty": 0.0, "cost": 0.0, "buys": 0, "ref": None, "halved": False,
            "realized": 0.0, "cycles": 0, "profit_total": 0.0})

    def grid_trade(self, coin, side, price, amount):
        """side=bid: amount는 원화, side=ask: amount는 수량.
        반환 (수량, 원화[매수는 수수료 포함 지출, 매도는 수수료 뺀 수입], 체결 평균가, 모의 여부).
        실전 주문은 고유 번호(identifier)를 먼저 저장하고 보낸다. 결과가 불명확하면 pending으로 남겨
        다음 확인 때 그 번호로 조회해서 확정한다 → 같은 주문이 두 번 나가지 않는다."""
        g = self.cfg["grid"]
        st = self.grid_state(coin)
        sim = g["simulate"] or not self.api
        market = f"KRW-{coin}"
        if sim:
            qty, krw = (amount * (1 - FEE) / price, amount) if side == "bid" else (amount, amount * price * (1 - FEE))
        else:
            if side == "ask":  # 주문 가능 잔고보다 많이 팔지 않는다 (기존 보유분을 직접 팔았거나 주문에 묶였을 때)
                acc = {a["currency"]: float(a["balance"]) for a in self.api.call("GET", "/accounts")}
                avail = acc.get(coin, 0.0)
                if avail < amount * 0.999:
                    self.alert("grid", f"{coin} 잔고 부족", f"팔 수량 {amount:g}개 중 주문 가능 {avail:g}개만 매도합니다.")
                    amount = avail
                if amount * price < 5_000:
                    raise RuntimeError(f"{coin} 매도 가능 금액이 5,000원 미만이라 매도하지 못했습니다.")
            ident = f"fg-{coin}-{side}-{int(time.time() * 1000)}"
            st["pending"] = {"id": ident, "side": side, "ts": time.time()}
            save_config(self.cfg)  # 보내기 전에 기록 (PC가 꺼져도 다음에 확인 가능)
            try:
                if side == "bid":
                    self.api.market_buy(market, amount, identifier=ident)
                else:
                    self.api.market_sell(market, amount, identifier=ident)
            except fo.UnknownResult:
                raise  # pending 유지 → 다음 확인 때 조회
            except RuntimeError:
                st.pop("pending", None)  # 업비트가 거절 = 주문 안 들어감
                save_config(self.cfg)
                raise
            vol, funds, fee = self.api.filled(identifier=ident)
            st.pop("pending", None)
            qty, krw = (vol, funds + fee) if side == "bid" else (vol, funds - fee)
            price = funds / vol if vol else price
        self.db.add("grid_trades", now().isoformat(), int(sim), coin, side, price, qty, krw, "")
        st["last_trade_ts"] = time.time()
        st["fee_total"] = st.get("fee_total", 0.0) + abs(qty * price - krw)  # 실제로 낸 수수료 누적 (화면 표시용)
        return qty, krw, price, sim

    def grid_resolve_pending(self, coin):
        """결과를 몰랐던 주문을 업비트에서 조회해 장부에 반영. 끝나면 True, 아직 모르면 False."""
        st = self.grid_state(coin)
        pend = st["pending"]
        o = self.api.get_order(identifier=pend["id"])
        if o is None:  # 업비트에 없음 = 주문이 안 들어감
            if time.time() - pend["ts"] < 60:
                return False  # 막 보낸 주문은 조회가 늦을 수 있어 1분은 기다린다
            st.pop("pending")
            self.alert("grid", f"{coin} 주문 확인", "결과를 몰랐던 주문이 업비트에 없어 취소된 것으로 처리했습니다.")
            save_config(self.cfg)
            return True
        res = fo.Upbit.order_result(o)
        if res is None:
            return False
        vol, funds, fee = res
        st.pop("pending")
        st["fee_total"] = st.get("fee_total", 0.0) + fee
        if vol > 0:
            px = funds / vol
            if pend["side"] == "bid":
                st.update(qty=st["qty"] + vol, cost=st["cost"] + funds + fee, buys=st["buys"] + 1, ref=px, halved=False)
                if st["buys"] == 1:
                    self.grid_stamp(st)
            else:
                frac = min(vol / st["qty"], 1) if st["qty"] else 1
                st["realized"] += (funds - fee) - st["cost"] * frac
                # 남은 게 있으면 절반 매도였던 것 → halved 표시 (안 하면 본전 위에서 절반을 한 번 더 판다)
                st.update(qty=max(st["qty"] - vol, 0.0), cost=st["cost"] * (1 - frac), ref=px, halved=True)
                if st["qty"] * px < 5_000:  # 사실상 다 팔림 → 사이클 종료
                    st["profit_total"] += st["realized"]
                    st["cycles"] += 1
                    st.update(qty=0.0, cost=0.0, buys=0, ref=None, halved=False, realized=0.0)
            self.db.add("grid_trades", now().isoformat(), 0, coin, pend["side"], px, vol,
                        funds + fee if pend["side"] == "bid" else funds - fee, "사후 확인")
            self.alert("grid", f"{coin} 주문 사후 확인", f"결과를 몰랐던 {'매수' if pend['side'] == 'bid' else '매도'} "
                       f"{vol:g}개 @ {fmtp(px)} 체결을 장부에 반영했습니다.")
        save_config(self.cfg)
        return True

    def grid_guard(self, coin, price):
        """매매 전 안전 점검. 매매하면 안 되면 이유 문자열, 괜찮으면 None."""
        g, st = self.cfg["grid"], self.grid_state(coin)
        t = time.time()
        prev = self.grid_prev.get(coin)
        self.grid_prev[coin] = price  # 정지 중에도 직전 가격은 계속 갱신
        if st.get("pause_until", 0) > t:
            return "일시정지"
        if st.get("blocked"):
            return "투자유의 지정"
        if prev and abs(price / prev - 1) > 0.15:  # 30초 사이 15% 넘게 움직임 = 시세 오류나 급변
            st["pause_until"] = t + 1800
            self.alert("fail", f"{coin} 급변 감지 · 30분 정지", f"{fmtp(prev)} → {fmtp(price)} ({(price / prev - 1) * 100:+.1f}%)")
            return "급변"
        if t - st.get("last_trade_ts", 0) < 60:
            return "직전 매매 1분 이내"
        if not (g["simulate"] or not self.api):
            day = now().strftime("%Y-%m-%d")
            n = self.db.query("SELECT COUNT(*) FROM grid_trades WHERE ts LIKE ? AND simulated = 0", day + "%")[0][0]
            if n >= g["max_trades_per_day"]:
                g["enabled"] = False
                save_config(self.cfg)
                self.alert("stop", "자동매매 자동 정지", f"오늘 실전 거래 {n}건으로 하루 한도 {g['max_trades_per_day']}건에 도달했습니다. "
                           "이상이 없는지 확인한 뒤 다시 켜세요.")
                return "하루 한도"
        return None

    def grid_check_warnings(self, force=False):
        """업비트 지정 확인 (10분마다).
        · 투자유의(상장폐지 심사 대상): 새 매수 중지 + 설정이 켜져 있으면 자동매매 보유분을 바로 시장가 청산
        · 주의(급등락·거래량·입금량 등 일시 경고): 새 매수만 중지하고 보유분은 그대로 (풀리면 재개)
        · 원화마켓에서 사라짐: 매매 불가 → 알림만"""
        if not force and time.time() - getattr(self, "_warn_ts", 0) < 600:
            return
        self._warn_ts = time.time()
        g = self.cfg["grid"]
        info = {m["market"][4:]: m for m in fr.get("/market/all?isDetails=true") if m["market"].startswith("KRW-")}
        for coin in self.grid_tracked():
            m = info.get(coin)
            ev = (m or {}).get("market_event") or {}
            gone = m is None
            designated = not gone and (m.get("market_warning") == "CAUTION" or bool(ev.get("warning")))
            watch = g.get("caution_block", DEFAULTS["grid"]["caution_block"])
            caution = [k for k, v in (ev.get("caution") or {}).items() if v and k in watch]
            st = self.grid_state(coin)
            block = gone or designated or bool(caution)
            if designated and st["qty"] > 0 and not st.get("pending") and g.get("auto_exit_warning", True):
                self.alert("fail", f"{coin} 투자유의 지정 → 자동 청산", "상장폐지 심사 대상(투자유의)으로 지정되어 자동매매 보유분을 "
                           "시장가로 전량 매도합니다. 기존 보유분은 건드리지 않습니다.")
                if coin not in self.prices:
                    t = fr.get(f"/ticker?markets=KRW-{coin}")
                    self.prices[coin] = t[0]["trade_price"]
                self.grid_liquidate(coin)  # 파는 것은 막지 않는다 (blocked여도 청산)
            kind = "gone" if gone else "warning" if designated else "caution" if caution else None
            if block and (not st.get("blocked") or st.get("blocked_why") != kind):
                st["blocked"], st["blocked_why"] = True, kind
                why = ("원화마켓에서 사라짐 (매매 불가)" if gone else "투자유의 지정 (상장폐지 심사 대상)" if designated
                       else "업비트 주의: " + ", ".join(CAUTION_NAMES.get(k, k) for k in caution))
                self.alert("fail", f"{coin} 자동매매 새 매수 중지", f"{why}. " + ("" if designated else "보유분은 그대로 두고 익절 주문도 유지합니다."))
            elif not block and st.get("blocked"):
                st["blocked"] = False
                st.pop("blocked_why", None)
                self.alert("grid", f"{coin} 자동매매 재개", "업비트 지정이 풀렸거나 새 매수를 쉬지 않는 종류(입금량 급증 등)입니다.")

    def grid_dip(self, force=False):
        """자동매매 감시 (5분마다): 추천 목록 중 자동매매 목록에 없는 코인을 지켜보다가, 전일 대비 min~max% 떨어지고
        거래대금이 충분하면 자동매매 목록에 넣는다 → 다음 확인 때 1회 금액으로 시작 매수. 투자유의·경고 코인은 제외."""
        g = self.cfg["grid"]
        d = g["dip"]
        if not d.get("enabled") or (not force and time.time() - getattr(self, "_dip_ts", 0) < 300):
            return []
        self._dip_ts = time.time()
        today = now().strftime("%Y-%m-%d")
        if d.get("day") != today:
            d["day"], d["added"] = today, 0
        pool = [c for c in d["pool"] if c not in g["coins"] and c not in GRID_BLOCKED
                and not self.grid_state(c).get("qty") and not self.grid_state(c).get("pending")]
        info = {m["market"][4:]: m for m in fr.get("/market/all?isDetails=true") if m["market"].startswith("KRW-")}
        pool = [c for c in pool if c in info]
        watch, picks = [], []
        for t in fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in pool)) if pool else []:
            coin, chg, vol = t["market"][4:], t["signed_change_rate"] * 100, t["acc_trade_price_24h"]
            m = info[coin]
            ev = m.get("market_event") or {}
            if m.get("market_warning") == "CAUTION" or ev.get("warning") or any((ev.get("caution") or {}).values()):
                note = "투자유의"
            elif vol < d["min_vol_eok"] * 1e8:
                note = "거래 적음"
            elif chg < -d["max_pct"]:
                note = "급락 제외"
            elif chg <= -d["min_pct"]:
                note = "조건 충족"
                picks.append((chg, coin, vol))
            else:
                note = ""
            watch.append((coin, chg, note))
        self.emit("dip_watch", sorted(watch, key=lambda w: w[1]), time.strftime("%H:%M"))
        room = min(d["per_day"] - d["added"], d["max_coins"] - len(g["coins"]))
        added = []
        for chg, coin, vol in sorted(picks)[:max(room, 0)]:
            g["coins"] = g["coins"] + [coin]
            st = self.grid_state(coin)
            st["auto"] = True
            d["added"] += 1
            added.append(coin)
            self.alert("grid", f"{coin} 감시 → 자동매매 시작 ({chg:+.1f}%)",
                       f"전일 대비 {chg:+.1f}% · 거래대금 {vol / 1e8:,.0f}억 → 자동매매 목록에 넣고 {g['unit_krw']:,}원 시작 매수합니다. "
                       f"(오늘 {d['added']}/{d['per_day']}개)")
        if picks and room <= 0:
            self.grid_cap_alert("dip", "감시 조건을 충족한 코인이 있지만 하루 추가 한도나 목록 최대 개수에 도달해 시작하지 않았습니다: "
                                       + ", ".join(c for _, c, _ in sorted(picks)))
        if added:
            save_config(self.cfg)
            self.prices.update({t["market"][4:]: t["trade_price"]
                                for t in fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in added))})
        return added

    def grid_step(self, coin, price):
        g, st = self.cfg["grid"], self.grid_state(coin)
        if st.get("pending") and self.api and not g["simulate"]:
            self.grid_resolve_pending(coin)
            return  # 이번 주기는 확정만 하고 매매는 다음 주기에
        limit = self.grid_limit_on()
        use_bid = self.grid_bid_on() and st.get("bid_fail_until", 0) <= time.time()  # 물타기도 지정가로 미리 걸기
        if limit and st.get("tp"):
            self.grid_tp_check(coin)
        if limit and st.get("bid") and self.grid_bid_check(coin) and st["qty"] > 0:
            self.grid_tp_sync(coin)  # 물타기 체결 → 익절 주문을 새 수량·새 평단으로 바로 다시 건다
            if use_bid and not st.get("blocked") and st.get("pause_until", 0) <= time.time():
                self.grid_bid_sync(coin)  # 다음 단계 물타기 주문도 바로
        if st.get("bid") and st["qty"] <= 0 and limit and st["bid"].get("kind") != "start":  # 익절로 사이클이 끝남 → 걸어 둔 물타기 매수 취소
            self.grid_bid_cancel(coin)
        why = self.grid_guard(coin, price)
        if why:
            if st.get("bid") and why in ("급변", "투자유의 지정", "하루 한도") and limit:  # 이때만 걸어 둔 매수 취소
                self.grid_bid_cancel(coin)  # (오류로 잠깐 정지·1분 대기 중에는 업비트에 걸린 주문을 그대로 둔다)
            return
        unit = g["unit_krw"]
        tag = "[모의] " if g["simulate"] or not self.api else ""
        # 목록에서 뺀 보유분 + 다른 코인에 걸어 둔 지정가 매수(아직 안 산 금액)까지 한도에 포함
        total_cost = sum(self.grid_state(c)["cost"] for c in self.grid_tracked()) + self.grid_bid_reserved()
        if st["qty"] <= 0 and self.grid_btc_bear():  # 비트코인 약세: 새 사이클 시작만 쉰다 (들고 있는 코인은 그대로)
            if st.get("bid") and st["bid"].get("kind") == "start":
                self.grid_bid_cancel(coin)  # 재진입 대기 주문도 쉼
            return
        if st["qty"] <= 0 and self.grid_reentry_wait(coin, price, use_bid):
            return save_config(self.cfg)  # 판 가격보다 N% 아래로 내려오길 기다리는 중
        if st["qty"] <= 0:  # 새 사이클 시작
            if total_cost + unit > self.grid_total_cap():
                return self.grid_cap_alert("total", f"자동매매 전체 원가 {total_cost:,.0f}원 · 전체 한도 {self.grid_total_cap():,.0f}원")
            if not self.grid_cash_ok("start", unit):
                return
            qty, krw, px, _ = self.grid_trade(coin, "bid", price, unit)
            st.update(qty=qty, cost=krw, buys=1, ref=px, halved=False, realized=0.0)
            self.grid_stamp(st)
            self.alert("grid", f"{tag}{coin} 시작 매수", f"{fmtp(px)}원에 {krw:,.0f}원 매수 (1회)",
                       say=None if tag else ("buy", f"{fv.kname(coin)}, {fv.won(krw)} 샀습니다"))
            if limit:
                save_config(self.cfg)
                self.grid_tp_sync(coin)  # 익절가에 지정가 매도
            if use_bid:
                self.grid_bid_sync(coin)  # 다음 물타기 가격에 지정가 매수
        else:
            if limit:
                self.grid_tp_sync(coin)  # 걸려 있어야 할 주문이 없거나 장부와 다르면 다시 건다
            if use_bid:
                self.grid_bid_sync(coin)
            orders = limit and bool(st.get("tp"))  # 지정가가 걸려 있으면 익절·절반 매도는 업비트가 한다
            value = st["qty"] * price * (1 - FEE)
            pnl = st["realized"] + value - st["cost"]
            avg = st["cost"] / st["qty"]
            breakeven = avg / (1 - FEE)
            if not orders and pnl >= self.cycle_profit(st):
                before = st["qty"]
                qty, krw, px, _ = self.grid_trade(coin, "ask", price, before)
                pnl = st["realized"] + krw - st["cost"] * min(qty / before, 1)  # 잔고 부족으로 덜 팔았으면 그만큼 원가만
                self.grid_close_cycle(coin, pnl, px, "전량 매도")
            elif not orders and (g["half_at_breakeven"] and st["buys"] >= 2 and not st["halved"] and price >= breakeven
                  and self.grid_be_qty(st, price) > 0):  # 팔 양과 남는 양 모두 업비트 최소 주문 이상일 때만
                before = st["qty"]
                qty, krw, px, _ = self.grid_trade(coin, "ask", price, self.grid_be_qty(st, price))
                frac = min(qty / before, 1)  # 실제로 판 비율만큼만 원가를 덜어낸다
                st["realized"] += krw - st["cost"] * frac
                st.update(qty=before - qty, cost=st["cost"] * (1 - frac), halved=True, ref=px)
                self.alert("grid", f"{tag}{coin} 본전 매도", f"{fmtp(px)}원에 {qty:g}개 매도 ({krw:,.0f}원)",
                           say=None if tag else ("sell", f"{fv.kname(coin)}, 본전 매도"))
            elif not use_bid and price <= st["ref"] * (1 - self.cycle_drop(st)):
                unit = self.grid_next_amount(st)  # 마틴게일이면 직전 매수의 배수
                if st["cost"] + unit > g["max_krw"]:
                    return self.grid_cap_alert(coin, f"{coin} 원가 {st['cost']:,.0f}원 + 다음 매수 {unit:,.0f}원 · 코인 한도 {g['max_krw']:,}원")
                if total_cost + unit > self.grid_total_cap():
                    return self.grid_cap_alert("total", f"자동매매 전체 원가 {total_cost:,.0f}원 · 전체 한도 {self.grid_total_cap():,.0f}원")
                if not self.grid_cash_ok("add", unit):
                    return
                if orders and not self.grid_tp_cancel(coin):  # 기존 익절 주문 먼저 취소 (그 사이 체결분은 장부에 반영)
                    return  # 취소 확인이 안 되면 이번엔 사지 않는다
                if st["qty"] <= 0:  # 취소 직전에 익절이 체결돼 사이클이 끝남
                    save_config(self.cfg)
                    return
                qty, krw, px, _ = self.grid_trade(coin, "bid", price, unit)
                st.update(qty=st["qty"] + qty, cost=st["cost"] + krw, buys=st["buys"] + 1, ref=px, halved=False)
                self.alert("grid", f"{tag}{coin} 물타기 {st['buys']}회",
                           f"{fmtp(px)}원에 {krw:,.0f}원 매수 · 평단 {fmtp(st['cost'] / st['qty'])} · 원가 {st['cost']:,.0f}원",
                           say=None if tag else ("buy", f"{fv.kname(coin)} 물타기, {fv.won(krw)} 샀습니다"))
                if limit:
                    save_config(self.cfg)
                    self.grid_tp_sync(coin)  # 새 수량·새 평단으로 익절가 다시 계산해서 건다
            else:
                return
        save_config(self.cfg)

    # ---------- 지정가 익절 (실전) ----------
    # 매수 직후 익절가에 지정가 매도를 걸어 둔다 → 가격이 닿는 순간 업비트가 바로 판다 (PC가 꺼져 있어도).
    # 2회 이상 샀으면 절반은 본전에, 나머지는 사이클 수익이 목표가 되는 가격에 따로 건다.
    # 추가 매수 전에는 기존 주문을 모두 취소하고(취소 전에 체결된 만큼은 장부에 반영), 산 뒤 새 수량·새 가격으로 다시 건다.
    # st["tp"] = [{"id": 고유번호, "uuid", "kind": "half"/"full", "price", "vol", "ev": 반영한 체결 수량, "ef": 반영한 체결 금액,
    #              "efee": 반영한 수수료, "ts"}]
    def grid_limit_on(self):
        g = self.cfg["grid"]
        return bool(self.api) and not g["simulate"] and g.get("limit_tp", True)

    def grid_tick(self, coin):
        """호가 단위 (10분 캐시). 자동매매 코인 전부를 한 번에 조회한다 (코인마다 따로 물으면 업비트 초당 조회 한도에 걸림).
        조회가 실패하면 예전 값을 그대로 쓰고 1분 뒤 다시, 예전 값도 없으면 호가창의 가장 작은 가격 차이."""
        c = self.ticks.get(coin)
        if c and time.time() - c[0] < 600:
            return c[1]
        coins = list(dict.fromkeys([coin] + self.grid_tracked()))
        try:
            rows = fr.get("/orderbook/instruments?markets=" + ",".join(f"KRW-{x}" for x in coins))
            t0 = time.time()
            for r in rows:
                v = float(r.get("tick_size") or 0)
                if v > 0:
                    self.ticks[r["market"][4:]] = (t0, v)
        except Exception:
            if c:
                self.ticks[coin] = (time.time() - 540, c[1])
                return c[1]
        c = self.ticks.get(coin)
        if c and time.time() - c[0] < 600:
            return c[1]
        units = fr.get(f"/orderbook?markets=KRW-{coin}")[0]["orderbook_units"]
        ps = sorted({u["ask_price"] for u in units} | {u["bid_price"] for u in units})
        t = min(b - a for a, b in zip(ps, ps[1:]))
        if not t > 0:
            raise RuntimeError(f"{coin} 호가 단위를 알 수 없습니다.")
        self.ticks[coin] = (time.time(), t)
        return t

    def grid_tp_plan(self, coin, st):
        """지금 장부로 걸어야 할 지정가 매도 [(kind, 가격, 수량)]. 5,000원 미만이라 못 걸면 []."""
        g, q = self.cfg["grid"], st["qty"]
        if q <= 0:
            return []
        tick = self.grid_tick(coin)
        profit = self.cycle_profit(st)
        if g["half_at_breakeven"] and st["buys"] >= 2 and not st["halved"]:
            be = tick_up(st["cost"] / q / (1 - FEE), tick)  # 본전 (산 수수료 + 팔 수수료 포함)
            half = self.grid_be_qty(st, be)  # 본전에서 팔 양 (1회 금액어치 또는 절반)
            rest = q - half
            realized = st["realized"] + half * be * (1 - FEE) - st["cost"] * half / q
            tp = tick_up((profit + st["cost"] * rest / q - realized) / (rest * (1 - FEE)), tick)
            if half > 0 and rest * tp >= MIN_SELL_KRW:
                return [("half", be, half), ("full", tp, rest)]
        tp = tick_up((profit + st["cost"] - st["realized"]) / (q * (1 - FEE)), tick)
        return [("full", tp, q)] if q * tp >= 5_000 else []

    def grid_tp_same(self, coin, want, have):
        """걸린 주문이 원하는 주문과 같으면 True. 가격은 원하는 가격 이상 1호가 이내면 그대로 둔다 (불필요한 취소 방지)."""
        if len(want) != len(have) or any(h.get("uuid") is None for h in have):
            return False
        tick = self.grid_tick(coin)
        for (kind, price, vol), h in zip(sorted(want, key=lambda w: w[1]), sorted(have, key=lambda h: h["price"])):
            left = h["vol"] - h["ev"]
            if kind != h["kind"] or not (price - 1e-9 <= h["price"] <= price + tick + 1e-9) or abs(left - vol) > max(vol * 1e-6, 1e-8):
                return False
        return True

    def grid_tp_fetch(self, rec):
        """주문 조회. 미체결 목록(이번 주기에 한 번 받은 것)에 있고 체결이 그대로면 조회를 생략한다."""
        o = (self.open_snap or {}).get(rec.get("uuid"))
        if o is not None and abs(float(o.get("executed_volume") or 0) - rec["ev"]) < 1e-12:
            return o
        return self.api.get_order(uuid=rec["uuid"]) if rec.get("uuid") else self.api.get_order(identifier=rec["id"])

    def grid_tp_apply(self, coin, rec, o):
        """주문 o의 새 체결분을 매도로 장부에 반영. 반영한 수량 반환."""
        st = self.grid_state(coin)
        vol = float(o.get("executed_volume") or 0)
        dv = vol - rec["ev"]
        if dv <= 1e-12:
            return 0.0
        funds = sum(float(t["funds"]) for t in o.get("trades") or [])
        fee = float(o.get("paid_fee") or 0)
        df, dfee = funds - rec["ef"], fee - rec["efee"]
        if df <= 0:  # 체결 내역이 비어 온 경우: 지정가(이상에 팔림)로 보수적으로 계산
            df, dfee = dv * rec["price"], dv * rec["price"] * FEE
            funds, fee = rec["ef"] + df, rec["efee"] + dfee
        rec.update(ev=vol, ef=funds, efee=fee)
        before = st["qty"]
        frac = min(dv / before, 1.0) if before > 0 else 1.0
        krw = df - dfee
        st["realized"] += krw - st["cost"] * frac
        st.update(qty=max(before - dv, 0.0), cost=st["cost"] * (1 - frac))
        st["fee_total"] = st.get("fee_total", 0.0) + dfee
        st["last_trade_ts"] = time.time()
        part = o.get("state") == "wait"
        self.db.add("grid_trades", now().isoformat(), 0, coin, "ask", df / dv, dv, krw, "지정가 부분 체결" if part else "지정가 매도")
        return dv

    def grid_tp_close_if_done(self, coin, px):
        """걸린 주문이 없고 남은 수량이 5,000원 미만이면 사이클 종료 (익절)."""
        st = self.grid_state(coin)
        if st.get("tp") or st["qty"] * px >= 5_000 or st["buys"] == 0:
            return False
        self.grid_close_cycle(coin, st["realized"], px, "지정가 전량 매도")
        return True

    def grid_close_cycle(self, coin, pnl, px, how):
        g, st = self.cfg["grid"], self.grid_state(coin)
        tag = "[모의] " if g["simulate"] or not self.api else ""
        st["profit_total"] += pnl
        st["cycles"] += 1
        self.alert("grid", f"{tag}{coin} 익절 {pnl:+,.0f}원",
                   f"{fmtp(px)}원에 {how} · {st['buys']}회 매수 사이클 · 누적 {st['profit_total']:,.0f}원",
                   say=None if tag else ("tp", f"{fv.kname(coin)} 익절, {fv.won(pnl)} 벌었습니다"))
        st.update(qty=0.0, cost=0.0, buys=0, ref=None, halved=False, realized=0.0)
        if g.get("reentry_pct", 0) > 0:  # 재진입 대기: 판 가격 기록 (이보다 N% 아래에서 다시 시작)
            st["last_exit"] = {"price": px, "ts": time.time()}
        if st.get("auto"):  # 하락으로 자동 추가된 코인은 익절로 사이클이 끝나면 목록에서 뺀다 (자리 비움)
            st["auto"] = False
            g["coins"] = [c for c in g["coins"] if c != coin]
            self.alert("grid", f"{tag}{coin} 자동 추가 코인 정리", "익절로 사이클이 끝나 자동매매 목록에서 뺐습니다.", quiet=True)

    def grid_tp_check(self, coin):
        """걸어 둔 지정가 매도의 체결을 장부에 반영. 바뀐 게 있으면 True."""
        st = self.grid_state(coin)
        changed, px = False, None
        for rec in list(st.get("tp") or []):
            o = self.grid_tp_fetch(rec)
            if o is None:
                if rec.get("uuid") is None and time.time() - rec["ts"] > 60:  # 보냈는지 몰랐던 주문이 업비트에 없음 = 안 들어감
                    st["tp"].remove(rec)
                    changed = True
                continue
            if rec.get("uuid") is None:
                rec["uuid"] = o["uuid"]
                changed = True
            dv = self.grid_tp_apply(coin, rec, o)
            if dv:
                changed, px = True, rec["ef"] / rec["ev"]
            if o.get("state") in ("done", "cancel"):
                st["tp"].remove(rec)
                changed = True
                if rec["kind"] == "half" and o["state"] == "done":
                    st.update(halved=True, ref=rec["ef"] / rec["ev"])
                    self.alert("grid", f"{coin} 본전 매도 (지정가)", say=("sell", f"{fv.kname(coin)}, 본전 매도"), msg=
                               f"{fmtp(rec['ef'] / rec['ev'])}원에 {rec['ev']:g}개 매도 ({rec['ef'] - rec['efee']:,.0f}원) · 나머지는 익절가에 걸려 있음")
                elif o["state"] == "cancel" and not rec.get("mine"):
                    self.alert("grid", f"{coin} 지정가 매도 취소됨",
                               "업비트에서 익절 주문이 취소된 것을 확인했습니다. 자동매매가 켜져 있으면 장부 수량으로 다시 겁니다.")
        if changed:
            if px:
                self.grid_tp_close_if_done(coin, px)
            save_config(self.cfg)
        return changed

    def grid_tp_cancel(self, coin):
        """걸어 둔 지정가 매도를 모두 취소하고, 취소 전에 체결된 만큼은 장부에 반영한다.
        모두 끝난 것(취소·체결)을 확인하면 True. 확인 못 하면 False (그 코인은 이번에 매수·재주문하지 않는다)."""
        st = self.grid_state(coin)
        px = None
        for rec in list(st.get("tp") or []):
            rec["mine"] = True
            o = self.grid_tp_fetch(rec)
            if o is None:
                if rec.get("uuid") is None and time.time() - rec["ts"] > 60:
                    st["tp"].remove(rec)
                    continue
                save_config(self.cfg)
                return False
            rec["uuid"] = o["uuid"]
            if o.get("state") == "wait":
                try:
                    self.api.cancel(o["uuid"])
                except RuntimeError:
                    pass  # 그 사이 체결됐을 수 있음 → 아래 조회로 확인
                for _ in range(6):
                    time.sleep(0.3)
                    o = self.api.get_order(uuid=rec["uuid"])
                    if o is None or o.get("state") != "wait":
                        break
            if o is None or o.get("state") == "wait":
                save_config(self.cfg)
                return False
            if self.grid_tp_apply(coin, rec, o):
                px = rec["ef"] / rec["ev"]
                if rec["kind"] == "half" and o["state"] == "done":
                    st.update(halved=True, ref=px)
            st["tp"].remove(rec)
        st.pop("tp", None)
        if px:
            self.grid_tp_close_if_done(coin, px)
        save_config(self.cfg)
        return True

    def grid_tp_sync(self, coin):
        """장부에 맞는 지정가 매도가 걸려 있게 한다. 다르면 기존 주문 취소 → 체결분 반영 → 새 수량·새 가격으로 다시 건다."""
        st = self.grid_state(coin)
        if st.get("tp_fail_until", 0) > time.time():
            return
        want = self.grid_tp_plan(coin, st)
        if self.grid_tp_same(coin, want, st.get("tp") or []):
            return
        if st.get("tp"):
            if not self.grid_tp_cancel(coin):
                return
            want = self.grid_tp_plan(coin, st)  # 취소 전에 체결된 게 있으면 장부가 바뀌었으므로 다시 계산
        if not want:
            return
        acc = {a["currency"]: float(a["balance"]) for a in self.api.call("GET", "/accounts")}
        avail = acc.get(coin, 0.0)
        total = sum(v for _, _, v in want)
        if avail < total * 0.999:  # 기존 보유분을 직접 팔았거나 다른 주문에 묶였을 때: 가진 만큼만
            self.grid_cap_alert(f"tp_{coin}", f"{coin} 익절 주문 수량 {total:g}개 중 주문 가능 {avail:g}개만 겁니다.")
            kind, price, vol = want[-1]
            want[-1] = (kind, price, vol - (total - avail))
            want = [w for w in want if w[2] * w[1] >= 5_000]
        st["tp"] = []
        for i, (kind, price, vol) in enumerate(sorted(want, key=lambda w: w[1])):
            rec = {"id": f"fg-{coin}-tp-{int(time.time() * 1000)}-{i}", "uuid": None, "kind": kind, "price": price,
                   "vol": int(vol * 1e8) / 1e8, "ev": 0.0, "ef": 0.0, "efee": 0.0, "ts": time.time()}
            st["tp"].append(rec)
            save_config(self.cfg)  # 보내기 전에 기록 (결과를 몰라도 다음에 고유 번호로 조회)
            try:
                try:
                    o = self.api.place(f"KRW-{coin}", "ask", rec["vol"], price, identifier=rec["id"])
                except fo.UnknownResult:
                    raise  # 들어갔는지 모름 → 다시 보내면 중복 주문 위험 (아래에서 uuid 없이 남겨 두고 조회)
                except RuntimeError as e:
                    if "insufficient" in str(e) or "under_min" in str(e):
                        raise
                    # 목표가가 다음 가격대(호가 단위가 더 큼)로 넘어간 경우: 10호가 단위로 올려 한 번 더
                    price = tick_up(price, self.grid_tick(coin) * 10)
                    rec.update(price=price, id=rec["id"] + "r")
                    save_config(self.cfg)
                    o = self.api.place(f"KRW-{coin}", "ask", rec["vol"], price, identifier=rec["id"])
            except fo.UnknownResult:
                continue  # uuid 없이 남겨 두면 다음 확인 때 고유 번호로 조회
            except RuntimeError as e:
                st["tp"].remove(rec)
                st["tp_fail_until"] = time.time() + 600
                save_config(self.cfg)
                self.alert("fail", f"{coin} 지정가 익절 주문 실패 · 10분간 시장가 방식",
                           f"{e}\n그동안은 예전처럼 익절가에 닿으면 시장가로 팝니다.")
                return
            rec["uuid"] = o["uuid"]
        save_config(self.cfg)
        if st["tp"]:
            txt = " · ".join(f"{'절반' if r['kind'] == 'half' else '전량'} {fmtp(r['price'])}원 {r['vol']:g}개" for r in st["tp"])
            self.alert("grid", f"{coin} 지정가 익절 걸어 둠", txt, quiet=True)

    # ---------- 지정가 물타기 (실전) ----------
    # 다음 추가 매수가(마지막 매수가 −하락%)에 다음 매수 금액만큼 지정가 매수를 미리 걸어 둔다 → 가격이 닿는 순간 체결.
    # 체결되면 장부에 넣고 익절 주문은 새 수량·새 평단으로 다시 건다(grid_tp_sync). 다음 단계 매수 주문도 새로 건다.
    # 자동매매를 끄거나, 목록에서 빼거나, 투자유의·급변·한도·현금 보호에 걸리면 걸어 둔 매수 주문은 취소한다.
    # st["bid"] = {"id", "uuid", "price", "amount", "vol", "ev", "ef", "efee", "ts", "counted": 매수 횟수에 셌는지}
    def grid_bid_on(self):
        return self.grid_limit_on() and self.cfg["grid"].get("limit_add", True)

    def grid_bid_reserved(self, skip=None):
        """다른 코인에 걸어 둔 지정가 매수 중 아직 안 산 금액 (전체 한도에서 미리 뺀다)."""
        out = 0.0
        for c in self.grid_tracked():
            b = self.grid_state(c).get("bid")
            if b and c != skip:
                out += b["amount"] * max(1 - b["ev"] / b["vol"], 0.0) if b["vol"] else b["amount"]
        return out

    def grid_bid_apply(self, coin, rec, o):
        """매수 주문 o의 새 체결분을 장부에 반영. 반영한 수량 반환."""
        st = self.grid_state(coin)
        vol = float(o.get("executed_volume") or 0)
        dv = vol - rec["ev"]
        if dv <= 1e-12:
            return 0.0
        funds = sum(float(t["funds"]) for t in o.get("trades") or [])
        fee = float(o.get("paid_fee") or 0)
        df, dfee = funds - rec["ef"], fee - rec["efee"]
        if df <= 0:  # 체결 내역이 비어 온 경우: 지정가(이하에 사짐)로 보수적으로 계산
            df, dfee = dv * rec["price"], dv * rec["price"] * FEE
            funds, fee = rec["ef"] + df, rec["efee"] + dfee
        rec.update(ev=vol, ef=funds, efee=fee)
        px = df / dv
        if st["qty"] <= 0 and st["buys"] == 0:  # 재진입 매수 또는 익절로 사이클이 끝난 뒤 체결됨 → 새 사이클의 첫 매수
            st.update(buys=1, ref=px, halved=False, realized=0.0)
            st.pop("last_exit", None)
            self.grid_stamp(st)
            rec["counted"] = True
        elif not rec.get("counted"):
            st.update(buys=st["buys"] + 1, ref=px, halved=False)
            rec["counted"] = True
        st.update(qty=st["qty"] + dv, cost=st["cost"] + df + dfee)
        st["fee_total"] = st.get("fee_total", 0.0) + dfee
        st["last_trade_ts"] = rec["fill_ts"] = time.time()
        first = rec.get("rows", 0) == 0
        rec["rows"] = rec.get("rows", 0) + 1
        self.db.add("grid_trades", now().isoformat(), 0, coin, "bid", px, dv, df + dfee, "지정가 물타기" if first else "지정가 물타기 추가 체결")
        start = rec.get("kind") == "start"
        self.alert("grid", f"{coin} 재진입 매수 (지정가)" if start else f"{coin} 물타기 {st['buys']}회 (지정가)",
                   f"{fmtp(px)}원에 {df + dfee:,.0f}원 매수 · 평단 {fmtp(st['cost'] / st['qty'])} · 원가 {st['cost']:,.0f}원"
                   + ("" if o.get("state") != "wait" else " · 일부 체결"),
                   say=("buy", f"{fv.kname(coin)}{', 다시' if start else ' 물타기,'} {fv.won(df + dfee)} 샀습니다") if first else None)
        return dv

    def grid_bid_check(self, coin):
        """걸어 둔 지정가 매수의 체결을 장부에 반영. 바뀐 게 있으면 True."""
        st = self.grid_state(coin)
        rec = st.get("bid")
        if not rec:
            return False
        o = self.grid_tp_fetch(rec)
        changed = False
        if o is None:
            if rec.get("uuid") is None and time.time() - rec["ts"] > 60:  # 보냈는지 몰랐던 주문이 업비트에 없음 = 안 들어감
                st.pop("bid")
                changed = True
        else:
            if rec.get("uuid") is None:
                rec["uuid"] = o["uuid"]
                changed = True
            if self.grid_bid_apply(coin, rec, o):
                changed = True
            if o.get("state") in ("done", "cancel"):
                st.pop("bid")
                changed = True
                if o["state"] == "cancel" and not rec.get("mine") and not rec["ev"]:
                    self.alert("grid", f"{coin} 지정가 매수 취소됨",
                               "업비트에서 물타기 매수 주문이 취소된 것을 확인했습니다. 자동매매가 켜져 있으면 다시 겁니다.")
        if changed:
            save_config(self.cfg)
        return changed

    def grid_bid_cancel(self, coin):
        """걸어 둔 지정가 매수를 취소하고, 취소 전에 체결된 만큼은 장부에 반영한다. 끝난 것을 확인하면 True."""
        st = self.grid_state(coin)
        rec = st.get("bid")
        if not rec:
            return True
        rec["mine"] = True
        o = self.grid_tp_fetch(rec)
        if o is None:
            if rec.get("uuid") is None and time.time() - rec["ts"] > 60:
                st.pop("bid")
                save_config(self.cfg)
                return True
            save_config(self.cfg)
            return False
        rec["uuid"] = o["uuid"]
        if o.get("state") == "wait":
            try:
                self.api.cancel(o["uuid"])
            except RuntimeError:
                pass  # 그 사이 체결됐을 수 있음 → 아래 조회로 확인
            for _ in range(6):
                time.sleep(0.3)
                o = self.api.get_order(uuid=rec["uuid"])
                if o is None or o.get("state") != "wait":
                    break
        if o is None or o.get("state") == "wait":
            save_config(self.cfg)
            return False
        self.grid_bid_apply(coin, rec, o)
        st.pop("bid", None)
        save_config(self.cfg)
        return True

    def grid_reentry_wait(self, coin, price, use_bid):
        """익절 뒤 재진입 대기 (설정 reentry_pct > 0). 기다려야 하면 True.
        판 가격 × (1 − N%) 이하로 내려오면 산다: 실전 지정가면 그 가격에 매수 주문을 걸어 두고(체결되면 새 사이클),
        아니면 그 가격 이하가 보일 때 시장가로. reentry_hours 동안 안 내려오면 걸어 둔 주문을 취소하고 바로 산다."""
        g, st = self.cfg["grid"], self.grid_state(coin)
        le, r = st.get("last_exit"), g.get("reentry_pct", 0) / 100
        if not le or r <= 0:
            st.pop("last_exit", None)
            return False
        target = le["price"] * (1 - r)
        expired = time.time() - le["ts"] > g.get("reentry_hours", 24) * 3600
        if not expired and price > target:
            if use_bid:
                self.grid_bid_sync(coin)  # 재진입 가격에 지정가 매수
            return True
        if st.get("bid") and not self.grid_bid_cancel(coin):  # 시간 초과 → 걸어 둔 재진입 주문 취소 후 바로 산다
            return True
        st.pop("last_exit", None)
        if st["qty"] > 0:  # 취소 직전에 사짐 → 이미 새 사이클
            return True
        if expired:
            self.alert("grid", f"{coin} 재진입 대기 끝", f"{g.get('reentry_hours', 24)}시간 동안 {g['reentry_pct']:g}% 아래로 안 내려와 지금 가격에 다시 삽니다.",
                       quiet=True)
        return False

    def grid_bid_want(self, coin):
        """지금 걸어야 할 지정가 매수 (가격, 금액). 걸면 안 되면 (None, 이유)."""
        g, st = self.cfg["grid"], self.grid_state(coin)
        if st["qty"] <= 0:  # 재진입 대기: 판 가격보다 N% 아래에 1회 금액
            le, r = st.get("last_exit"), g.get("reentry_pct", 0) / 100
            if not le or r <= 0:
                return None, ""
            amount = g["unit_krw"]
            total = sum(self.grid_state(c)["cost"] for c in self.grid_tracked()) + self.grid_bid_reserved(skip=coin)
            if total + amount > self.grid_total_cap():
                return None, f"자동매매 전체 원가+걸어 둔 매수 {total:,.0f}원 · 전체 한도 {self.grid_total_cap():,.0f}원"
            tick = self.grid_tick(coin)
            return (round(math.floor(le["price"] * (1 - r) / tick + 1e-9) * tick, 8), amount), ""
        if not st.get("ref"):
            return None, ""
        amount = self.grid_next_amount(st)
        if st["cost"] + amount > g["max_krw"]:
            return None, f"{coin} 원가 {st['cost']:,.0f}원 + 다음 매수 {amount:,.0f}원 · 코인 한도 {g['max_krw']:,}원"
        total = sum(self.grid_state(c)["cost"] for c in self.grid_tracked()) + self.grid_bid_reserved(skip=coin)
        if total + amount > self.grid_total_cap():
            return None, f"자동매매 전체 원가+걸어 둔 매수 {total:,.0f}원 · 전체 한도 {self.grid_total_cap():,.0f}원"
        tick = self.grid_tick(coin)
        price = round(math.floor(st["ref"] * (1 - self.cycle_drop(st)) / tick + 1e-9) * tick, 8)
        return (price, amount), ""

    def grid_bid_sync(self, coin):
        """장부에 맞는 지정가 매수가 걸려 있게 한다. 가격·금액이 다르면 취소(체결분 반영) 후 다시 건다."""
        st = self.grid_state(coin)
        if st.get("bid_fail_until", 0) > time.time():
            return
        rec = st.get("bid")
        if rec and rec["ev"] > 0 and time.time() - rec.get("fill_ts", 0) < 60:
            return  # 일부 체결 중: 1분은 두고 본다 (나머지도 체결될 수 있음)
        want, why = self.grid_bid_want(coin)
        if rec and rec.get("uuid") and want and not rec["ev"] and abs(rec["price"] - want[0]) < 1e-9 and abs(rec["amount"] - want[1]) < 1:
            return
        if rec:
            ev0 = rec["ev"]
            if not self.grid_bid_cancel(coin):
                return
            if rec["ev"] > ev0:
                return  # 취소하는 사이 더 체결됨 → 장부가 바뀜 → 익절 다시 건 뒤 다음 확인 때 새로
        if want is None:
            if why:
                self.grid_cap_alert(f"bid_{coin}", why)
            return
        price, amount = want
        kind = "start" if st["qty"] <= 0 else "add"
        if not self.grid_cash_ok(kind, amount):
            return
        vol = int(amount / price * 1e8) / 1e8
        rec = {"id": f"fg-{coin}-{kind}-{int(time.time() * 1000)}", "uuid": None, "kind": kind, "price": price, "amount": amount, "vol": vol,
               "ev": 0.0, "ef": 0.0, "efee": 0.0, "ts": time.time()}
        st["bid"] = rec
        save_config(self.cfg)  # 보내기 전에 기록 (결과를 몰라도 다음에 고유 번호로 조회)
        try:
            o = self.api.place(f"KRW-{coin}", "bid", vol, price, identifier=rec["id"])
        except fo.UnknownResult:
            return  # uuid 없이 남겨 두면 다음 확인 때 고유 번호로 조회
        except RuntimeError as e:
            st.pop("bid", None)
            st["bid_fail_until"] = time.time() + 600
            save_config(self.cfg)
            self.alert("fail", f"{coin} 지정가 물타기 주문 실패 · 10분간 시장가 방식",
                       f"{e}\n그동안은 예전처럼 추가 매수가에 닿으면 시장가로 삽니다.")
            return
        rec["uuid"] = o["uuid"]
        save_config(self.cfg)

    def grid_bid_locked(self):
        """자동매매가 걸어 둔 지정가 매수에 묶인 원화 (남은 수량 × 주문가 + 수수료)."""
        out = 0.0
        for c in self.grid_tracked():
            b = self.grid_state(c).get("bid")
            if b and b.get("uuid"):
                out += max(b["vol"] - b["ev"], 0.0) * b["price"] * (1 + FEE)
        return out

    def krw_free(self, max_age=20):
        """현금 보호에 쓰는 원화: 업비트 주문 가능 원화 + 자동매매가 걸어 둔 매수에 묶인 원화.
        (걸어 둔 물타기 주문은 아직 안 쓴 돈으로 본다 = 시장가 물타기 때와 같은 기준. 피보나치 예약에 묶인 돈은 제외)
        업비트 잔고는 20초 캐시. API 없으면 None."""
        if not self.api:
            return None
        c = getattr(self, "_krw_cache", None)
        if not (c and time.time() - c[0] < max_age):
            acc = {a["currency"]: float(a["balance"]) for a in self.api.call("GET", "/accounts")}
            c = self._krw_cache = (time.time(), acc.get("KRW", 0.0))
        return c[1] + self.grid_bid_locked()

    def grid_cash_ok(self, kind, amount):
        """현금 보호 (실전만): 산 뒤 주문 가능 원화가 보호선 아래로 내려가면 매수하지 않는다.
        kind='start': 새 코인 시작 매수 (보호선 cash_floor_start), 'add': 물타기 (보호선 cash_floor_all).
        피보나치 예약 매수에 묶인 돈은 원래 주문 가능 원화에서 빠져 있어서 건드리지 않는다."""
        g = self.cfg["grid"]
        if g["simulate"] or not self.api:
            return True
        free = self.krw_free()
        floor = g.get("cash_floor_start", 0) if kind == "start" else g.get("cash_floor_all", 0)
        if free - amount < floor:
            what = "새 코인 시작 매수" if kind == "start" else "물타기 매수"
            self.grid_cap_alert(f"cash_{kind}", f"주문 가능 원화 {free:,.0f}원 → {what} 중지 (보호선 {floor:,.0f}원). "
                                                "파는 것(본전 절반·익절)은 계속합니다.")
            return False
        c = getattr(self, "_krw_cache", None)
        if c:  # 방금 쓴 만큼 캐시에서 빼 둔다 (20초 안에 여러 코인이 같이 사도 보호선을 넘지 않게)
            self._krw_cache = (c[0], c[1] - amount)
        return True

    def cash_stage_check(self):
        """주문 가능 원화 단계가 바뀌면 알림 (코인 모으기는 업비트 앱에서 직접 조절해야 해서 알려만 준다)."""
        g = self.cfg["grid"]
        free = self.krw_free(max_age=60)
        if free is None:
            return
        stage = (3 if free < g.get("cash_floor_all", 0) else 2 if free < g.get("cash_floor_start", 0)
                 else 1 if free < g.get("cash_warn", 0) else 0)
        prev = g.get("cash_stage", 0)
        if stage == prev:
            return
        g["cash_stage"] = stage
        save_config(self.cfg)
        msg = {0: ("현금 평시 복귀", f"주문 가능 원화 {free:,.0f}원. 코인 모으기를 원래대로(하루 7만) 되돌려도 됩니다."),
               1: ("현금 주의 단계", f"주문 가능 원화 {free:,.0f}원 (주의선 {g['cash_warn']:,}원 아래). "
                                 "업비트 앱에서 코인 모으기를 절반(하루 3.5만)으로 줄이세요."),
               2: ("현금 위험 단계", f"주문 가능 원화 {free:,.0f}원 (위험선 {g['cash_floor_start']:,}원 아래). "
                                 "자동매매 새 시작 매수를 멈췄습니다(물타기는 계속). 업비트 앱에서 코인 모으기를 일시 중지하세요."),
               3: ("현금 비상 단계", f"주문 가능 원화 {free:,.0f}원 (비상선 {g['cash_floor_all']:,}원 아래). "
                                 "자동매매 매수를 모두 멈췄습니다. 매도는 계속합니다. 코인 모으기는 중지 상태로 두세요.")}[stage]
        self.alert("fail" if stage > prev else "grid", *msg)

    def grid_realized(self):
        """자동매매 누적 실현 수익 (끝난 사이클 + 진행 중 사이클의 절반 매도분, 수수료 뺀 금액)."""
        return sum(st.get("profit_total", 0.0) + st.get("realized", 0.0) for st in self.cfg["grid"]["state"].values())

    def grid_total_cap(self):
        """실제 적용하는 전체 한도. 수익 재투자를 켜면 설정 한도 + 누적 실현 수익 (손실이면 설정 한도 그대로)."""
        g = self.cfg["grid"]
        return g["total_max_krw"] + (max(0.0, self.grid_realized()) if g.get("reinvest", True) else 0.0)

    def grid_stamp(self, st):
        """새 사이클을 시작할 때 그 사이클의 1회 금액·익절액·배수·하락폭을 적어 둔다 → 설정을 바꿔도 진행 중 사이클은 시작할 때 기준 그대로."""
        g = self.cfg["grid"]
        st["unit"], st["profit"] = g["unit_krw"], g["profit_krw"]
        st["mult"], st["drop"] = max(1.0, float(g.get("multiplier", 1.0))), float(g["drop_pct"])
        st["wide_after"], st["wide_drop"] = int(g.get("wide_after", 0)), float(g.get("wide_drop_pct", 0.0))

    def cycle_unit(self, st):
        return st.get("unit") or self.cfg["grid"]["unit_krw"]

    def cycle_profit(self, st):
        return st.get("profit") or self.cfg["grid"]["profit_krw"]

    def cycle_mult(self, st):
        return st.get("mult") or max(1.0, float(self.cfg["grid"].get("multiplier", 1.0)))

    def cycle_drop(self, st):
        """추가 매수 하락폭 (비율, 0.03 = 3%). wide_after회 이상 샀으면 넓힌 간격(wide_drop)으로 → 한 코인에 돈이 몰리는 것을 막는다."""
        g = self.cfg["grid"]
        wa = st.get("wide_after", g.get("wide_after", 0))
        wd = st.get("wide_drop", g.get("wide_drop_pct", 0.0))
        if wa and wd and st.get("buys", 0) >= wa:
            return wd / 100
        return (st.get("drop") or g["drop_pct"]) / 100

    def grid_btc_bear(self):
        """비트코인 약세 필터: 전날 비트코인 일봉 종가가 최근 N일(기본 20일) 종가 평균보다 낮으면 True → 새 코인 시작 매수를 쉰다.
        1시간마다 다시 판단. 조회가 실패하면 직전 판단을 유지 (처음이면 막지 않음). 상태가 바뀌면 알림."""
        g = self.cfg["grid"]
        if not g.get("btc_filter", True):
            self.btc_bear = None
            return False
        c = getattr(self, "_bear_ts", 0)
        if self.btc_bear and time.time() - c < 3600:
            return self.btc_bear[0]
        n = int(g.get("btc_filter_days", 20))
        try:
            rows = fr.get(f"/candles/days?market=KRW-BTC&count={n + 1}")
            closes = [r["trade_price"] for r in rows[1:n + 1]]  # 오늘(진행 중) 봉은 빼고 끝난 N일
            ma = sum(closes) / len(closes)
            bear = closes[0] < ma
        except Exception:
            return self.btc_bear[0] if self.btc_bear else False
        prev = g.get("btc_bear_last")
        self.btc_bear, self._bear_ts = (bear, closes[0], ma), time.time()
        if prev is not None and prev != bear:
            self.alert("grid", "비트코인 약세 · 새 시작 쉼" if bear else "비트코인 회복 · 새 시작 재개",
                       f"비트코인 전날 종가 {closes[0]:,.0f}원 · 최근 {n}일 평균 {ma:,.0f}원 → "
                       + ("평균 아래라 새 코인 시작 매수를 쉽니다. 들고 있는 코인의 물타기·익절은 그대로 합니다." if bear
                          else "평균 위로 올라와 새 코인 시작 매수를 다시 합니다."))
        if prev != bear:
            g["btc_bear_last"] = bear
            save_config(self.cfg)
        return bear

    def grid_next_amount(self, st):
        """다음 추가 매수 금액. 배수 1이면 1회 금액 그대로, 2면 1만 → 2만 → 4만 … (이번 사이클 매수 횟수 기준, 사이클의 1회 금액)."""
        g = self.cfg["grid"]
        mult = self.cycle_mult(st) if st.get("buys") else max(1.0, float(g.get("multiplier", 1.0)))
        unit = self.cycle_unit(st) if st.get("buys") else g["unit_krw"]
        return round(unit * mult ** max(st.get("buys", 0), 0) / 10) * 10 if st.get("buys") else unit

    def grid_be_qty(self, st, price):
        """본전에서 팔 수량. 직전 단계 금액어치(기본), 1회 금액어치 또는 절반. 판 뒤 남는 것도 업비트 최소 주문 이상이어야 하며, 안 되면 0.
        직전 단계 = 마지막 매수 바로 앞 단계의 매수 금액: 2회 샀으면 1회 금액, 3회면 1회×배수, 4회면 1회×배수² …"""
        g, q = self.cfg["grid"], st["qty"]
        mode = g.get("be_sell", "prev")
        amount = self.cycle_unit(st)
        if mode == "prev" and st["buys"] > 2:
            amount = round(amount * self.cycle_mult(st) ** (st["buys"] - 2) / 10) * 10
        sell = q / 2 if mode == "half" else min(amount / price, q)
        sell = int(sell * 1e8) / 1e8
        if sell * price < MIN_SELL_KRW or (q - sell) * price < MIN_SELL_KRW:
            return 0.0
        return sell

    def grid_cap_alert(self, key, msg):
        """한도 도달 알림은 같은 한도에 대해 1시간에 한 번만."""
        if time.time() - self.grid_capped.get(key, 0) > 3600:
            self.grid_capped[key] = time.time()
            self.alert("grid", "자동매매 한도 도달 · 추가 매수 멈춤", msg)

    def grid_view(self):
        g, rows = self.cfg["grid"], []
        listed = set(self.grid_coins())
        for coin in self.grid_tracked():
            st, p = self.grid_state(coin), self.prices.get(coin)
            if not p:  # 시세를 아직 못 받은 코인도 목록에 있다는 건 보여 준다
                rows.append({"status": "시세 대기", "listed": coin in listed, "coin": coin, "price": None, "buys": st["buys"], "cost": st["cost"],
                             "qty": st["qty"], "avg": None, "pnl": 0, "next_buy": None, "breakeven": None, "tp": None,
                             "cycles": st["cycles"], "profit_total": st["profit_total"]})
                continue
            q = st["qty"]
            avg = st["cost"] / q if q else None
            pnl = st["realized"] + q * p * (1 - FEE) - st["cost"] if q else 0
            # 익절가: realized + q*x*(1-FEE) - cost = profit
            tp = (self.cycle_profit(st) + st["cost"] - st["realized"]) / (q * (1 - FEE)) if q else None
            t = time.time()
            status = ("결과 확인 중" if st.get("pending") else "조회만 · 매매 안 함" if coin not in listed
                      else ("투자유의 중지" if st.get("blocked_why") in (None, "warning", "gone") else "주의 · 새 매수 쉼") if st.get("blocked")
                      else "새 시작 쉼" if q <= 0 and not st.get("bid") and (self.btc_bear or (False,))[0]
                      else f"정지 {int((st['pause_until'] - t) // 60) + 1}분" if st.get("pause_until", 0) > t else "자동매매 중")
            rows.append({"status": status, "listed": coin in listed, "auto": bool(st.get("auto")), "coin": coin, "price": p, "buys": st["buys"], "cost": st["cost"], "qty": q, "avg": avg,
                         "pnl": pnl, "next_buy": st["ref"] * (1 - self.cycle_drop(st)) if st["ref"] else None,
                         "breakeven": avg / (1 - FEE) if avg and st["buys"] >= 2 and not st["halved"] else None,
                         "tp": tp, "cycles": st["cycles"], "profit_total": st["profit_total"], "halved": bool(st.get("halved")) and q > 0,
                         "profit": self.cycle_profit(st) if q else g["profit_krw"], "unit": self.cycle_unit(st) if q else g["unit_krw"],
                         "fee_total": st.get("fee_total", 0.0), "realized": st["realized"],
                         "next_amt": self.grid_next_amount(st) if st["ref"] else None,
                         "orders": [(o["kind"], o["price"], o["vol"] - o["ev"]) for o in sorted(st.get("tp") or [], key=lambda o: o["price"])],
                         "bid": (st["bid"]["price"], st["bid"]["amount"]) if st.get("bid") else None})
        return rows

    # ---------- 텔레그램 (조회 전용): 엔진 스레드에서 글을 만들어 보낸다 ----------
    def tg_command(self, cmd):
        name, _, arg = cmd.partition(":")
        if name == "daily":
            y = (now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            self.tg.send(self.tg_day_text(y, "어제") + "\n\n" + self.tg_status_text())
            return
        make = {"status": self.tg_status_text, "coin": lambda: self.tg_coin_text(arg),
                "today": lambda: self.tg_day_text(now().strftime("%Y-%m-%d"), "오늘"),
                "yesterday": lambda: self.tg_day_text((now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d"), "어제"),
                "pnl": self.tg_pnl_text, "month": self.tg_month_text, "price": self.tg_price_text,
                "balance": self.tg_balance_text, "orders": self.tg_orders_text, "plan": self.tg_plan_text,
                "risk": self.tg_risk_text, "alerts": self.tg_alerts_text, "check": self.tg_check_text}.get(name)
        if not make:
            return
        try:
            self.tg.send(make())
        except Exception as e:  # noqa: BLE001 — 조회 실패는 휴대폰에 알려만 준다 (매매에는 영향 없음)
            self.tg.send(f"조회하다 오류가 났습니다 ({type(e).__name__}). 잠시 뒤 다시 보내 주세요.")

    # 휴대폰 텔레그램 앱에서 보기 좋게: 한 줄에 한 가지, 짧은 줄(25자 안팎), 금액은 만·억 단위, 코인 번호는 ①②③
    TG_LINE = "━━━━━━━━━━━━"
    TG_NUM = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

    @classmethod
    def tg_n(cls, i):
        return cls.TG_NUM[i - 1] if 1 <= i <= len(cls.TG_NUM) else f"{i}."

    @staticmethod
    def tg_won(x, sign=False):
        """금액 짧게: 1억 이상 1.23억, 1만 이상 2.5만, 그 아래는 원 단위."""
        s = "+" if sign and x > 0 else "-" if x < 0 else ""
        a = abs(x)
        if a >= 1e8:
            v = f"{a / 1e8:,.2f}".rstrip("0").rstrip(".") + "억"
        elif a >= 1e4:
            v = f"{a / 1e4:,.2f}".rstrip("0").rstrip(".") + "만"
        else:
            v = f"{a:,.0f}"
        return f"{s}{v}원"

    @staticmethod
    def tg_icon(status):
        return ("🟢" if status == "자동매매 중" else "🔴" if "중지" in status else "⚪" if "조회만" in status or "대기" in status
                else "🟡")

    def tg_tickers(self, coins):
        """업비트 시세 {코인: 시세 dict}. 원화마켓에 없는 코인은 빠진다."""
        coins = [c for c in dict.fromkeys(coins) if c]
        if not coins:
            return {}
        try:
            return {t["market"][4:]: t for t in fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in coins))}
        except Exception:  # noqa: BLE001 — 없는 코인이 섞이면 업비트가 통째로 거절하므로 하나씩
            out = {}
            for c in coins:
                try:
                    out[c] = fr.get(f"/ticker?markets=KRW-{c}")[0]
                except Exception:  # noqa: BLE001
                    pass
            return out

    @staticmethod
    def tg_chg(t):
        ch = t.get("signed_change_rate", 0.0) * 100
        return f"{'▲' if ch > 0 else '▼' if ch < 0 else ''}{abs(ch):.2f}%"

    @staticmethod
    def tg_pct(x, p):
        return f"{(x / p - 1) * 100:+.1f}%" if x and p else "-"

    def tg_sim(self):
        g = self.cfg["grid"]
        return g["simulate"] or not self.api

    def tg_head(self, icon, title):
        return [f"{icon} <b>{title}</b>", f"{now():%m-%d %H:%M} 기준", self.TG_LINE]

    def tg_accounts(self):
        if not self.api:
            return {}
        try:
            return {a["currency"]: a for a in self.api.call("GET", "/accounts")}
        except Exception:  # noqa: BLE001
            return {}

    def tg_status_text(self):
        """현황: 총괄 → 피보나치 코인별 → 자동매매 코인별."""
        g = self.cfg["grid"]
        W, P = self.tg_won, self.tg_pct
        tick = self.tg_tickers(list(dict.fromkeys(fr.COINS + self.grid_tracked())))
        price = lambda c: tick[c]["trade_price"] if c in tick else self.prices.get(c)  # noqa: E731
        rows = self.grid_view()
        trades = build_journal(self.db, self.tg_sim())
        today = now().strftime("%Y-%m-%d")
        sells = [t for t in trades if t["side"] == "ask"]
        buys = [t for t in trades if t["side"] == "bid"]
        t_sells = [t for t in sells if t["date"] == today]
        t_buys = [t for t in buys if t["date"] == today]
        cost = sum(r["cost"] for r in rows)
        upnl = sum(r["qty"] * (price(r["coin"]) or 0) * (1 - FEE) + r.get("realized", 0.0) - r["cost"] for r in rows if r["qty"])
        done = sum(r["profit_total"] + r.get("realized", 0.0) for r in rows)
        cap = self.grid_total_cap()
        L = self.tg_head("📊", "FibTrader 현황") + [
            "<b>💰 총괄</b>",
            f"누적 수익  <b>{W(done, True)}</b>",
            f"오늘 수익  <b>{W(sum(t['pnl'] or 0 for t in t_sells), True)}</b>",
            f"평가 손익  <b>{W(upnl, True)}</b>" + (f" ({upnl / cost * 100:+.1f}%)" if cost else ""),
            f"익절 횟수  오늘 {sum(1 for t in t_sells if t.get('full'))} · 누적 {sum(1 for t in sells if t.get('full'))}",
            f"오늘 거래  매수 {len(t_buys)} · 매도 {len(t_sells)}",
            f"누적 거래  매수 {len(buys)} · 매도 {len(sells)}",
            f"투입 금액  {W(cost)} / {W(cap)} ({cost / cap * 100 if cap else 0:.0f}%)"]
        acc = self.tg_accounts()
        if acc:
            try:
                L.append(f"주문 가능  {W(self.krw_free())}")
            except Exception:  # noqa: BLE001
                pass
        if (self.btc_bear or (None,))[0]:
            L.append("⚠️ 비트코인 약세: 새 시작 쉼")
        L += [self.TG_LINE, f"<b>📐 피보나치</b> · {'반자동' if self.cfg['mode'] == 'semi' else '알림만'}", ""]
        for i, c in enumerate(fr.COINS, 1):
            p = price(c)
            lv, pg = self.cfg.get("levels", {}).get(c, {}), self.cfg["progress"][c]
            sd, bd = pg["sell_done"], pg["buy_done"]
            sl, bl = lv.get("sells", []), lv.get("buys", [])
            L.append(f"<b>{self.tg_n(i)} {c}</b>  {fmtp(p) if p else '-'}" + (f" {self.tg_chg(tick[c])}" if c in tick else ""))
            a = acc.get(c)
            if a and p:
                q = float(a["balance"]) + float(a["locked"])
                avg = float(a.get("avg_buy_price") or 0)
                L.append(f" · 평가 {W(q * p)}" + (f" ({P(p, avg)})" if avg else ""))
            L.append(f" · 진행 매도 {sd}/{len(sl)} · 매수 {bd}/{len(bl)}")
            if bd < len(bl):
                L.append(f" · {bd + 1}차 매수 {fmtp(bl[bd])} ({P(bl[bd], p)})")
            if sd < len(sl):
                L.append(f" · {sd + 1}차 매도 {fmtp(sl[sd])} ({P(sl[sd], p)})")
            if lv.get("stop"):
                L.append(f" · 중단선 {fmtp(lv['stop'])} ({P(lv['stop'], p)})")
            L.append("")
        state = "꺼짐" if not g["enabled"] else "모의" if self.tg_sim() else "실전"
        per = journal_summary(trades, "coin")
        held = sorted((r for r in rows if r["qty"]), key=lambda r: -r["cost"])
        idle = [r for r in rows if not r["qty"]]
        L += [self.TG_LINE, f"<b>🤖 자동매매</b> · {state} · {len(rows)}개", ""]
        for i, r in enumerate(held + idle, 1):
            c, p = r["coin"], price(r["coin"])
            L.append(f"<b>{self.tg_n(i)} {c}</b>  {fmtp(p) if p else '-'}" + (f" {self.tg_chg(tick[c])}" if c in tick else ""))
            L.append(f" {self.tg_icon(r['status'])} {r['status']}")
            if r["qty"] and p:
                u = r["qty"] * p * (1 - FEE) + r.get("realized", 0.0) - r["cost"]
                L.append(f" · 손익 <b>{W(u, True)}</b> ({u / r['cost'] * 100:+.1f}%)")
                L.append(f" · {r['buys']}회 매수 · 원가 {W(r['cost'])}")
                L.append(f" · 평단 {fmtp(r['cost'] / r['qty'])}" + (" · 본전 매도함" if r.get("halved") else ""))
                if r.get("next_buy"):
                    L.append(f" · 물타기 {fmtp(r['next_buy'])} ({P(r['next_buy'], p)})"
                             + (f" {W(r['next_amt'])}" if r.get("next_amt") else ""))
                if r.get("tp"):
                    L.append(f" · 익절 {fmtp(r['tp'])} ({P(r['tp'], p)}) {W(r['profit'], True)}")
            else:
                L.append(" · 보유 없음 (다음 판 대기)")
            j = per.get(c, {})
            L.append(f" · 누적 {W(r['profit_total'] + r.get('realized', 0.0), True)} · 익절 {r['cycles']}번")
            L.append(f" · 거래 매수 {j.get('buys', 0)} · 매도 {j.get('sells', 0)}")
            L.append("")
        return "\n".join(L).rstrip()

    def tg_day_text(self, date, label):
        """하루 요약: 총괄 → 거래한 코인별."""
        W = self.tg_won
        trades = [t for t in build_journal(self.db, self.tg_sim()) if t["date"] == date]
        sells = [t for t in trades if t["side"] == "ask"]
        buys = [t for t in trades if t["side"] == "bid"]
        L = [f"📅 <b>{label} 자동매매</b>", f"{date}", self.TG_LINE, "<b>💰 총괄</b>",
             f"실현 수익  <b>{W(sum(t['pnl'] or 0.0 for t in sells), True)}</b>",
             f"익절  {sum(1 for t in sells if t.get('full'))}번",
             f"매수 {len(buys)}번 · {W(sum(t['krw'] for t in buys))}",
             f"매도 {len(sells)}번 · {W(sum(t['krw'] for t in sells))}"]
        per = journal_summary(trades, "coin")
        if not per:
            return "\n".join(L + [self.TG_LINE, "거래 없음"])
        L += [self.TG_LINE, "<b>🪙 코인별</b>", ""]
        for i, a in enumerate(sorted(per.values(), key=lambda a: (-a["pnl"], -a["buy_krw"])), 1):
            L.append(f"<b>{self.tg_n(i)} {a['key']}</b>" + (f"  {W(a['pnl'], True)}" if a["sells"] else ""))
            if a["sells"]:
                L.append(f" · 익절 {a['cycles']}번 · 매도 {a['sells']}번")
            L.append(f" · 매수 {a['buys']}번 {W(a['buy_krw'])}")
            L.append("")
        return "\n".join(L).rstrip()

    def tg_pnl_text(self):
        W = self.tg_won
        trades = [t for t in build_journal(self.db, self.tg_sim()) if t["side"] == "ask"]
        today = now().date()
        spans = [("오늘", today, today), ("어제", today - datetime.timedelta(days=1), today - datetime.timedelta(days=1)),
                 ("7일", today - datetime.timedelta(days=6), today), ("이번 달", today.replace(day=1), today)]
        L = self.tg_head("💰", "자동매매 수익") + [f"<b>📈 총괄</b> · {'모의' if self.tg_sim() else '실전'}"]
        for label, a_, b_ in spans:
            ts = [t for t in trades if a_.isoformat() <= t["date"] <= b_.isoformat()]
            L.append(f"{label}  <b>{W(sum(t['pnl'] or 0 for t in ts), True)}</b> · 익절 {sum(1 for t in ts if t.get('full'))}")
        L.append(f"누적  <b>{W(sum(t['pnl'] or 0 for t in trades), True)}</b> · 익절 {sum(1 for t in trades if t.get('full'))}")
        L.append("(수수료 뺀 금액)")
        per = journal_summary(trades, "coin")
        if per:
            L += [self.TG_LINE, "<b>🪙 코인별 누적</b>", ""]
            for i, a in enumerate(sorted(per.values(), key=lambda a: -a["pnl"]), 1):
                L.append(f"<b>{self.tg_n(i)} {a['key']}</b>  {W(a['pnl'], True)}")
                L.append(f" · 익절 {a['cycles']}번 · 매도 {a['sells']}번")
        return "\n".join(L)

    def tg_month_text(self):
        W = self.tg_won
        per = journal_summary([t for t in build_journal(self.db, self.tg_sim()) if t["side"] == "ask"], "month")
        L = self.tg_head("📆", "월별 수익")
        if not per:
            return "\n".join(L + ["아직 매도 기록이 없습니다."])
        for m in sorted(per)[-6:][::-1]:
            a = per[m]
            L.append(f"<b>{m[:4]}년 {int(m[5:])}월</b>  {W(a['pnl'], True)}")
            L.append(f" · 익절 {a['cycles']}번 · 매도 {a['sells']}번")
        return "\n".join(L)

    def tg_price_text(self):
        tick = self.tg_tickers(list(dict.fromkeys(fr.COINS + self.grid_tracked())))
        L = self.tg_head("💹", "시세 (많이 오른 순)")
        for i, c in enumerate(sorted(tick, key=lambda c: -tick[c].get("signed_change_rate", 0)), 1):
            t = tick[c]
            L.append(f"<b>{self.tg_n(i)} {c}</b>  {fmtp(t['trade_price'])}")
            L.append(f" · {self.tg_chg(t)} · 거래 {self.tg_won(t.get('acc_trade_price_24h', 0))}")
        return "\n".join(L)

    def tg_coin_text(self, coin):
        W, P = self.tg_won, self.tg_pct
        coin = coin.upper().replace("KRW-", "")
        tick = self.tg_tickers([coin]).get(coin)
        if not tick:
            return f"{coin}: 업비트 원화마켓에 없는 코인입니다."
        p = tick["trade_price"]
        L = self.tg_head("🔎", f"{coin}  {fmtp(p)} {self.tg_chg(tick)}") + [
            f"고가  {fmtp(tick.get('high_price'))}", f"저가  {fmtp(tick.get('low_price'))}",
            f"거래  {W(tick.get('acc_trade_price_24h', 0))}"]
        known = False
        if coin in fr.COINS and self.cfg.get("levels", {}).get(coin):
            known = True
            lv, pg = self.cfg["levels"][coin], self.cfg["progress"][coin]
            L += [self.TG_LINE, f"<b>📐 피보나치</b> · 매도 {pg['sell_done']}/{len(lv['sells'])} · 매수 {pg['buy_done']}/{len(lv['buys'])}"]
            for i, x in reversed(list(enumerate(lv["sells"]))):
                L.append(f"{'✅' if i < pg['sell_done'] else '▫️'} {i + 1}차 매도 {fmtp(x)} ({P(x, p)})")
            L.append(f"👉 지금 {fmtp(p)}")
            for i, x in enumerate(lv["buys"]):
                L.append(f"{'✅' if i < pg['buy_done'] else '▫️'} {i + 1}차 매수 {fmtp(x)} ({P(x, p)})")
            L.append(f"⛔ 중단선 {fmtp(lv['stop'])} ({P(lv['stop'], p)})")
        row = next((r for r in self.grid_view() if r["coin"] == coin), None)
        if row:
            known = True
            L += [self.TG_LINE, "<b>🤖 자동매매</b>", f"{self.tg_icon(row['status'])} {row['status']}"]
            if row["qty"]:
                u = row["qty"] * p * (1 - FEE) + row.get("realized", 0.0) - row["cost"]
                L.append(f"손익  <b>{W(u, True)}</b> ({u / row['cost'] * 100:+.1f}%)")
                L.append(f"매수  {row['buys']}회 · 원가 {W(row['cost'])}")
                L.append(f"평단  {fmtp(row['cost'] / row['qty'])}" + (" · 본전 매도함" if row.get("halved") else ""))
                if row.get("next_buy"):
                    L.append(f"물타기  {fmtp(row['next_buy'])} ({P(row['next_buy'], p)})")
                    if row.get("next_amt"):
                        L.append(f"  └ 금액 {W(row['next_amt'])}")
                if row.get("breakeven"):
                    L.append(f"본전  {fmtp(row['breakeven'])} ({P(row['breakeven'], p)})")
                if row.get("tp"):
                    L.append(f"익절  {fmtp(row['tp'])} ({P(row['tp'], p)})")
                    L.append(f"  └ 목표 {W(row['profit'], True)}")
            else:
                L.append("보유 없음 (다음 판 대기)")
            L.append(f"누적  {W(row['profit_total'], True)} · 익절 {row['cycles']}번")
        a = self.tg_accounts().get(coin)
        if a:
            q = float(a["balance"]) + float(a["locked"])
            avg = float(a.get("avg_buy_price") or 0)
            L += [self.TG_LINE, "<b>🏦 업비트 계좌</b>", f"수량  {q:,.8g}개", f"평가  {W(q * p)}"]
            if avg:
                L.append(f"평단  {fmtp(avg)} ({P(p, avg)})")
        if not known:
            L += [self.TG_LINE, "FibTrader가 매매하지 않는 코인입니다."]
        return "\n".join(L)

    def tg_balance_text(self):
        W, P = self.tg_won, self.tg_pct
        if not self.api:
            return "API 키가 없어서 잔고를 볼 수 없습니다."
        acc = self.api.call("GET", "/accounts")
        krw = next((float(a["balance"]) + float(a["locked"]) for a in acc if a["currency"] == "KRW"), 0.0)
        krw_free = next((float(a["balance"]) for a in acc if a["currency"] == "KRW"), 0.0)
        coins = {a["currency"]: a for a in acc if a["currency"] != "KRW" and float(a["balance"]) + float(a["locked"]) > 0}
        tick = self.tg_tickers(list(coins))
        rows = []
        for c, a in coins.items():
            if c in tick:
                q = float(a["balance"]) + float(a["locked"])
                avg = float(a.get("avg_buy_price") or 0)
                rows.append((q * tick[c]["trade_price"], c, q * avg, tick[c]["trade_price"], avg))
        rows = sorted((r for r in rows if r[0] >= 1000), reverse=True)
        val, base = sum(r[0] for r in rows), sum(r[2] for r in rows)
        L = self.tg_head("🏦", "업비트 잔고") + [
            f"총자산  <b>{W(krw + val)}</b>", f"원화  {W(krw)}", f"주문 가능  {W(krw_free)}", f"코인  {W(val)}",
            f"평가 손익  <b>{W(val - base, True)}</b>" + (f" ({(val / base - 1) * 100:+.1f}%)" if base else ""),
            self.TG_LINE, "<b>🪙 코인별</b> (많은 순)", ""]
        for i, (v, c, b, p, avg) in enumerate(rows[:20], 1):
            L.append(f"<b>{self.tg_n(i)} {c}</b>  {W(v)}")
            if avg:
                L.append(f" · {W(v - b, True)} ({P(p, avg)})")
        return "\n".join(L)

    def tg_orders_text(self):
        W, P = self.tg_won, self.tg_pct
        if not self.api:
            return "API 키가 없어서 주문을 볼 수 없습니다."
        orders = self.api.open_all()
        if not orders:
            return "📋 업비트에 걸린 주문이 없습니다."
        tick = self.tg_tickers([o["market"][4:] for o in orders if o["market"].startswith("KRW-")])
        by = {}
        for o in orders:
            by.setdefault(o["market"][4:], []).append(o)
        amt = lambda o: float(o["price"] or 0) * float(o["remaining_volume"] or 0)  # noqa: E731
        L = self.tg_head("📋", "걸린 주문") + [
            f"전체  {len(orders)}건", f"매수  {sum(1 for o in orders if o['side'] == 'bid')}건 · {W(sum(amt(o) for o in orders if o['side'] == 'bid'))}",
            f"매도  {sum(1 for o in orders if o['side'] == 'ask')}건 · {W(sum(amt(o) for o in orders if o['side'] == 'ask'))}",
            self.TG_LINE, ""]
        for i, c in enumerate(sorted(by), 1):
            p = tick.get(c, {}).get("trade_price")
            L.append(f"<b>{self.tg_n(i)} {c}</b>" + (f"  지금 {fmtp(p)}" if p else ""))
            for o in sorted(by[c], key=lambda o: -float(o["price"] or 0)):
                px = float(o["price"] or 0)
                L.append(f" {'🔵 매도' if o['side'] == 'ask' else '🔴 매수'} {fmtp(px)}" + (f" ({P(px, p)})" if p else "") + f" {W(amt(o))}")
            L.append("")
        return "\n".join(L).rstrip()

    def tg_plan_text(self):
        P = self.tg_pct
        tick = self.tg_tickers(fr.COINS)
        L = self.tg_head("📐", "피보나치 플랜") + ["✅ 체결 · 👉 지금 가격", ""]
        for i, c in enumerate(fr.COINS, 1):
            lv = self.cfg.get("levels", {}).get(c)
            if not lv:
                continue
            pg = self.cfg["progress"][c]
            p = tick.get(c, {}).get("trade_price") or self.prices.get(c)
            L.append(f"<b>{self.tg_n(i)} {c}</b>" + (f"  {self.tg_chg(tick[c])}" if c in tick else ""))
            for k, x in reversed(list(enumerate(lv["sells"]))):
                L.append(f"{'✅' if k < pg['sell_done'] else '▫️'} {k + 1}차 매도 {fmtp(x)} ({P(x, p)})")
            L.append(f"👉 지금 {fmtp(p)}")
            for k, x in enumerate(lv["buys"]):
                L.append(f"{'✅' if k < pg['buy_done'] else '▫️'} {k + 1}차 매수 {fmtp(x)} ({P(x, p)})")
            L.append(f"⛔ 중단선 {fmtp(lv['stop'])} ({P(lv['stop'], p)})")
            L.append(f"레벨 기준 {lv.get('at', '-')}")
            L.append("")
        return "\n".join(L).rstrip()

    def tg_risk_text(self):
        W, P = self.tg_won, self.tg_pct
        g = self.cfg["grid"]
        allrows = self.grid_view()
        rows = [r for r in allrows if r["qty"]]
        cost = sum(r["cost"] for r in rows)
        cap = self.grid_total_cap()
        up = sum(r["qty"] * (r["price"] or 0) * (1 - FEE) + r.get("realized", 0.0) - r["cost"] for r in rows)
        L = self.tg_head("⚠️", "위험 점검") + [
            "<b>📊 한도</b>", f"투입  {W(cost)} / {W(cap)}", f"사용  <b>{cost / cap * 100 if cap else 0:.0f}%</b>",
            f"코인당 한도  {W(g['max_krw'])}", f"평가 손익  <b>{W(up, True)}</b>"]
        if rows:
            L += [self.TG_LINE, "<b>🪙 많이 들어간 코인</b>", ""]
            for i, r in enumerate(sorted(rows, key=lambda r: -r["cost"])[:5], 1):
                u = r["qty"] * (r["price"] or 0) * (1 - FEE) + r.get("realized", 0.0) - r["cost"]
                L.append(f"<b>{self.tg_n(i)} {r['coin']}</b>  {r['buys']}회 · {W(r['cost'])}")
                L.append(f" · 코인 한도의 {r['cost'] / g['max_krw'] * 100:.0f}% · {W(u, True)}")
                if r.get("next_buy") and r["price"]:
                    L.append(f" · 다음 {fmtp(r['next_buy'])} ({P(r['next_buy'], r['price'])})"
                             + (f" {W(r['next_amt'])}" if r.get("next_amt") else ""))
        wide = int(g.get("wide_after", 0))
        deep = [r for r in rows if wide and r["buys"] >= wide - 3]
        blocked = [r for r in allrows if "중지" in r["status"] or "쉼" in r["status"]]
        if deep or blocked:
            L += [self.TG_LINE, "<b>🚨 살펴볼 것</b>"]
            for r in deep:
                L.append(f" · {r['coin']} 물타기 {r['buys']}회 ({wide}회부터 간격 넓어짐)")
            for r in blocked:
                L.append(f" · {r['coin']} {r['status']}")
        try:
            free = self.krw_free()
        except Exception:  # noqa: BLE001
            free = None
        if free is not None:
            L += [self.TG_LINE, "<b>💵 현금</b>", f"주문 가능  {W(free)}",
                  f"새 시작 멈춤  {W(g.get('cash_floor_start', 0))} 아래", f"모든 매수 멈춤  {W(g.get('cash_floor_all', 0))} 아래"]
        if (self.btc_bear or (False,))[0]:
            L.append("⚠️ 비트코인 약세: 새 시작 쉼")
        return "\n".join(L)

    def tg_alerts_text(self):
        rows = self.db.query("SELECT ts, title, msg FROM alerts WHERE kind NOT IN ('order', 'info') ORDER BY rowid DESC LIMIT 10")
        L = self.tg_head("🔔", "최근 알림 10개")
        if not rows:
            return "\n".join(L + ["최근 알림이 없습니다."])
        for ts, title, msg in rows:
            first = (msg or "").split("\n")[0]
            L.append(f"<b>{ts[5:16]}</b>  {ftg.esc(title)}")
            if first:
                L.append(f" └ {ftg.esc(first[:45])}")
            L.append("")
        return "\n".join(L).rstrip()

    def tg_check_text(self):
        g = self.cfg["grid"]
        last = getattr(self, "last_ok", 0)
        ago = time.time() - last if last else None
        ok = ago is not None and ago < 3 * max(self.cfg["every_sec"], 10) + 30
        up = max(0.0, time.time() - getattr(self, "started", 0.0)) if getattr(self, "started", None) else None
        L = self.tg_head("🩺", "프로그램 점검") + [
            "✅ <b>정상 작동</b>" if ok else "⚠️ <b>확인이 늦어지는 중</b>",
            f"마지막 확인  {f'{ago:.0f}초 전' if ago is not None else '아직 없음'}",
            f"켜진 시간  {int(up // 3600)}시간 {int(up % 3600 // 60)}분" if up is not None else "켜진 시간  모름",
            f"업비트 API  {'연결됨' if self.api else '키 없음'}",
            f"피보나치  {'반자동' if self.cfg['mode'] == 'semi' else '알림만'} · {'모의' if self.cfg['simulate'] else '실전'}",
            f"자동매매  {'꺼짐' if not g['enabled'] else '모의' if self.tg_sim() else '실전'} · {len(self.grid_coins())}개",
            f"텔레그램  {self.tg.status}"]
        if self.cfg.get("stopped"):
            L += ["", "⛔ 긴급 정지 상태", "(PC에서 [재개]를 눌러야 풀림)"]
        if self.proposal:
            L += ["", "📝 PC에 승인 대기 주문 제안 있음"]
        return "\n".join(L)

    def grid_refresh(self):
        """[조회] 버튼: 자동매매 대상·보유 코인 시세를 바로 받아 표를 새로 그린다 (주문은 안 함)."""
        coins = self.grid_tracked()
        if coins:
            for t in fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in coins)):
                self.prices[t["market"][4:]] = t["trade_price"]
        self.emit("grid", self.grid_view())

    def grid_liquidate(self, coin):
        st = self.grid_state(coin)
        if st.get("pending"):
            self.emit("done", [f"{coin}: 결과 확인 중인 주문이 있어 잠시 뒤 다시 시도하세요."])
            return
        live = not (self.cfg["grid"]["simulate"] or not self.api)
        if live and ((st.get("bid") and not self.grid_bid_cancel(coin)) or (st.get("tp") and not self.grid_tp_cancel(coin))):  # 걸어 둔 주문부터 취소
            self.alert("fail", f"{coin} 청산 보류", "걸어 둔 지정가 매도의 취소를 확인하지 못했습니다. 잠시 뒤 다시 시도하세요.")
            return
        if st["qty"] <= 0 or coin not in self.prices:
            self.cfg["grid"]["coins"] = [c for c in self.cfg["grid"]["coins"] if c != coin]
            save_config(self.cfg)
            return
        before = st["qty"]
        if live and before * self.prices[coin] < 5_000:
            self.alert("fail", f"{coin} 청산 못 함 · 5,000원 미만",
                       f"자동매매 보유분이 {before * self.prices[coin]:,.0f}원어치라 업비트 최소 주문(5,000원)보다 작아 팔 수 없습니다.\n"
                       "자동매매 탭에서 체크하고 [선택 코인 청산]을 누르면 '장부만 정리'할 수 있습니다 (코인은 계좌에 남음).")
            return
        try:
            qty, krw, px, sim = self.grid_trade(coin, "ask", self.prices[coin], before)
        except RuntimeError as e:
            self.alert("fail", f"{coin} 청산 실패", f"{e}\n장부는 그대로 두었습니다. 업비트에서 직접 팔았다면 [선택 코인 청산] → '장부만 정리'를 하세요.")
            return
        pnl = st["realized"] + krw - st["cost"] * min(qty / before, 1)
        st["profit_total"] += pnl
        st.update(qty=0.0, cost=0.0, buys=0, ref=None, halved=False, realized=0.0)
        self.cfg["grid"]["coins"] = [c for c in self.cfg["grid"]["coins"] if c != coin]
        save_config(self.cfg)
        self.alert("grid", f"{coin} 청산", f"{fmtp(px)}원에 전량 매도 · 손익 {pnl:+,.0f}원 · 자동매매 목록에서 뺐습니다",
                   say=("sell", f"{fv.kname(coin)} 청산, 손익 {fv.won(pnl)}"))

    def grid_forget(self, coin):
        """장부만 정리: 업비트에서 직접 팔았거나 5,000원 미만이라 못 파는 자동매매 보유분을 장부에서 지운다.
        현재가로 판 것으로 추정해 투자일지에 '장부 정리'로 남긴다. 계좌에 남은 코인은 이후 기존 보유로 본다."""
        st = self.grid_state(coin)
        if st.get("pending"):
            self.emit("done", [f"{coin}: 결과 확인 중인 주문이 있어 잠시 뒤 다시 시도하세요."])
            return
        g = self.cfg["grid"]
        if self.api and ((st.get("bid") and not self.grid_bid_cancel(coin)) or (st.get("tp") and not self.grid_tp_cancel(coin))):
            self.emit("done", [f"{coin}: 걸어 둔 지정가 주문의 취소를 확인하지 못했습니다. 잠시 뒤 다시 시도하세요."])
            return
        qty, cost = st["qty"], st["cost"]
        if qty > 0:
            px = self.prices.get(coin) or st.get("ref") or 0
            krw = qty * px * (1 - FEE)
            pnl = st["realized"] + krw - cost
            st["profit_total"] += pnl
            self.db.add("grid_trades", now().isoformat(), int(g["simulate"] or not self.api), coin, "ask", px, qty, krw, "장부 정리")
            msg = (f"자동매매 장부에서 {qty:g}개 (원가 {cost:,.0f}원)를 지웠습니다. 현재가 {fmtp(px)}원 기준 손익 {pnl:+,.0f}원 (추정)으로 "
                   "투자일지에 남겼습니다. 업비트 계좌에 남은 코인은 이제 기존 보유로 봅니다.")
        else:
            msg = "정리할 자동매매 보유분이 없어 목록에서만 뺐습니다."
        st.update(qty=0.0, cost=0.0, buys=0, ref=None, halved=False, realized=0.0)
        st.pop("auto", None)
        g["coins"] = [c for c in g["coins"] if c != coin]
        save_config(self.cfg)
        self.alert("grid", f"{coin} 장부 정리", msg)

    def grid_adopt(self, coin):
        """[기존 보유 합치기]: 업비트 계좌에 따로 있던 같은 코인을 자동매매 장부에 넣고, 원가를 업비트 매수평균가에 맞춘다.
        주문은 나가지 않는다. 합친 뒤 익절·물타기는 합친 수량 전체로 하고, 수익도 업비트 앱과 같게 계산한다.
        예전에 그 코인을 '장부 정리'로 지웠다면 그때 '현재가로 팔았다고 추정한 손익'은 실제로 팔린 게 아니므로 취소한다
        (안 그러면 업비트 평단으로 맞출 때 그 손익이 두 번 잡힌다). 이미 합친 코인에 다시 누르면 평단만 맞춘다."""
        g, st = self.cfg["grid"], self.grid_state(coin)
        if g["simulate"] or not self.api:
            self.emit("done", [f"{coin}: 기존 보유 합치기는 실전(API 연결)에서만 됩니다."])
            return
        if st.get("pending"):
            self.emit("done", [f"{coin}: 결과 확인 중인 주문이 있어 잠시 뒤 다시 시도하세요."])
            return
        if (st.get("bid") and not self.grid_bid_cancel(coin)) or (st.get("tp") and not self.grid_tp_cancel(coin)):  # 묶인 수량이 풀려야 잔고를 제대로 센다 (다음 확인 때 다시 걸림)
            self.emit("done", [f"{coin}: 걸어 둔 지정가 주문의 취소를 확인하지 못했습니다. 잠시 뒤 다시 시도하세요."])
            return
        px = self.prices.get(coin) or fr.get(f"/ticker?markets=KRW-{coin}")[0]["trade_price"]
        acc = {a["currency"]: a for a in self.api.call("GET", "/accounts")}
        bal = float(acc[coin]["balance"]) if coin in acc else 0.0  # 주문에 묶인 수량은 빼고
        avg = float(acc[coin].get("avg_buy_price") or 0) if coin in acc else 0.0
        own = bal - st["qty"]
        msgs = []
        if own * px >= 1_000:
            cost = own * px
            self.db.add("grid_trades", now().isoformat(), 0, coin, "bid", px, own, cost, "기존 보유 편입")
            if st["qty"] <= 0:  # 진행 중 사이클이 없으면 이것으로 새 사이클 시작
                st.update(buys=1, ref=px, halved=False, realized=0.0)
                self.grid_stamp(st)
            st.update(qty=st["qty"] + own, cost=st["cost"] + cost)
            st.pop("rebased", None)
            if coin not in g["coins"]:
                g["coins"].append(coin)
            msgs.append(f"{own:g}개를 자동매매 장부에 넣었습니다 (주문 없음).")
        adopt = self.db.query("SELECT rowid, qty, krw FROM grid_trades WHERE coin = ? AND simulated = 0 AND note = '기존 보유 편입' "
                              "ORDER BY rowid DESC LIMIT 1", coin)
        if adopt and not st.get("rebased") and avg > 0 and st["qty"] > 0 and abs(bal - st["qty"]) <= st["qty"] * 0.001:
            rid, aq, akrw = adopt[0]
            new_cost = st["qty"] * avg * (1 + FEE)  # 업비트 매수평균가는 수수료 전 → 산 때 낸 수수료를 더해 앱 원가 기준과 맞춤
            delta = new_cost - st["cost"]
            self.db.run("UPDATE grid_trades SET krw = ?, price = ? WHERE rowid = ?", akrw + delta, (akrw + delta) / aq, rid)
            # 편입 전 마지막 '장부 정리'(같은 수량)의 추정 손익 취소 → 일지 합계 = 실제
            undo = 0.0
            forget = self.db.query("SELECT rowid, qty FROM grid_trades WHERE coin = ? AND note = '장부 정리' AND rowid < ? "
                                   "ORDER BY rowid DESC LIMIT 1", coin, rid)
            if forget and abs(forget[0][1] - aq) <= aq * 0.05:
                t = next((x for x in build_journal(self.db) if x["id"] == forget[0][0]), None)
                if t and t.get("pnl") is not None and t.get("base") is not None:
                    undo = t["pnl"]
                    self.db.run("UPDATE grid_trades SET krw = ? WHERE rowid = ?", t["base"], forget[0][0])
                    st["profit_total"] -= undo
            st.update(cost=new_cost, rebased=True)
            msgs.append(f"원가를 업비트 매수평균가 {fmtp(avg)}원 기준으로 맞췄습니다 (원가 {new_cost:,.0f}원, {delta:+,.0f}원)."
                        + (f" 예전 장부 정리 때 추정한 손익 {undo:+,.0f}원은 실제로 판 게 아니라 취소했습니다." if undo else ""))
        if not msgs:
            self.emit("done", [f"{coin}: 합치거나 맞출 게 없습니다."])
            return
        save_config(self.cfg)
        v = st["qty"] * px * (1 - FEE) - st["cost"] + st["realized"]
        self.alert("grid", f"{coin} 기존 보유 합침", " ".join(msgs) + f" 지금 손익 {v:+,.0f}원 (업비트 앱과 같은 기준, 팔 때 수수료 뺌)")
        self.emit("grid", self.grid_view())

    def emergency_stop(self, cancel_all):
        if not self.cfg.get("stopped"):  # 재개할 때 되돌릴 값
            self.cfg["stopped"] = {"at": now().strftime("%m-%d %H:%M"), "mode": self.cfg["mode"],
                                   "grid": self.cfg["grid"]["enabled"]}
        self.cfg["grid"]["enabled"] = False
        self.cfg["mode"] = "alert"
        save_config(self.cfg)
        msgs = ["모드를 '알림만'으로 바꾸고 자동매매를 껐습니다."]
        if cancel_all and self.api:
            for coin in fr.COINS:
                for o in self.api.open_orders(f"KRW-{coin}"):
                    try:
                        self.api.cancel(o["uuid"])
                        msgs.append(f"취소 {o['market']} {o['side']} {float(o['price']):,.0f}")
                    except RuntimeError as e:
                        msgs.append(f"취소 실패 {o['market']}: {e}")
            for coin in self.grid_tracked():  # 자동매매 지정가 주문도 취소 (재개하면 다시 건다)
                for key, fn, word in (("bid", self.grid_bid_cancel, "매수"), ("tp", self.grid_tp_cancel, "매도")):
                    if self.grid_state(coin).get(key):
                        try:
                            ok = fn(coin)
                        except Exception:
                            ok = False
                        msgs.append(f"{'취소' if ok else '취소 확인 못 함'} {coin} 자동매매 지정가 {word}")
            self.known_orders = None
        self.alert("stop", "긴급 정지", "\n".join(msgs))
        self.emit("done", msgs)

    def resume(self):
        """긴급 정지 해제: 정지 전 모드·자동매매 켜짐 상태로 되돌린다 (취소한 주문은 되살리지 않음)."""
        st = self.cfg.get("stopped")
        if not st:
            return
        self.cfg["mode"] = st.get("mode", "semi")
        self.cfg["grid"]["enabled"] = st.get("grid", False)
        self.cfg["stopped"] = None
        save_config(self.cfg)
        self.alert("stop", "재개", f"모드 '{'반자동' if self.cfg['mode'] == 'semi' else '알림만'}' · 자동매매 "
                                 f"{'켜짐' if self.cfg['grid']['enabled'] else '꺼짐'}으로 되돌렸습니다.")
        self.emit("done", ["긴급 정지를 풀었습니다."])
        if self.cfg["mode"] == "semi":
            self.make_proposal("재개 후 플랜과 비교", force=True)

    # ---------- 메인 루프 ----------
    def run(self):
        self.started = time.time()
        self.tg.start()
        self.emit("status", "레벨 계산 중…")
        while not self.stop_event.is_set():
            try:
                if not self.levels:
                    if not self.cfg.get("levels"):
                        self.recalc_levels("처음 실행: 플랜 레벨 계산")
                    self.load_levels()
                    self.last_levels = time.time()
                    self.check_prices()
                    self.make_proposal("시작 시 플랜과 비교")
                elif time.time() - self.last_levels > 600:  # 10분마다 레벨 변화 확인
                    self.check_drift()
                self.check_prices()
                self.check_fills()
                if time.time() - self.last_board > 300:
                    self.refresh_board()
                keys = "API 연결됨" if self.api else "API 키 없음(체결 감지·주문 불가)"
                mode = "반자동" if self.cfg["mode"] == "semi" else "알림만"
                sim = " · 모의" if self.cfg["simulate"] else " · 실전"
                self.emit("status", f"{now():%H:%M:%S} 확인 · {mode}{sim} · {keys}")
                self.last_ok = time.time()
            except Exception as e:  # 네트워크 오류 등은 다음 주기에 재시도
                self.emit("status", f"{now():%H:%M:%S} 오류(재시도): {e}")
            deadline = time.time() + self.cfg["every_sec"]
            while time.time() < deadline and not self.stop_event.is_set():
                try:
                    cmd, args = self.commands.get(timeout=0.3)
                except queue.Empty:
                    continue
                try:
                    getattr(self, cmd)(*args)
                except Exception as e:
                    self.emit("done", [f"오류: {e}"])
