"""FibTrader 엔진: 설정, 기록 DB, 감시(가격·체결), 재계산 제안, 승인 후 실행.

화면(fibtrader.pyw)과는 queue로만 주고받는다. 표준 라이브러리만 사용.
이벤트: ("prices", {coin: price}), ("board", {coin: 현황}), ("alert", 제목, 내용),
        ("proposal", 제안), ("done", 실행 결과 문자열 목록), ("status", 문자열)
"""
import datetime
import json
import os
import queue
import sqlite3
import threading
import time

import fib_check as fc
import fib_orders as fo
import fib_recalc as fr

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "fibtrader_config.json")
DB_PATH = os.path.join(HERE, "fibtrader.db")
KST = datetime.timezone(datetime.timedelta(hours=9))

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
    "levels": {},                   # 고정 플랜 레벨 {coin: {sells, buys, stop, at}}
    "grid": {                       # 자동매매(물타기): 피보나치와 별개, 승인 없이 자동 주문
        "enabled": True,
        "simulate": True,           # 켜 두면 가상으로만 사고판다
        "coins": ["BCH", "SOL", "DOGE"],
        "unit_krw": 10_000,         # 1회 매수 금액
        "drop_pct": 5.0,            # 마지막 매수가(또는 절반 매도가) 대비 이만큼 떨어지면 추가 매수
        "profit_krw": 500,          # 사이클 수익(수수료 뺀 뒤)이 이 금액 이상이면 전량 매도
        "half_at_breakeven": True,  # 2회 이상 산 뒤 본전(수수료 포함)에 오면 절반 매도
        "max_krw": 500_000,         # 코인별 최대 투입(보유 원가) 한도
        "total_max_krw": 1_500_000, # 자동매매 전체 원가 한도 (여러 코인이 같이 빠질 때)
        "max_trades_per_day": 200,  # 하루 실전 거래가 이보다 많으면 버그·폭주로 보고 자동매매를 끈다
        "state": {},
    },
}
GRID_BLOCKED = set(fr.COINS)  # 피보나치 코인은 자동매매 금지
FEE = 0.0005
MIN_SELL_KRW = 5_500  # 업비트 최소 주문 5,000원 + 수수료·가격 변동 여유


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


def make_api():
    access, secret = os.environ.get("UPBIT_ACCESS_KEY"), os.environ.get("UPBIT_SECRET_KEY")
    return fo.Upbit(access, secret) if access and secret else None


def todo_key(todo):
    return json.dumps([(k, m, o["side"], o["price"], round(o["volume"], 6)) for k, m, o in todo])


class PriceFeed(threading.Thread):
    """화면용 실시간 시세: 2초마다 현재가, 1분마다 업비트 잔고(평단 포함), 5분마다 체결 내역. 주문·알림 판단은 Engine이 한다."""

    def __init__(self, engine, events, every=2.0):
        super().__init__(daemon=True)
        self.engine, self.events, self.every = engine, events, every
        self.stop_event = engine.stop_event
        self.last_hold = self.last_hist = 0
        self.krw_markets = None
        self.held = []           # 원화마켓이 있는 보유 코인
        self.want_history = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                if self.krw_markets is None:
                    self.krw_markets = {m["market"][4:] for m in fr.get("/market/all") if m["market"].startswith("KRW-")}
                coins = list(dict.fromkeys(fr.COINS + self.engine.grid_tracked() + self.held))
                ts = fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in coins))
                self.events.put(("live", {t["market"][4:]: (t["trade_price"], t["signed_change_rate"] * 100,
                                                            t["signed_change_price"]) for t in ts}))
                api = self.engine.api
                if api and time.time() - self.last_hold > 60:
                    acc = api.call("GET", "/accounts")
                    hold = {a["currency"]: float(a["balance"]) + float(a["locked"]) for a in acc}
                    self.held = [a["currency"] for a in acc if a["currency"] in self.krw_markets
                                 and float(a["balance"]) + float(a["locked"]) > 0]
                    self.events.put(("hold", hold))
                    self.events.put(("accounts", [
                        {"currency": a["currency"], "qty": float(a["balance"]) + float(a["locked"]),
                         "locked": float(a["locked"]), "avg": float(a.get("avg_buy_price") or 0)} for a in acc]))
                    self.last_hold = time.time()
                if api and (time.time() - self.last_hist > 300 or self.want_history.is_set()):
                    self.want_history.clear()
                    self.last_hist = time.time()
                    try:
                        self.events.put(("history", api.closed_orders()))
                    except Exception as e:
                        self.events.put(("history_error", str(e)))
            except Exception:
                pass  # 다음 주기에 다시
            self.stop_event.wait(self.every)


