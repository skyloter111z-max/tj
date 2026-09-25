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
        "state": {},
    },
}
GRID_BLOCKED = set(fr.COINS)  # 피보나치 코인은 자동매매 금지
FEE = 0.0005


def now():
    return datetime.datetime.now(KST)


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        cfg.update({k: v for k, v in saved.items() if k in DEFAULTS and k != "grid"})
        cfg["grid"].update(saved.get("grid", {}))
        for c in fr.COINS:
            cfg["progress"].setdefault(c, {"sell_done": 0, "buy_done": 0})
    apply_config(cfg)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
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
    """화면용 실시간 시세: 2초마다 현재가, 1분마다 보유 수량. 주문·알림 판단은 Engine이 한다."""

    def __init__(self, engine, events, every=2.0):
        super().__init__(daemon=True)
        self.engine, self.events, self.every = engine, events, every
        self.stop_event = engine.stop_event
        self.last_hold = 0

    def run(self):
        while not self.stop_event.is_set():
            try:
                coins = fr.COINS + [c for c in self.engine.grid_coins() if c not in fr.COINS]
                ts = fr.get("/ticker?markets=" + ",".join(f"KRW-{c}" for c in coins))
                self.events.put(("live", {t["market"][4:]: (t["trade_price"], t["signed_change_rate"] * 100)
                                          for t in ts}))
                api = self.engine.api
                if api and time.time() - self.last_hold > 60:
                    acc = api.call("GET", "/accounts")
                    hold = {a["currency"]: float(a["balance"]) + float(a["locked"]) for a in acc}
                    self.events.put(("hold", hold))
                    self.last_hold = time.time()
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

    def check_drift(self):
        """고정 레벨과 지금 계산이 달라졌는지 (예: 일봉 고점 갱신). 알림만 하고 바꾸지는 않는다."""
        changed = []
        for coin in fr.COINS:
            fresh, lv, pg = fo.compute_levels(coin), self.cfg["levels"][coin], self.cfg["progress"][coin]
            pairs = list(zip(lv["buys"][pg["buy_done"]:], fresh["buys"][pg["buy_done"]:]))
            if any(abs(a / b - 1) > 0.005 for a, b in pairs):
                changed.append(coin)
        sig = ",".join(changed)
        if changed and sig != getattr(self, "_drift_sig", ""):
            self.alert("levels", "레벨 변경 감지",
                       f"{sig}: 기준점이 바뀌었습니다. 주봉 마감 규칙을 확인한 뒤 '레벨 재계산'을 누르세요.")
        self._drift_sig = sig
        self.last_levels = time.time()

    def refresh_board(self):
        board = {"_levels_at": ", ".join(f"{c} {v.get('at', '')}" for c, v in self.cfg["levels"].items())}
        for coin in fr.COINS:
            h4, h1 = fc.candles(240, coin, 60), fc.candles(60, coin, 60)
            board[coin] = {"price": self.prices.get(coin), "levels": self.levels.get(coin, []),
                           "trend": f"4시간봉 {fc.trend(h4)}\n1시간봉 {fc.trend(h1)}",
                           "change24": fc.pct(h1[-1]["trade_price"], h1[-24]["opening_price"])}
        dca = sum(self.cfg["dca_daily"].values())
        if self.api and dca:
            krw = self.api.holdings()[1]
            board["_cash"] = f"주문 가능 현금 {krw:,.0f}원 · 모으기 하루 {dca:,}원 → 약 {krw / dca:,.0f}일분"
        elif dca:
            board["_cash"] = f"모으기 하루 {dca:,}원 (한 달 약 {dca * 30:,}원)"
        self.last_board = time.time()
        self.emit("board", board)

    # ---------- 감시 ----------
    def check_prices(self):
        coins = fr.COINS + [c for c in self.grid_coins() if c not in fr.COINS]
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
        if self.cfg["grid"]["enabled"]:
            for coin in self.grid_coins():
                if coin in self.prices:
                    try:
                        self.grid_step(coin, self.prices[coin])
                    except Exception as e:
                        self.alert("grid", f"{coin} 자동매매 오류", str(e))
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

    # ---------- 제안·실행 ----------
    def make_proposal(self, reason, force=False):
        if self.cfg["mode"] != "semi" and not force:
            return
        holdings = self.api.holdings()[0] if self.api else fr.HOLDINGS
        rows, todo = fo.diff(self.api, holdings, replace=True, progress=self.cfg["progress"],
                             tol=self.cfg["volume_tol_pct"] / 100, levels=self.cfg["levels"])
        key = todo_key(todo)
        if not todo:
            self.proposal = None
            self.emit("proposal", {"reason": reason, "rows": rows, "todo": [], "id": None})
            return
        if not force and key in self.dismissed:
            return
        cur = self.db.conn.execute("INSERT INTO proposals (ts, reason, todo, status) VALUES (?,?,?,?)",
                                   (now().isoformat(), reason, key, "pending"))
        self.db.conn.commit()
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
        results, count = [], self.db.actions_today()
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
                            self.api.place(market, o["side"], o["volume"], o["price"])
                        count += 1
                    res = "ok"
                except RuntimeError as e:
                    res = f"실패: {e}"
            word = "취소" if kind == "cancel" else "주문"
            side = "매도" if o["side"] == "ask" else "매수"
            self.db.add("actions", now().isoformat(), int(sim), kind, market, o["side"], o["price"], o["volume"], res)
            results.append(f"{tag}{word} {market} {side} {o['price']:,.0f} × {o['volume']:g} → {res}")
        self.db.conn.execute("UPDATE proposals SET status=? WHERE id=?", ("simulated" if sim else "executed", p["id"]))
        self.db.conn.commit()
        self.proposal = None
        self.known_orders = None  # 방금 취소한 주문을 체결로 오인하지 않도록 다시 읽는다
        self.emit("done", results)
        if not sim:
            self.make_proposal("실행 후 확인")

    def dismiss(self, proposal_id):
        if self.proposal and self.proposal["id"] == proposal_id:
            self.dismissed.add(self.proposal["key"])
            self.db.conn.execute("UPDATE proposals SET status='dismissed' WHERE id=?", (proposal_id,))
            self.db.conn.commit()
            self.proposal = None
            self.emit("proposal", None)

    # ---------- 자동매매 (물타기 그리드) ----------
    def grid_coins(self):
        return [c for c in self.cfg["grid"]["coins"] if c not in GRID_BLOCKED]

    def grid_state(self, coin):
        return self.cfg["grid"]["state"].setdefault(coin, {
            "qty": 0.0, "cost": 0.0, "buys": 0, "ref": None, "halved": False,
            "realized": 0.0, "cycles": 0, "profit_total": 0.0})

    def grid_trade(self, coin, side, price, amount):
        """side=bid: amount는 원화, side=ask: amount는 수량. (수량, 원화[매수는 수수료 포함 지출, 매도는 수수료 뺀 수입])"""
        g = self.cfg["grid"]
        sim = g["simulate"] or not self.api
        market = f"KRW-{coin}"
        if sim:
            qty, krw = (amount * (1 - FEE) / price, amount) if side == "bid" else (amount, amount * price * (1 - FEE))
        else:
            r = self.api.market_buy(market, amount) if side == "bid" else self.api.market_sell(market, amount)
            vol, funds, fee = self.api.filled(r["uuid"])
            qty, krw = (vol, funds + fee) if side == "bid" else (vol, funds - fee)
            price = funds / vol if vol else price
        self.db.add("grid_trades", now().isoformat(), int(sim), coin, side, price, qty, krw, "")
        return qty, krw, price, sim

    def grid_step(self, coin, price):
        g, st = self.cfg["grid"], self.grid_state(coin)
        unit, drop = g["unit_krw"], g["drop_pct"] / 100
        tag = "[모의] " if g["simulate"] or not self.api else ""
        if st["qty"] <= 0:  # 새 사이클 시작
            qty, krw, px, _ = self.grid_trade(coin, "bid", price, unit)
            st.update(qty=qty, cost=krw, buys=1, ref=px, halved=False, realized=0.0)
            self.alert("grid", f"{tag}{coin} 시작 매수", f"{px:,.4g}원에 {krw:,.0f}원 매수 (1회)")
        else:
            value = st["qty"] * price * (1 - FEE)
            pnl = st["realized"] + value - st["cost"]
            avg = st["cost"] / st["qty"]
            breakeven = avg / (1 - FEE)
            if pnl >= g["profit_krw"]:
                qty, krw, px, _ = self.grid_trade(coin, "ask", price, st["qty"])
                pnl = st["realized"] + krw - st["cost"]
                st["profit_total"] += pnl
                st["cycles"] += 1
                self.alert("grid", f"{tag}{coin} 익절 +{pnl:,.0f}원",
                           f"{px:,.4g}원에 전량 매도 · {st['buys']}회 매수 사이클 · 누적 {st['profit_total']:,.0f}원")
                st.update(qty=0.0, cost=0.0, buys=0, ref=None, halved=False, realized=0.0)
            elif g["half_at_breakeven"] and st["buys"] >= 2 and not st["halved"] and price >= breakeven:
                half = st["qty"] / 2
                qty, krw, px, _ = self.grid_trade(coin, "ask", price, half)
                st["realized"] += krw - st["cost"] / 2
                st.update(qty=st["qty"] - qty, cost=st["cost"] / 2, halved=True, ref=px)
                self.alert("grid", f"{tag}{coin} 본전 절반 매도", f"{px:,.4g}원에 {qty:g}개 매도 ({krw:,.0f}원)")
            elif price <= st["ref"] * (1 - drop):
                if st["cost"] + unit > g["max_krw"]:
                    if not st.get("capped"):
                        st["capped"] = True
                        self.alert("grid", f"{coin} 투입 한도 도달", f"원가 {st['cost']:,.0f}원 · 한도 {g['max_krw']:,}원. 추가 매수 멈춤")
                    return
                qty, krw, px, _ = self.grid_trade(coin, "bid", price, unit)
                st.update(qty=st["qty"] + qty, cost=st["cost"] + krw, buys=st["buys"] + 1, ref=px, halved=False, capped=False)
                self.alert("grid", f"{tag}{coin} 물타기 {st['buys']}회",
                           f"{px:,.4g}원에 {krw:,.0f}원 매수 · 평단 {st['cost'] / st['qty']:,.4g} · 원가 {st['cost']:,.0f}원")
            else:
                return
        save_config(self.cfg)

    def grid_view(self):
        g, rows = self.cfg["grid"], []
        for coin in self.grid_coins():
            st, p = self.grid_state(coin), self.prices.get(coin)
            if not p:
                continue
            q = st["qty"]
            avg = st["cost"] / q if q else None
            pnl = st["realized"] + q * p * (1 - FEE) - st["cost"] if q else 0
            # 익절가: realized + q*x*(1-FEE) - cost = profit
            tp = (g["profit_krw"] + st["cost"] - st["realized"]) / (q * (1 - FEE)) if q else None
            rows.append({"coin": coin, "price": p, "buys": st["buys"], "cost": st["cost"], "qty": q, "avg": avg,
                         "pnl": pnl, "next_buy": st["ref"] * (1 - g["drop_pct"] / 100) if st["ref"] else None,
                         "breakeven": avg / (1 - FEE) if avg and st["buys"] >= 2 and not st["halved"] else None,
                         "tp": tp, "cycles": st["cycles"], "profit_total": st["profit_total"]})
        return rows

    def grid_liquidate(self, coin):
        st = self.grid_state(coin)
        if st["qty"] <= 0 or coin not in self.prices:
            return
        qty, krw, px, sim = self.grid_trade(coin, "ask", self.prices[coin], st["qty"])
        pnl = st["realized"] + krw - st["cost"]
        st["profit_total"] += pnl
        st.update(qty=0.0, cost=0.0, buys=0, ref=None, halved=False, realized=0.0)
        self.cfg["grid"]["coins"] = [c for c in self.cfg["grid"]["coins"] if c != coin]
        save_config(self.cfg)
        self.alert("grid", f"{coin} 청산", f"{px:,.4g}원에 전량 매도 · 손익 {pnl:+,.0f}원 · 자동매매 목록에서 뺐습니다")

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
                elif time.time() - self.last_levels > 3600:
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