class Engine(threading.Thread):
    def __init__(self, cfg, db, events):
        super().__init__(daemon=True)
        self.cfg, self.db, self.events = cfg, db, events
        self.api = make_api()
        self.stop_event = threading.Event()
        self.commands = queue.Queue()
        self.levels = {}          # coin -> [(이름, 가격)]
        self.prices = {}
        self.alert_state = {}
        self.known_orders = None
        self.proposal = None
        self.dismissed = set()
        self.last_levels = self.last_board = 0
        self.grid_prev = {}       # 자동매매 급변 감지용 직전 가격
        self.grid_capped = {}     # 한도 알림 시각
        self.last_exec = 0

    # ---------- 외부(화면)에서 부르는 것: 명령 큐에 넣고 엔진 스레드가 처리 ----------
    def request(self, cmd, *args):
        self.commands.put((cmd, args))

    def emit(self, *ev):
        self.events.put(ev)

    def alert(self, kind, title, msg):
        self.db.alert(kind, title, msg)
        self.emit("alert", title, msg, kind)

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
        """차트용 캔들. unit: 분(int) 또는 'days'. 결과는 ("candles", key, [(시가, 고가, 저가, 종가)])."""
        cs = fc.candles(unit, coin, count)
        self.emit("candles", key, [(c["opening_price"], c["high_price"], c["low_price"], c["trade_price"]) for c in cs])

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
                           "candles": [(c["opening_price"], c["high_price"], c["low_price"], c["trade_price"]) for c in h4[-48:]],
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
            for coin in self.grid_tracked():
                if self.grid_state(coin).get("pending") and (not g["enabled"] or coin not in self.grid_coins()):
                    try:
                        self.grid_resolve_pending(coin)
                    except Exception as e:
                        self.alert("fail", f"{coin} 주문 확인 오류", str(e))
        if self.cfg["grid"]["enabled"]:
            try:
                self.grid_check_warnings()
            except Exception:
                pass  # 조회 실패 시 다음 시간에 다시
            for coin in self.grid_coins():
                if coin in self.prices:
                    try:
                        self.grid_step(coin, self.prices[coin])
                    except fo.UnknownResult as e:
                        self.alert("fail", f"{coin} 주문 결과 확인 중", f"{e}\n다음 확인 때 업비트에서 조회해 반영합니다 (중복 주문 안 함).")
                    except Exception as e:  # 현금 부족·IP 변경·네트워크 등: 10분 쉬고 재시도 (30초마다 반복 실패 방지)
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
                self.alert("fill", f"{coin} {word} 체결{label}", f"{coin} {word} {price:,.0f}원 × {vol:g} 체결")
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

    def execute(self, proposal_id):
        p = self.proposal
        if not p or p["id"] != proposal_id:
            self.emit("done", ["제안이 바뀌었습니다. 다시 확인하세요."])
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
            need = sum(o["price"] * o["volume"] for k, _, o in todo if k == "place" and o["side"] == "bid")
            freed = sum(o["price"] * o["volume"] for k, _, o in todo if k == "cancel" and o["side"] == "bid")
            if need > krw_free + freed + 1:
                self.emit("done", [f"현금 부족으로 실행하지 않았습니다: 새 매수 주문 {need:,.0f}원 / 주문 가능 {krw_free + freed:,.0f}원"])
                self.alert("fail", "주문 실행 중단 · 현금 부족", f"필요 {need:,.0f}원, 가능 {krw_free + freed:,.0f}원")
                return
        results, count, failed = [], self.db.actions_today(), []
        for kind, market, o in p["todo"]:
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
        if vol > 0:
            px = funds / vol
            if pend["side"] == "bid":
                st.update(qty=st["qty"] + vol, cost=st["cost"] + funds + fee, buys=st["buys"] + 1, ref=px, halved=False)
            else:
                frac = min(vol / st["qty"], 1) if st["qty"] else 1
                st["realized"] += (funds - fee) - st["cost"] * frac
                st.update(qty=max(st["qty"] - vol, 0.0), cost=st["cost"] * (1 - frac), ref=px)
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

    def grid_check_warnings(self):
        """업비트 투자유의·경고 코인은 자동매매에서 막는다 (1시간마다)."""
        if time.time() - getattr(self, "_warn_ts", 0) < 3600:
            return
        self._warn_ts = time.time()
        info = {m["market"][4:]: m for m in fr.get("/market/all?isDetails=true") if m["market"].startswith("KRW-")}
        for coin in self.grid_coins():
            m = info.get(coin)
            ev = (m or {}).get("market_event") or {}
            warn = m is None or m.get("market_warning") == "CAUTION" or ev.get("warning") or \
                any((ev.get("caution") or {}).values())
            st = self.grid_state(coin)
            if warn and not st.get("blocked"):
                st["blocked"] = True
                self.alert("fail", f"{coin} 자동매매 중지", "업비트 투자유의/경고 지정 또는 원화마켓에 없음. 보유분은 그대로 두었습니다.")
            elif not warn and st.get("blocked"):
                st["blocked"] = False
                self.alert("grid", f"{coin} 자동매매 재개", "투자유의 지정이 풀렸습니다.")

    def grid_step(self, coin, price):
        g, st = self.cfg["grid"], self.grid_state(coin)
        if st.get("pending") and self.api and not g["simulate"]:
            self.grid_resolve_pending(coin)
            return  # 이번 주기는 확정만 하고 매매는 다음 주기에
        if self.grid_guard(coin, price):
            return
        unit, drop = g["unit_krw"], g["drop_pct"] / 100
        tag = "[모의] " if g["simulate"] or not self.api else ""
        total_cost = sum(self.grid_state(c)["cost"] for c in self.grid_tracked())  # 목록에서 뺀 보유분도 한도에 포함
        if st["qty"] <= 0:  # 새 사이클 시작
            if total_cost + unit > g["total_max_krw"]:
                return self.grid_cap_alert("total", f"자동매매 전체 원가 {total_cost:,.0f}원 · 전체 한도 {g['total_max_krw']:,}원")
            qty, krw, px, _ = self.grid_trade(coin, "bid", price, unit)
            st.update(qty=qty, cost=krw, buys=1, ref=px, halved=False, realized=0.0)
            self.alert("grid", f"{tag}{coin} 시작 매수", f"{fmtp(px)}원에 {krw:,.0f}원 매수 (1회)")
        else:
            value = st["qty"] * price * (1 - FEE)
            pnl = st["realized"] + value - st["cost"]
            avg = st["cost"] / st["qty"]
            breakeven = avg / (1 - FEE)
            if pnl >= g["profit_krw"]:
                before = st["qty"]
                qty, krw, px, _ = self.grid_trade(coin, "ask", price, before)
                pnl = st["realized"] + krw - st["cost"] * min(qty / before, 1)  # 잔고 부족으로 덜 팔았으면 그만큼 원가만
                st["profit_total"] += pnl
                st["cycles"] += 1
                self.alert("grid", f"{tag}{coin} 익절 {pnl:+,.0f}원",
                           f"{fmtp(px)}원에 전량 매도 · {st['buys']}회 매수 사이클 · 누적 {st['profit_total']:,.0f}원")
                st.update(qty=0.0, cost=0.0, buys=0, ref=None, halved=False, realized=0.0)
            elif (g["half_at_breakeven"] and st["buys"] >= 2 and not st["halved"] and price >= breakeven
                  and st["qty"] / 2 * price >= MIN_SELL_KRW):  # 반씩 나눠도 업비트 최소 주문 이상일 때만
                before = st["qty"]
                qty, krw, px, _ = self.grid_trade(coin, "ask", price, before / 2)
                frac = min(qty / before, 1)  # 실제로 판 비율만큼만 원가를 덜어낸다
                st["realized"] += krw - st["cost"] * frac
                st.update(qty=before - qty, cost=st["cost"] * (1 - frac), halved=True, ref=px)
                self.alert("grid", f"{tag}{coin} 본전 절반 매도", f"{fmtp(px)}원에 {qty:g}개 매도 ({krw:,.0f}원)")
            elif price <= st["ref"] * (1 - drop):
                if st["cost"] + unit > g["max_krw"]:
                    return self.grid_cap_alert(coin, f"{coin} 원가 {st['cost']:,.0f}원 · 코인 한도 {g['max_krw']:,}원")
                if total_cost + unit > g["total_max_krw"]:
                    return self.grid_cap_alert("total", f"자동매매 전체 원가 {total_cost:,.0f}원 · 전체 한도 {g['total_max_krw']:,}원")
                qty, krw, px, _ = self.grid_trade(coin, "bid", price, unit)
                st.update(qty=st["qty"] + qty, cost=st["cost"] + krw, buys=st["buys"] + 1, ref=px, halved=False)
                self.alert("grid", f"{tag}{coin} 물타기 {st['buys']}회",
                           f"{fmtp(px)}원에 {krw:,.0f}원 매수 · 평단 {fmtp(st['cost'] / st['qty'])} · 원가 {st['cost']:,.0f}원")
            else:
                return
        save_config(self.cfg)

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
            tp = (g["profit_krw"] + st["cost"] - st["realized"]) / (q * (1 - FEE)) if q else None
            t = time.time()
            status = ("결과 확인 중" if st.get("pending") else "조회만 · 매매 안 함" if coin not in listed
                      else "투자유의 중지" if st.get("blocked")
                      else f"정지 {int((st['pause_until'] - t) // 60) + 1}분" if st.get("pause_until", 0) > t else "자동매매 중")
            rows.append({"status": status, "listed": coin in listed, "coin": coin, "price": p, "buys": st["buys"], "cost": st["cost"], "qty": q, "avg": avg,
                         "pnl": pnl, "next_buy": st["ref"] * (1 - g["drop_pct"] / 100) if st["ref"] else None,
                         "breakeven": avg / (1 - FEE) if avg and st["buys"] >= 2 and not st["halved"] else None,
                         "tp": tp, "cycles": st["cycles"], "profit_total": st["profit_total"]})
        return rows

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
        if st["qty"] <= 0 or coin not in self.prices:
            self.cfg["grid"]["coins"] = [c for c in self.cfg["grid"]["coins"] if c != coin]
            save_config(self.cfg)
            return
        before = st["qty"]
        qty, krw, px, sim = self.grid_trade(coin, "ask", self.prices[coin], before)
        pnl = st["realized"] + krw - st["cost"] * min(qty / before, 1)
        st["profit_total"] += pnl
        st.update(qty=0.0, cost=0.0, buys=0, ref=None, halved=False, realized=0.0)
        self.cfg["grid"]["coins"] = [c for c in self.cfg["grid"]["coins"] if c != coin]
        save_config(self.cfg)
        self.alert("grid", f"{coin} 청산", f"{fmtp(px)}원에 전량 매도 · 손익 {pnl:+,.0f}원 · 자동매매 목록에서 뺐습니다")

    def emergency_stop(self, cancel_all):
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
            self.known_orders = None
        self.alert("stop", "긴급 정지", "\n".join(msgs))
        self.emit("done", msgs)

    # ---------- 메인 루프 ----------
    def run(self):
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
