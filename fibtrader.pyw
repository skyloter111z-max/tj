"""FibTrader: 피보나치 플랜 감시·알림·반자동 주문 (트레이 + 대시보드).

처음 한 번: install.bat 실행 (라이브러리·글꼴 설치 + 바탕화면 아이콘)
실행: 바탕화면 FibTrader 아이콘 더블클릭
창을 닫으면 트레이로 숨고, 트레이 아이콘 오른쪽 클릭 → 종료로 끝낸다.
화면 디자인: 다크 테마, 현황 1a(3열 사다리), 투자내역 2a (디자인 스펙 md 기준)
"""
import ctypes
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
if sys.stdout is None:  # pythonw엔 콘솔이 없음
    sys.stdout = sys.stderr = open(os.path.join(HERE, "fibtrader.log"), "a", encoding="utf-8", buffering=1)

import fib_recalc as fr  # noqa: E402
import fibtrader_core as core  # noqa: E402
import fibtrader_theme as T  # noqa: E402
import fibtrader_widgets as W  # noqa: E402

WIN = sys.platform == "win32"
try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:  # 라이브러리가 없거나 트레이를 못 쓰는 환경이면 창만 띄운다
    pystray = None

POPUP_KINDS = {"hit", "fill", "proposal", "levels", "stop", "drift", "fail"}  # 근접(near)은 소리·트레이 알림만


SHOW_EVENT = "FibTraderShowEvent"  # 두 번째 실행이 이미 떠 있는 창을 앞으로 부르는 신호
MB_TOP = 0x40000 | 0x10000          # MB_TOPMOST | MB_SETFOREGROUND: 안내창이 다른 창 뒤에 숨지 않게


def kernel32():
    k = ctypes.windll.kernel32
    k.CreateEventW.restype = k.OpenEventW.restype = ctypes.c_void_p
    k.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
    k.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    k.SetEvent.argtypes = k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    return k


def single_instance():
    if not WIN:
        return True
    ctypes.windll.kernel32.CreateMutexW(None, False, "FibTraderSingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def signal_existing():
    """이미 실행 중인 FibTrader에 '창 보여줘' 신호. 성공하면 True (예전 버전은 신호를 못 받아 False)."""
    k = kernel32()
    h = k.OpenEventW(0x0002, 0, SHOW_EVENT)  # EVENT_MODIFY_STATE
    if not h:
        return False
    k.SetEvent(h)
    k.CloseHandle(h)
    return True


def message(text, title="FibTrader", icon=0x40):
    if WIN:
        ctypes.windll.user32.MessageBoxW(0, text, title, icon | MB_TOP)
    else:
        print(title, text)


def make_shortcut(folder, name="FibTrader.lnk"):
    """pythonw로 fibtrader.pyw를 실행하는 바로가기(.lnk) 생성. folder: 'Desktop' 또는 'Startup'."""
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    script = os.path.join(HERE, "fibtrader.pyw")
    ps = (f"$d=[Environment]::GetFolderPath('{folder}');"
          f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d '{name}'));"
          f"$s.TargetPath='{pyw}';$s.Arguments='\"{script}\"';$s.WorkingDirectory='{HERE}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def startup_dir():
    return os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")


def fmt(v, coin=None):
    return T.fmtp(v)


def lab(parent, text="", font="kr", fg=T.TEXT, bg=T.PANEL, **kw):
    return tk.Label(parent, text=text, font=T.F[font], fg=fg, bg=bg, **kw)


class App:
    def __init__(self):
        self.cfg = core.load_config()
        self.cfg.setdefault("ui", {"charts_open": [], "inv_charts_open": [], "near_highlight_pct": 5})
        self.db = core.DB()
        self.events = queue.Queue()
        self.ui_calls = queue.Queue()
        self.engine = core.Engine(self.cfg, self.db, self.events)
        self.proposal = None
        self.prices = {}
        self.board = {}
        self.live = {}      # coin -> (현재가, 전일 대비 %, 전일 대비 금액)
        self.hold = {}      # currency -> 보유 수량 (주문에 묶인 것 포함)
        self.accounts = []  # 업비트 잔고 (평단 포함)
        self.open_orders = {c: [] for c in fr.COINS}
        self.status_text = ""

        T.load_private_fonts()
        self.root = tk.Tk()
        self.root.title("FibTrader")
        self.root.geometry("1440x900")
        self.root.minsize(1280, 800)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        T.setup_fonts(self.root)
        T.apply_ttk(self.root)

        # 2-1 상단바: 브랜드 | 탭 | (빈칸) | 상태 태그 | API 상태 | 긴급 정지
        top = tk.Frame(self.root, bg=T.PANEL, height=40)
        top.pack(fill="x")
        brand = lab(top, "FIBTRADER", "brand", padx=18)
        brand.pack(side="left", fill="y")
        tk.Frame(top, bg=T.DIVIDER, width=1).pack(side="left", fill="y", pady=8)
        tabbar = tk.Frame(top, bg=T.PANEL)
        tabbar.pack(side="left", fill="y")
        right = tk.Frame(top, bg=T.PANEL)
        right.pack(side="right", fill="y", padx=(0, 12))
        self.tags = {}
        for key in ("mode", "sim"):
            t = lab(right, "", "tag", fg=T.ACCENT, padx=6, pady=1, highlightthickness=1, highlightbackground=T.ACCENT)
            t.pack(side="left", padx=3, pady=10)
            self.tags[key] = t
        self.status_dot = lab(right, "●", "num_xs", fg=T.DOWN, padx=0)
        self.status_dot.pack(side="left", padx=(12, 4))
        self.status = lab(right, "시작 중…", "kr_s", fg=T.MUTED)
        self.status.pack(side="left", padx=(0, 14))
        T.Btn(right, "긴급 정지", self.emergency, "danger").pack(side="left", pady=5)
        tk.Frame(self.root, bg=T.DIVIDER, height=1).pack(fill="x")

        # 2-2 시세 티커
        self.ticker = W.Ticker(self.root)
        self.ticker.pack(fill="x")
        tk.Frame(self.root, bg=T.DIVIDER, height=1).pack(fill="x")
        # 2-3 모의 모드 배너
        self.sim_banner = lab(self.root, "모의 모드 · 승인해도 실제 주문은 나가지 않습니다", "kr_s", fg=T.ACCENT_200,
                              bg=T.BANNER_BG, height=1, pady=3)

        self.nb = W.Tabs(self.root, tabbar)
        self.nb.pack(fill="both", expand=True)
        self.build_board(self.nb)
        self.build_invest(self.nb)
        self.build_grid(self.nb)
        self.build_orders(self.nb)
        self.build_logs(self.nb)
        self.build_settings(self.nb)
        self.refresh_chrome()

        self.icon = None
        if pystray:
            threading.Thread(target=self.run_tray, daemon=True).start()
        if WIN:
            threading.Thread(target=self.watch_show, daemon=True).start()
        self.engine.start()
        self.feed = core.PriceFeed(self.engine, self.events)
        self.feed.start()
        self.root.after(300, self.pump)

    def watch_show(self):
        """바탕화면 아이콘을 또 누르면(두 번째 실행) 이 창을 앞으로 가져온다."""
        k = kernel32()
        h = k.CreateEventW(None, 0, 0, SHOW_EVENT)
        while h and not self.engine.stop_event.is_set():
            if k.WaitForSingleObject(h, 1000) == 0:  # WAIT_OBJECT_0
                self.ui_calls.put(self.show)

    # ---------------- 트레이 ----------------
    def tray_image(self, color):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle((4, 4, 60, 60), fill=color)
        d.text((24, 18), "F", fill="white")
        return img

    def run_tray(self):
        self.img_ok, self.img_alert = self.tray_image((89, 128, 166)), self.tray_image((240, 113, 106))
        menu = pystray.Menu(pystray.MenuItem("열기", lambda *_: self.ui_calls.put(self.show), default=True),
                            pystray.MenuItem("긴급 정지", lambda *_: self.ui_calls.put(self.emergency)),
                            pystray.MenuItem("종료", lambda *_: self.ui_calls.put(self.quit)))
        self.icon = pystray.Icon("FibTrader", self.img_ok, "FibTrader", menu)
        self.icon.run()

    def tray_alert(self, title, msg):
        if not self.icon:
            return
        self.icon.icon = self.img_alert
        try:
            self.icon.notify(msg[:250], title)
        except Exception:
            pass

    # ---------------- 창 ----------------
    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if self.icon:
            self.icon.icon = self.img_ok

    def hide(self):
        if self.icon:
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        self.closing = True
        self.engine.stop_event.set()
        if self.icon:
            self.icon.stop()
        self.root.destroy()

    def popup(self, title, msg):
        w = tk.Toplevel(self.root, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        w.title(title)
        w.attributes("-topmost", True)
        lab(w, title, "kr_title").pack(padx=20, pady=(16, 6), anchor="w")
        lab(w, msg, "kr", justify="left", wraplength=480).pack(padx=20, pady=4, anchor="w")
        row = tk.Frame(w, bg=T.PANEL)
        row.pack(pady=14, padx=20, anchor="e")
        T.Btn(row, "대시보드 열기", lambda: (w.destroy(), self.show())).pack(side="left", padx=4)
        T.Btn(row, "확인", w.destroy, "primary").pack(side="left", padx=4)

    def refresh_chrome(self):
        """상단 태그·모의 배너를 설정 상태에 맞춘다."""
        self.tags["mode"].config(text="반자동" if self.cfg["mode"] == "semi" else "알림만")
        sim = self.cfg["simulate"] or not self.engine.api
        self.tags["sim"].config(text="모의" if sim else "실전",
                                fg=T.ACCENT if sim else T.UP, highlightbackground=T.ACCENT if sim else T.UP)
        if sim and not self.sim_banner.winfo_ismapped():
            self.sim_banner.pack(fill="x", before=self.nb)
        elif not sim and self.sim_banner.winfo_ismapped():
            self.sim_banner.pack_forget()

    # ---------------- ① 현황 (1a: 3열 사다리) ----------------
    def build_board(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "현황")
        self.board_tab = f
        # 레벨 변경 알림판 (유의적 변화 시에만)
        self.drift_box = tk.Frame(f, bg=T.PANEL, highlightthickness=1, highlightbackground=T.UP)
        self.drift_msg = lab(self.drift_box, "", "kr", justify="left", anchor="w")
        self.drift_msg.pack(side="left", fill="x", expand=True, padx=16, pady=10)
        db = tk.Frame(self.drift_box, bg=T.PANEL)
        db.pack(side="right", padx=12, pady=8)
        T.Btn(db, "현행 기준으로 바꾸기", self.apply_drift, "primary").pack(side="left", padx=3)
        T.Btn(db, "BTC·ETH·XRP 예약 전체 취소", lambda: self.cancel_coin(None)).pack(side="left", padx=3)
        T.Btn(db, "나중에", lambda: self.drift_box.pack_forget()).pack(side="left", padx=3)
        self.auto_drift = tk.BooleanVar(value=self.cfg.get("auto_apply_drift", False))
        tk.Checkbutton(db, text="앞으로 자동 반영", variable=self.auto_drift, command=self.toggle_auto_drift,
                       bg=T.PANEL, fg=T.TEXT, selectcolor=T.GROUND, activebackground=T.PANEL, activeforeground=T.TEXT,
                       font=T.F["kr_s"]).pack(side="left", padx=6)

        # 2-4 하단 요약바
        self.sumbar = W.SummaryBar(f, [("coins", "코인 평가 (BTC·ETH·XRP)"), ("cash", "현금"), ("total", "총자산"),
                                       ("free", "주문 가능 현금"), ("dca", "모으기"), ("lvl", "레벨 기준 시각")])
        self.sumbar.pack(side="bottom", fill="x")
        self.drift_btn = T.Btn(self.sumbar, "레벨 변화 지금 확인", self.check_drift_now)
        self.drift_btn.pack(side="right", padx=16)

        self.cards_wrap = tk.Frame(f, bg=T.GROUND)
        self.cards_wrap.pack(fill="both", expand=True, padx=18, pady=18)
        self.cards = {}
        for i, coin in enumerate(fr.COINS):
            self.cards_wrap.columnconfigure(i, weight=1, uniform="card")
            self.cards[coin] = self.build_card(self.cards_wrap, coin, i)
        self.cards_wrap.rowconfigure(0, weight=1)

    def build_card(self, parent, coin, col):
        box = tk.Frame(parent, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 9, 0 if col == 2 else 9))
        inner = tk.Frame(box, bg=T.PANEL)
        inner.pack(fill="both", expand=True, padx=16, pady=16)
        c = {"box": box}
        head = tk.Frame(inner, bg=T.PANEL)
        head.pack(fill="x")
        lab(head, coin, "sym").pack(side="left")
        c["chart_btn"] = T.Btn(head, "차트 ▾", lambda: self.toggle_card_chart(coin), "ghost")
        c["chart_btn"].pack(side="right")
        c["state"] = lab(head, "", "kr_s", fg=T.MUTED)
        c["state"].pack(side="right", padx=8)
        prow = tk.Frame(inner, bg=T.PANEL)
        prow.pack(fill="x", pady=(6, 0))
        c["price"] = lab(prow, "-", "price")
        c["price"].pack(side="left")
        c["chg"] = lab(prow, "", "chg")
        c["chg"].pack(side="left", padx=(10, 0), anchor="s", pady=(0, 7))
        c["hold"] = lab(inner, "", "kr_s", fg=T.MUTED, anchor="w")
        c["hold"].pack(fill="x", pady=(2, 10))
        # 버튼 행·지표를 먼저 아래에 붙여 두고(공간 우선), 남는 높이에 사다리 표
        btns = tk.Frame(inner, bg=T.PANEL)
        btns.pack(side="bottom", fill="x", pady=(14, 0))
        T.Btn(btns, "선택 취소", lambda: self.cancel_selected(coin)).pack(side="left")
        T.Btn(btns, "전체 취소", lambda: self.cancel_coin(coin)).pack(side="left", padx=6)
        T.Btn(btns, "플랜대로 다시 걸기", lambda: self.replan_coin(coin), "primary").pack(side="right")
        c["ind"] = []
        rows = [tk.Frame(inner, bg=T.PANEL) for _ in range(2)]
        for r in reversed(rows):
            r.pack(side="bottom", fill="x", pady=(8, 0))
        for r in rows:
            parts = [lab(r, "", "num_s", fg=T.MUTED) for _ in range(4)]
            for j, p in enumerate(parts):
                if j:
                    lab(r, "|", "num_s", fg=T.DIVIDER).pack(side="left", padx=4)
                p.pack(side="left")
            c["ind"].append(parts)
        c["chart"] = W.Candles(inner, height=150)
        c["ladder"] = W.Ladder(inner)
        c["ladder"].pack(fill="x", anchor="n")
        if coin in self.cfg["ui"]["charts_open"]:
            self.root.after(10, lambda: self.show_card_chart(coin, True))
        return c

    def toggle_card_chart(self, coin):
        opened = coin in self.cfg["ui"]["charts_open"]
        self.show_card_chart(coin, not opened)
        lst = [x for x in self.cfg["ui"]["charts_open"] if x != coin] + ([] if opened else [coin])
        self.cfg["ui"]["charts_open"] = lst
        core.save_config(self.cfg)

    def show_card_chart(self, coin, on):
        c = self.cards[coin]
        if on:
            c["chart"].pack(fill="x", pady=(0, 10), before=c["ladder"])
            c["chart_btn"].config(text="차트 ▴")
        else:
            c["chart"].pack_forget()
            c["chart_btn"].config(text="차트 ▾")
        self.render_board()

    def ladder_rows(self, coin):
        """레벨 8행 + 예약 주문을 한 표로 (같은 가격의 주문은 레벨 행에 합침)."""
        p = self.prices.get(coin)
        lv = self.cfg.get("levels", {}).get(coin)
        if not lv or not p:
            return []
        pg = self.cfg["progress"][coin]
        near = self.cfg["ui"].get("near_highlight_pct", 5)
        hold = self.hold.get(coin, 0.0)
        done_w = sum(w for _, w in fr.SELL_STEPS[:pg["sell_done"]])
        base = hold / (1 - done_w) if done_w < 1 else 0
        budget = self.cfg["buy_budget"] * self.cfg["buy_split"][coin]
        orders = list(self.open_orders.get(coin, []))
        rows = []

        def attach(row, side):
            m = next((o for o in orders if o["side"] == side and abs(o["price"] - row["price"]) < 1e-9), None)
            if m:
                orders.remove(m)
                row.update(uuid=m["uuid"], qty=m["volume"], amt=m["price"] * m["volume"])
            return row

        for i, ((name, w), price) in enumerate(zip(fr.SELL_STEPS, lv["sells"])):
            done = i < pg["sell_done"]
            rows.append(attach({"kind": "sell", "name": f"{name} 매도" + (" ✓" if done else ""),
                                "sub": "체결" if done else f"{w * 100:g}%", "price": price,
                                "qty": base * w, "amt": base * w * price, "color": T.MUTED if done else T.DOWN}, "ask"))
        for i, ((r, w), price) in enumerate(zip(fr.BUY_STEPS, lv["buys"])):
            done = i < pg["buy_done"]
            q = budget * w / price
            rows.append(attach({"kind": "buy", "name": f"{i + 1}차 매수" + (" ✓" if done else ""),
                                "sub": "체결" if done else f"{r * 100:g}% · {w * 100:g}%", "price": price,
                                "qty": q, "amt": q * price, "color": T.MUTED if done else T.UP}, "bid"))
        rows.append({"kind": "stop", "name": "매수 중단선", "sub": "78.6%", "price": lv["stop"], "color": T.MUTED})
        for o in orders:  # 플랜 가격과 다른 예약 주문은 따로 한 줄
            ask = o["side"] == "ask"
            rows.append({"kind": "order", "name": "예약 매도" if ask else "예약 매수", "sub": "플랜 밖", "price": o["price"],
                         "uuid": o["uuid"], "qty": o["volume"], "amt": o["price"] * o["volume"],
                         "color": T.DOWN if ask else T.UP})
        for r in rows:
            r["pct"] = (r["price"] / p - 1) * 100
            r["near"] = bool(near) and r["kind"] in ("sell", "buy", "order") and abs(r["pct"]) <= near
        rows.append({"kind": "now", "name": "현재가", "price": p, "color": T.TEXT, "bold": True})
        rows.sort(key=lambda r: -r["price"])
        return rows

    def render_board(self):
        total = 0.0
        for coin, c in self.cards.items():
            p = self.prices.get(coin)
            live = self.live.get(coin)
            ch = live[1] if live else 0
            c["price"].config(text=T.fmtp(p) if p else "-", fg=T.chg_color(ch) if live else T.TEXT)
            if live:
                c["chg"].config(fg=T.chg_color(ch), text=f"{T.arrow(live[2])}{T.fmtp(abs(live[2]))}  {ch:+.2f}%")
            pg = self.cfg["progress"][coin]
            c["state"].config(text=f"매도 {pg['sell_done']}/3 · 매수 {pg['buy_done']}/3 체결")
            q = self.hold.get(coin)
            if q is not None and p:
                total += q * p
                c["hold"].config(text=f"보유 {T.fmtq(q)} {coin}  ·  평가 {q * p:,.0f}원")
            chart_on = coin in self.cfg["ui"]["charts_open"]
            rows = self.ladder_rows(coin)
            c["ladder"].set_rows(rows, rh=31 if chart_on else 40)
            if chart_on:  # 표가 최소 행 높이(24)로도 안 들어가면 모자란 만큼 차트를 줄인다 (최소 60)
                need = W.Ladder.HEAD + len(rows) * 24
                have = c["ladder"].winfo_height()
                cur = int(c["chart"].cget("height"))
                want = cur - (need - have) if have > 1 and need > have else min(150, cur + max(0, have - need - 4))
                want = max(60, min(150, want))
                if want != cur:
                    c["chart"].config(height=want)
            b = self.board.get(coin, {})
            for parts, ind in zip(c["ind"], b.get("ind", [])):
                label, side, dist, slope, rsi = ind
                parts[0].config(text=f"{label} MA20", fg=T.MUTED)
                parts[1].config(text=f"{side} {dist:+.1f}%", fg=T.UP if side == "위" else T.DOWN)
                parts[2].config(text=f"기울기 {slope:+.2f}%", fg=T.TEXT)
                parts[3].config(text=f"RSI {rsi:.0f}", fg=T.TEXT)
            if chart_on and b.get("candles"):
                lv = self.cfg.get("levels", {}).get(coin, {})
                pg_s, pg_b = pg["sell_done"], pg["buy_done"]
                s1 = lv.get("sells", [None] * 3)[pg_s] if pg_s < len(lv.get("sells", [])) else None
                b1 = lv.get("buys", [None] * 3)[pg_b] if pg_b < len(lv.get("buys", [])) else None
                cs = list(b["candles"])
                if p and cs:  # 마지막 봉은 실시간 가격으로
                    o, h, l, _ = cs[-1]
                    cs[-1] = (o, max(h, p), min(l, p), p)
                c["chart"].set(cs, [(f"{pg_s + 1}차 매도", s1, T.DOWN, False), ("현재가", p, T.LINE_NOW, True),
                                    (f"{pg_b + 1}차 매수", b1, T.UP, False)], "4h · 48봉")
        krw = self.hold.get("KRW")
        self.sumbar.set("coins", T.fmtk(total) if total else "-", "원")
        self.sumbar.set("cash", T.fmtk(krw) if krw is not None else "-", "원")
        self.sumbar.set("total", T.fmtk(total + krw) if krw is not None else "-", "원")
        free = self.board.get("_krw_free")
        self.sumbar.set("free", T.fmtk(free) if free is not None else "-", "원")
        dca = self.board.get("_dca", sum(self.cfg["dca_daily"].values()))
        days = f"약 {free / dca:,.0f}" if free is not None and dca else "-"
        self.sumbar.set("dca", days, "일분", label=f"모으기 하루 {dca:,}원")
        at = self.board.get("_levels_at", "")
        self.sumbar.set("lvl", at[5:] if len(at) > 5 else at or "-")

    def render_strip(self, data):
        self.live.update(data)
        for coin in fr.COINS:
            if coin in data:
                self.prices[coin] = data[coin][0]
        grid = [c for c in self.engine.grid_tracked() if c not in fr.COINS]
        held = [a["currency"] for a in self.accounts if a["currency"] in self.live and a["qty"] > 0
                and a["currency"] not in fr.COINS and a["currency"] not in grid]
        pick = lambda cs: [(c, self.live[c][0], self.live[c][1]) for c in cs if c in self.live]  # noqa: E731
        groups = [("피보나치", pick(fr.COINS)), ("자동매매", pick(grid))]
        if self.nb.index() == 1:  # 투자내역에서는 보유 코인도
            groups.append(("보유", pick(held)))
        self.ticker.set(groups)
        if self.icon:
            self.icon.title = "\n".join(f"{c} {v[0]:,.0f} ({v[1]:+.2f}%)" for c, v in data.items() if c in fr.COINS)

    def render_orders(self, by_coin):
        self.open_orders = by_coin
        self.render_board()

    def render_drift(self, drift):
        if not drift:
            self.drift_box.pack_forget()
            return
        lines = ["⚠ 피보나치 금액이 유의적으로 바뀌었습니다 (0.5% 이상)"]
        for coin, ch in drift.items():
            lines.append(f"{coin}: " + " · ".join(f"{n} {a:,.0f}→{b:,.0f} ({(b / a - 1) * 100:+.1f}%)" for n, a, b in ch))
        self.drift_msg.config(text="\n".join(lines))
        if not self.drift_box.winfo_ismapped():
            self.drift_box.pack(fill="x", padx=18, pady=(18, 0), before=self.cards_wrap)

    def check_drift_now(self):
        self.drift_btn.config(text="확인 중…")
        self.engine.request("check_drift", True)

    def show_drift_report(self, report, drift):
        """[레벨 변화 지금 확인] 결과 창: 코인별 기준점 + 고정 레벨 vs 지금 계산."""
        self.drift_btn.config(text="레벨 변화 지금 확인")
        w = tk.Toplevel(self.root, bg=T.PANEL)
        w.title("피보나치 레벨 확인")
        w.attributes("-topmost", True)
        n = sum(len(v) for v in drift.values())
        head = "변화 없음 — 걸어 둔 레벨이 지금 계산과 같습니다" if not n else f"⚠ {n}개 레벨이 0.5% 넘게 달라졌습니다"
        lab(w, head, "kr_title", fg=T.TEXT if not n else T.UP).pack(anchor="w", padx=20, pady=(16, 4))
        lab(w, "지금 레벨 = 설정에 고정된 가격(예약 주문 기준) · 새 계산 = 방금 업비트 캔들로 다시 계산한 가격",
            "kr_s", fg=T.MUTED).pack(anchor="w", padx=20, pady=(0, 10))
        for coin, r in report.items():
            box = tk.Frame(w, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
            box.pack(fill="x", padx=20, pady=4)
            lab(box, f"{coin}   현재가 {T.fmtp(r['price'])}", "kr_b").pack(anchor="w", padx=12, pady=(8, 2))
            lab(box, f"기준점  주봉 고점 {T.fmtp(r['H_w'])} ({r['H_w_date']}) · 저점 {T.fmtp(r['L'])} ({r['L_date']}) · "
                     f"일봉 고점 {T.fmtp(r['H_d'])} ({r['H_d_date']})", "kr_s", fg=T.MUTED).pack(anchor="w", padx=12)
            g = tk.Frame(box, bg=T.PANEL)
            g.pack(fill="x", padx=12, pady=(6, 10))
            for j, h in enumerate(("구분", "지금 레벨", "새 계산", "차이")):
                lab(g, h, "kr_xs", fg=T.MUTED, anchor="e" if j else "w").grid(row=0, column=j, sticky="ew", padx=8)
            for i, (name, a, b) in enumerate(r["rows"], start=1):
                d = (b / a - 1) * 100 if a else 0
                big = abs(d) > 0.5
                col = T.DOWN if "매도" in name else T.UP if "매수" in name and "중단" not in name else T.MUTED
                lab(g, name, "kr_s", fg=col, anchor="w").grid(row=i, column=0, sticky="ew", padx=8)
                lab(g, T.fmtp(a), "num", anchor="e").grid(row=i, column=1, sticky="ew", padx=8)
                lab(g, T.fmtp(b), "num", anchor="e").grid(row=i, column=2, sticky="ew", padx=8)
                lab(g, f"{d:+.2f}%" if big else "같음", "num_b" if big else "num_s",
                    fg=T.UP if big else T.MUTED, anchor="e").grid(row=i, column=3, sticky="ew", padx=8)
            for j in range(4):
                g.columnconfigure(j, minsize=(110, 130, 130, 80)[j])
        row = tk.Frame(w, bg=T.PANEL)
        row.pack(fill="x", padx=20, pady=14)
        if n:
            T.Btn(row, "현행 기준으로 바꾸기", lambda: (w.destroy(), self.apply_drift()), "primary").pack(side="right", padx=4)
        T.Btn(row, "닫기", w.destroy).pack(side="right", padx=4)
        w.update_idletasks()  # 내용 크기에 맞춰 메인 창 가운데에
        ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - ww) // 2
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - wh) // 2)
        w.geometry(f"{ww}x{wh}+{max(0, x)}+{max(0, y)}")

    def fib_sim_note(self):
        return ("\n\n※ 설정 탭의 '모의 모드'가 켜져 있어 새 주문은 실제로 나가지 않고 기록만 됩니다."
                if self.cfg["simulate"] or not self.engine.api else "")

    def apply_drift(self):
        if messagebox.askyesno("현행 기준으로 바꾸기",
                               "지금 캔들로 레벨을 다시 계산하고,\nBTC·ETH·XRP 예약 주문 중 새 플랜과 다른 것은 취소한 뒤 새 가격으로 다시 겁니다."
                               + self.fib_sim_note() + "\n\n진행할까요?", icon="warning"):
            self.drift_box.pack_forget()
            self.engine.request("apply_plan", True, None, "현행 기준으로 바꾸기")
            self.nb.select(self.orders_tab)  # 주문 탭에서 결과 확인

    def toggle_auto_drift(self):
        on = self.auto_drift.get()
        if on and not messagebox.askyesno("자동 반영", "앞으로 레벨이 유의적으로 바뀌면 확인 없이 자동으로 주문을 새 가격으로 바꿉니다.\n켤까요?"
                                          + self.fib_sim_note(), icon="warning"):
            self.auto_drift.set(False)
            return
        self.cfg["auto_apply_drift"] = on
        core.save_config(self.cfg)

    def cancel_selected(self, coin):
        sel = list(self.cards[coin]["ladder"].checked)
        if not sel:
            messagebox.showinfo("취소", "표에서 취소할 주문의 체크박스(☐)를 누르세요.")
            return
        if messagebox.askyesno("선택 취소", f"{coin} 예약 주문 {len(sel)}건을 업비트에서 실제로 취소할까요?"):
            self.engine.request("cancel_orders", [coin], sel)
            self.cards[coin]["ladder"].checked.clear()

    def cancel_coin(self, coin):
        name = coin or "BTC·ETH·XRP"
        if messagebox.askyesno("전체 취소", f"{name} 예약(미체결) 주문을 업비트에서 전부 실제로 취소할까요?", icon="warning"):
            self.engine.request("cancel_orders", [coin] if coin else None, None)

    def replan_coin(self, coin):
        if messagebox.askyesno("플랜대로 다시 걸기", f"{coin} 예약 주문을 지금 플랜과 비교해서, 다른 것은 취소하고 플랜대로 다시 겁니다."
                               + self.fib_sim_note() + "\n\n진행할까요?"):
            self.engine.request("apply_plan", False, [coin], f"{coin} 플랜대로 다시 걸기")

    # ---------------- 투자내역 (2a) ----------------
    INV_COLS = (("arrow", "", 28, "center"), ("coin", "코인", 80, "w"), ("qty", "보유수량", 130, "e"),
                ("avg", "매수평균가", 120, "e"), ("buy", "매수금액", 120, "e"), ("price", "현재가", 120, "e"),
                ("value", "평가금액", 120, "e"), ("pnl", "평가손익", 120, "e"), ("rate", "수익률", 90, "e"),
                ("weight", "비중", 130, "e"))

    def build_invest(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "투자내역")
        self.inv_sum = W.SummaryBar(f, [("krw", "보유 KRW"), ("buy", "총매수"), ("val", "총평가"), ("pnl", "평가손익"),
                                        ("total", "총 보유자산")], big=True, height=78)
        self.inv_sum.pack(fill="x", padx=18, pady=(18, 0))
        # 본문만 세로 스크롤
        outer = tk.Frame(f, bg=T.GROUND)
        outer.pack(fill="both", expand=True, padx=18, pady=18)
        canvas = tk.Canvas(outer, bg=T.GROUND, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=T.GROUND)
        win = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-int(e.delta / 120), "units")
                        if self.nb.index() == 1 else None)
        self.inv_canvas = canvas

        hp = tk.Frame(body, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        hp.pack(fill="x")
        hh = tk.Frame(hp, bg=T.PANEL)
        hh.pack(fill="x", padx=16, pady=(14, 8))
        lab(hh, "보유 코인", "panel_t").pack(side="left")
        lab(hh, "업비트 매수평균가 기준 · 현재가 2초마다 갱신 · 스테이킹·원화마켓 없는 코인 제외 · 행을 누르면 차트",
            "kr_s", fg=T.MUTED).pack(side="right")
        self.inv_table = tk.Frame(hp, bg=T.PANEL)
        self.inv_table.pack(fill="x", padx=16, pady=(0, 14))
        head = tk.Frame(self.inv_table, bg=T.PANEL)
        head.pack(fill="x")
        self.inv_grid_cfg(head)
        for i, (key, text, w, anchor) in enumerate(self.INV_COLS):
            lab(head, text, "kr_xs", fg=T.MUTED, anchor=anchor).grid(row=0, column=i, sticky="ew", padx=4, pady=4)
        tk.Frame(self.inv_table, bg=T.DIVIDER, height=1).pack(fill="x")
        self.inv_rows = {}

        tp = tk.Frame(body, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        tp.pack(fill="x", pady=(18, 0))
        th = tk.Frame(tp, bg=T.PANEL)
        th.pack(fill="x", padx=16, pady=(14, 8))
        lab(th, "거래내역", "panel_t").pack(side="left")
        lab(th, "최근 체결 100건 · 5분마다 갱신", "kr_s", fg=T.MUTED).pack(side="left", padx=10)
        T.Btn(th, "새로고침", self.feed_history_now).pack(side="right")
        seg = tk.Frame(th, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        seg.pack(side="right", padx=10)
        self.hist_filter, self.seg_labels, self.hist_orders = "전체", {}, []
        for name in ("전체", "매수", "매도"):
            s = lab(seg, name, "kr_s", padx=12, pady=3, cursor="hand2")
            s.pack(side="left")
            s.bind("<Button-1>", lambda e, n=name: self.set_hist_filter(n))
            self.seg_labels[name] = s
        self.set_hist_filter("전체", render=False)
        cols = (("ts", "체결시간", 170), ("coin", "코인", 80), ("side", "종류", 70), ("qty", "거래수량", 150),
                ("px", "거래단가", 130), ("krw", "거래금액", 130), ("fee", "수수료", 90), ("type", "주문", 80))
        self.hist_tree = ttk.Treeview(tp, columns=[c for c, _, _ in cols], show="headings", height=12, style="Tall.Treeview")
        for c, t, w in cols:
            self.hist_tree.heading(c, text=t)
            self.hist_tree.column(c, width=w, anchor="w" if c in ("ts", "coin", "side", "type") else "e")
        self.hist_tree.tag_configure("bid", foreground=T.UP)
        self.hist_tree.tag_configure("ask", foreground=T.DOWN)
        self.hist_tree.pack(fill="x", padx=16, pady=(0, 14))

    def inv_grid_cfg(self, frame):
        for i, (_, _, w, _) in enumerate(self.INV_COLS):
            frame.columnconfigure(i, minsize=w, weight=1 if i in (1,) else 0)

    def set_hist_filter(self, name, render=True):
        self.hist_filter = name
        for n, s in self.seg_labels.items():
            s.config(bg=T.ACCENT if n == name else T.PANEL, fg=T.GROUND if n == name else T.TEXT)
        if render:
            self.render_history(self.hist_orders)

    def feed_history_now(self):
        if hasattr(self, "feed"):
            self.feed.want_history.set()

    def inv_row(self, cur):
        """보유 코인 한 줄 (처음 한 번만 만들고 이후엔 글자만 바꾼다)."""
        if cur in self.inv_rows:
            return self.inv_rows[cur]
        wrap = tk.Frame(self.inv_table, bg=T.PANEL)
        wrap.pack(fill="x")
        row = tk.Frame(wrap, bg=T.PANEL, height=42, cursor="hand2")
        row.pack(fill="x")
        row.pack_propagate(False)
        inner = tk.Frame(row, bg=T.PANEL)
        inner.pack(fill="both", expand=True)
        self.inv_grid_cfg(inner)
        cells = {}
        for i, (key, _, _, anchor) in enumerate(self.INV_COLS):
            if key == "weight":
                cell = tk.Frame(inner, bg=T.PANEL)
                bar = tk.Canvas(cell, width=60, height=4, bg=T.TRACK_10, highlightthickness=0)
                bar.pack(side="left", padx=(0, 6), pady=0)
                pct = lab(cell, "", "num_s")
                pct.pack(side="left")
                cells[key] = (bar, pct)
                cell.grid(row=0, column=i, sticky="e", padx=4)
                widgets = [cell, bar, pct]
            else:
                font = "num_b" if key in ("coin", "rate") else "num_s" if key == "qty" else "num"
                l = lab(inner, "", font, fg=T.MUTED if key == "qty" else T.TEXT, anchor=anchor)
                l.grid(row=0, column=i, sticky="ew", padx=4, pady=11)
                cells[key] = l
                widgets = [l]
            for wdg in widgets:
                wdg.bind("<Button-1>", lambda e, c=cur: self.toggle_inv_chart(c))
        for wdg in (row, inner):
            wdg.bind("<Button-1>", lambda e, c=cur: self.toggle_inv_chart(c))
        tk.Frame(wrap, bg=T.DIVIDER_SOFT, height=1).pack(fill="x")
        chart = W.Candles(wrap, height=200)
        r = {"wrap": wrap, "row": row, "inner": inner, "cells": cells, "chart": chart, "candles": None}
        self.inv_rows[cur] = r
        if cur in self.cfg["ui"].get("inv_charts_open", []):
            self.root.after(10, lambda: self.toggle_inv_chart(cur, force=True))
        return r

    def toggle_inv_chart(self, cur, force=False):
        r = self.inv_rows[cur]
        opened = r["chart"].winfo_ismapped()
        on = True if force else not opened
        bg = T.ROW_NEAR if on else T.PANEL
        for wdg in [r["row"], r["inner"]] + [w for w in r["inner"].winfo_children()]:
            wdg.config(bg=bg)
        for v in r["cells"].values():
            if isinstance(v, tuple):
                v[1].config(bg=bg)
            else:
                v.config(bg=bg)
        r["cells"]["arrow"].config(text="▴" if on else "▾")
        if on:
            r["chart"].pack(fill="x", pady=(0, 10), padx=4)
            self.engine.request("load_candles", f"inv:{cur}", cur, "days", 60)
        else:
            r["chart"].pack_forget()
        if not force:
            lst = [c for c in self.cfg["ui"].get("inv_charts_open", []) if c != cur] + ([cur] if on else [])
            self.cfg["ui"]["inv_charts_open"] = lst
            core.save_config(self.cfg)

    def render_invest(self):
        krw = 0.0
        items = []
        for a in self.accounts:
            cur = a["currency"]
            if cur == "KRW":
                krw = a["qty"]
                continue
            live = self.live.get(cur)
            if not live or a["qty"] <= 0:
                continue
            items.append((cur, a, live[0]))
        buy_tot = sum(a["qty"] * a["avg"] for _, a, _ in items)
        val_tot = sum(a["qty"] * p for _, a, p in items)
        for cur in list(self.inv_rows):  # 다 판 코인은 줄 삭제
            if cur not in {c for c, _, _ in items}:
                self.inv_rows.pop(cur)["wrap"].destroy()
        for cur, a, price in sorted(items, key=lambda x: -x[1]["qty"] * x[2]):
            r = self.inv_row(cur)
            cells = r["cells"]
            buy, val = a["qty"] * a["avg"], a["qty"] * price
            pnl = val - buy
            rate = pnl / buy * 100 if buy else 0
            col = T.chg_color(pnl)
            cells["arrow"].config(text="▴" if r["chart"].winfo_ismapped() else "▾", fg=T.MUTED)
            cells["coin"].config(text=cur)
            cells["qty"].config(text=T.fmtq(a["qty"]))
            cells["avg"].config(text=T.fmtp(a["avg"]))
            cells["buy"].config(text=T.fmtk(buy))
            cells["price"].config(text=T.fmtp(price))
            cells["value"].config(text=T.fmtk(val))
            cells["pnl"].config(text=T.fmtk(pnl, sign=True), fg=col)
            cells["rate"].config(text=f"{rate:+.2f}%", fg=col)
            share = val / val_tot * 100 if val_tot else 0
            bar, pct = cells["weight"]
            bar.delete("all")
            bar.create_rectangle(0, 0, 60 * share / 100, 4, fill=T.ACCENT, outline="")
            pct.config(text=f"{share:.1f}%")
            if r["chart"].winfo_ismapped() and r["candles"]:
                r["chart"].set(r["candles"], [("매수평균가", a["avg"], T.LINE_NOW, False), ("현재가", price, T.TEXT, True)],
                               "1일 · 60봉")
        pnl = val_tot - buy_tot
        rate = pnl / buy_tot * 100 if buy_tot else 0
        self.inv_sum.set("krw", T.fmtk(krw), "원")
        self.inv_sum.set("buy", T.fmtk(buy_tot), "원")
        self.inv_sum.set("val", T.fmtk(val_tot), "원")
        self.inv_sum.set("pnl", f"{T.fmtk(pnl, sign=True)}", f"원  {rate:+.2f}%", color=T.chg_color(pnl))
        self.inv_sum.set("total", T.fmtk(krw + val_tot), "원")

    def render_history(self, orders):
        self.hist_orders = orders
        self.hist_tree.delete(*self.hist_tree.get_children())
        for o in orders:
            vol = float(o.get("executed_volume") or 0)
            if vol <= 0:
                continue
            if (self.hist_filter == "매수" and o["side"] != "bid") or (self.hist_filter == "매도" and o["side"] != "ask"):
                continue
            funds = o.get("executed_funds")
            funds = float(funds) if funds is not None else sum(float(t["funds"]) for t in o.get("trades") or []) \
                or (float(o["price"]) * vol if o.get("price") and o.get("ord_type") == "limit" else 0)
            px = funds / vol if funds else float(o.get("price") or 0)
            ts = (o.get("created_at") or "")[:19].replace("T", " ")
            self.hist_tree.insert("", "end", tags=(o["side"],), values=(
                ts, o["market"].split("-")[-1], "매수" if o["side"] == "bid" else "매도", T.fmtq(vol),
                T.fmtp(px), T.fmtk(funds), f"{float(o.get('paid_fee') or 0):,.1f}",
                {"limit": "지정가", "price": "시장가", "market": "시장가"}.get(o.get("ord_type"), o.get("ord_type", ""))))

    # ---------------- 자동매매 (물타기) ----------------
    def page(self, nb, text):
        f = ttk.Frame(nb, padding=18)
        nb.add(f, text)
        return f

    def build_grid(self, nb):
        f = self.page(nb, "자동매매")
        g = self.cfg["grid"]
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        self.g_on = tk.BooleanVar(value=g["enabled"])
        self.g_sim = tk.BooleanVar(value=g["simulate"])
        self.g_half = tk.BooleanVar(value=g["half_at_breakeven"])
        ttk.Checkbutton(bar, text="켜기", variable=self.g_on).pack(side="left")
        ttk.Checkbutton(bar, text="모의", variable=self.g_sim).pack(side="left", padx=6)
        self.g_fields = {}
        for key, label, val, w in (("coins", "코인", ",".join(g["coins"]), 30), ("unit_krw", "1회", g["unit_krw"], 8),
                                   ("drop_pct", "하락%", g["drop_pct"], 5), ("profit_krw", "익절원", g["profit_krw"], 6),
                                   ("max_krw", "코인한도", g["max_krw"], 8), ("total_max_krw", "전체한도", g["total_max_krw"], 9)):
            ttk.Label(bar, text=label, style="Muted.TLabel").pack(side="left", padx=(10, 3))
            e = ttk.Entry(bar, width=w)
            e.insert(0, str(val))
            e.pack(side="left")
            self.g_fields[key] = e
        ttk.Checkbutton(bar, text="본전 절반 매도", variable=self.g_half).pack(side="left", padx=10)
        T.Btn(bar, "저장", self.save_grid, "primary", bg=T.GROUND).pack(side="left")
        ttk.Label(f, text="규칙: 시작 매수 → 마지막 매수가 대비 하락%마다 1회 금액 추가 매수 → (2회 이상 샀으면) 본전에 절반 매도"
                          " → 사이클 수익이 익절원 이상이면 전량 매도 후 다시 시작. BTC·ETH·XRP는 제외.",
                  style="Muted.TLabel", wraplength=1300).pack(anchor="w", pady=8)
        cols = (("status", "상태", 150), ("coin", "코인", 60), ("price", "현재가", 100), ("buys", "매수", 45), ("cost", "원가", 85),
                ("avg", "평단", 100), ("pnl", "평가손익", 85), ("next", "다음 매수가", 105), ("be", "본전 절반가", 105),
                ("tp", "익절가", 105), ("cyc", "사이클", 55), ("tot", "누적 수익", 90), ("own", "기존 보유(별도)", 150))
        self.grid_tree = ttk.Treeview(f, columns=[c for c, _, _ in cols], show="headings", height=10)
        for c, t, w in cols:
            self.grid_tree.heading(c, text=t)
            self.grid_tree.column(c, width=w, anchor="e" if c not in ("coin", "status") else "center")
        self.grid_tree.tag_configure("up", foreground=T.UP)
        self.grid_tree.tag_configure("down", foreground=T.DOWN)
        self.grid_tree.pack(fill="x")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=8)
        self.grid_sum = ttk.Label(row, text="")
        self.grid_sum.pack(side="left")
        T.Btn(row, "선택 코인 청산", self.grid_liquidate, bg=T.GROUND).pack(side="right")
        T.Btn(row, "선택 코인 목록에 다시 넣기", self.grid_relist, bg=T.GROUND).pack(side="right", padx=8)
        ttk.Label(f, text="자동매매 거래 기록", style="Title.TLabel").pack(anchor="w", pady=(10, 6))
        self.grid_log = self.table(f, (("ts", "시간", 170), ("sim", "모의", 50), ("coin", "코인", 70), ("side", "구분", 60),
                                       ("price", "가격", 130), ("qty", "수량", 160), ("krw", "금액", 120)), 10)

    def render_grid(self, rows):
        self.grid_tree.delete(*self.grid_tree.get_children())
        num = lambda v: "-" if v is None else T.fmtp(v)  # noqa: E731
        cost = tot = pnl = 0
        for r in rows:
            cost, tot, pnl = cost + r["cost"], tot + r["profit_total"], pnl + r["pnl"]
            self.grid_tree.insert("", "end", iid=r["coin"], tags=("up" if r["pnl"] > 0 else "down",), values=(
                r["status"], r["coin"], num(r["price"]), r["buys"], f"{r['cost']:,.0f}", num(r["avg"]), f"{r['pnl']:+,.0f}",
                num(r["next_buy"]), num(r["breakeven"]), num(r["tp"]), r["cycles"], f"{r['profit_total']:+,.0f}",
                self.own_text(r)))
        g = self.cfg["grid"]
        state = ("꺼짐" if not g["enabled"] else "모의" if g["simulate"] or not self.engine.api else "실전")
        self.grid_sum.config(text=f"[{state}] 투입 원가 {cost:,.0f}원 · 평가손익 {pnl:+,.0f}원 · 누적 실현 {tot:+,.0f}원")

    def own_text(self, r):
        """업비트 실제 잔고에서 자동매매 몫을 뺀 기존 보유분 (모의면 전체 잔고가 기존 보유)."""
        bal = self.hold.get(r["coin"])
        if bal is None:
            return "-"
        g = self.cfg["grid"]
        mine = 0 if g["simulate"] or not self.engine.api else r["qty"]
        own = max(bal - mine, 0)
        return f"{T.fmtq(own)}개 ({own * r['price']:,.0f}원)" if own > 1e-12 else "없음"

    def render_grid_log(self):
        self.grid_log.delete(*self.grid_log.get_children())
        for ts, sim, coin, side, price, qty, krw, _ in self.db.query(
                "SELECT * FROM grid_trades ORDER BY rowid DESC LIMIT 200"):
            self.grid_log.insert("", "end", tags=(side,), values=(ts[:19].replace("T", " "), "예" if sim else "", coin,
                                                                  "매수" if side == "bid" else "매도", T.fmtp(price),
                                                                  T.fmtq(qty), f"{krw:,.0f}"))

    def save_grid(self):
        g, fl = self.cfg["grid"], self.g_fields
        try:
            # 쉼표·띄어쓰기·슬래시 어느 것으로 나눠 적어도 된다 (예: "SOL DOGE ADA" / "SOL,DOGE")
            coins = list(dict.fromkeys(c.upper() for c in re.split(r"[\s,，/;·]+", fl["coins"].get()) if c))
            blocked = [c for c in coins if c in core.GRID_BLOCKED]
            new = {"coins": [c for c in coins if c not in core.GRID_BLOCKED],
                   "unit_krw": int(float(fl["unit_krw"].get())), "drop_pct": float(fl["drop_pct"].get()),
                   "profit_krw": int(float(fl["profit_krw"].get())), "max_krw": int(float(fl["max_krw"].get())),
                   "total_max_krw": int(float(fl["total_max_krw"].get()))}
        except ValueError as e:
            messagebox.showerror("자동매매", f"숫자를 확인하세요: {e}")
            return
        try:
            listed = {m["market"][4:] for m in fr.get("/market/all") if m["market"].startswith("KRW-")}
        except Exception:
            listed = None
        unknown = [c for c in new["coins"] if listed is not None and c not in listed]
        if unknown:
            messagebox.showerror("자동매매", f"업비트 원화마켓에 없는 코인입니다: {', '.join(unknown)}\n"
                                            "기호를 확인하세요 (예: BCH, SOL, DOGE, ADA).")
            return
        if new["unit_krw"] < 5000:
            messagebox.showerror("자동매매", "업비트 최소 주문이 5,000원이라 1회 금액은 5,000원 이상이어야 합니다.")
            return
        going_live = self.g_on.get() and not self.g_sim.get() and (g["simulate"] or not g["enabled"])
        if going_live and not messagebox.askyesno(
                "자동매매 실전", f"⚠ 실전으로 켜면 승인 없이 업비트에 시장가 주문이 자동으로 나갑니다.\n"
                f"코인 {', '.join(new['coins'])} · 1회 {new['unit_krw']:,}원 · 코인별 한도 {new['max_krw']:,}원 · "
                f"전체 한도 {new['total_max_krw']:,}원\n\n진행할까요?",
                icon="warning"):
            return
        holding = any(st.get("qty") for st in g["state"].values())
        msg = "저장했습니다." + (f"\n{', '.join(blocked)}는 피보나치 코인이라 제외했습니다." if blocked else "")
        if g["simulate"] and not self.g_sim.get():
            g["state"] = {}  # 모의 보유분은 가상이라 실전 시작 전에 비운다
            msg += "\n모의 기록(가상 보유분)을 비우고 실전으로 새로 시작합니다."
        elif not g["simulate"] and self.g_sim.get() and holding:
            messagebox.showerror("자동매매", "실전 보유분이 있습니다. '선택 코인 청산'으로 비운 뒤 모의로 바꾸세요.")
            self.g_sim.set(False)
            return
        g.update(new, enabled=self.g_on.get(), simulate=self.g_sim.get(), half_at_breakeven=self.g_half.get())
        core.save_config(self.cfg)
        self.set_coins_field()
        msg += f"\n자동매매 코인: {', '.join(new['coins']) or '없음'}"
        messagebox.showinfo("자동매매", msg)

    def set_coins_field(self):
        e = self.g_fields["coins"]
        e.delete(0, "end")
        e.insert(0, ",".join(self.cfg["grid"]["coins"]))

    def grid_relist(self):
        sel = self.grid_tree.selection()
        if not sel:
            messagebox.showinfo("자동매매", "표에서 다시 넣을 코인을 선택하세요.")
            return
        coin, g = sel[0], self.cfg["grid"]
        if coin in g["coins"]:
            messagebox.showinfo("자동매매", f"{coin}은 이미 자동매매 목록에 있습니다.")
            return
        g["coins"] = g["coins"] + [coin]
        core.save_config(self.cfg)
        self.set_coins_field()
        messagebox.showinfo("자동매매", f"{coin}을 목록에 다시 넣었습니다. 이어서 자동으로 사고팝니다.\n"
                                     f"자동매매 코인: {', '.join(g['coins'])}")

    def grid_liquidate(self):
        sel = self.grid_tree.selection()
        if not sel:
            messagebox.showinfo("자동매매", "표에서 청산할 코인을 선택하세요.")
            return
        coin = sel[0]
        if messagebox.askyesno("청산", f"{coin} 자동매매 보유분을 전량 시장가 매도하고 목록에서 뺄까요?"):
            self.engine.request("grid_liquidate", coin)

    # ---------------- ② 주문 ----------------
    def build_orders(self, nb):
        f = self.page(nb, "주문")
        self.orders_tab = f
        self.prop_reason = ttk.Label(f, text="제안 없음", style="Title.TLabel")
        self.prop_reason.pack(anchor="w")
        cols = (("st", "상태", 70), ("coin", "코인", 60), ("label", "구분", 190), ("price", "가격", 130),
                ("vol", "수량", 150), ("krw", "금액(원)", 130))
        holder = ttk.Frame(f)
        holder.pack(fill="both", expand=True, pady=8)
        self.prop_tree = ttk.Treeview(holder, columns=[c for c, _, _ in cols], show="headings", height=16)
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.prop_tree.yview)
        self.prop_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        for c, t, w in cols:
            self.prop_tree.heading(c, text=t)
            self.prop_tree.column(c, width=w, anchor="e" if c in ("price", "vol", "krw") else "center")
        for tag, color in (("유지", T.MUTED), ("주문", T.ACCENT_200), ("취소", T.UP)):
            self.prop_tree.tag_configure(tag, foreground=color)
        self.prop_tree.pack(side="left", fill="both", expand=True)
        row = ttk.Frame(f)
        row.pack(fill="x")
        T.Btn(row, "플랜과 다시 비교", lambda: self.engine.request("make_proposal", "수동 비교", True), bg=T.GROUND).pack(side="left")
        T.Btn(row, "레벨 재계산", self.recalc, bg=T.GROUND).pack(side="left", padx=6)
        self.btn_ok = T.Btn(row, "승인·실행", self.approve, "primary", bg=T.GROUND)
        self.btn_ok.pack(side="right")
        T.Btn(row, "무시", self.dismiss, bg=T.GROUND).pack(side="right", padx=6)
        self.result = tk.Text(f, height=7, wrap="none", bg=T.PANEL, fg=T.TEXT, insertbackground=T.TEXT,
                              highlightthickness=1, highlightbackground=T.DIVIDER, relief="flat", font=T.F["kr_s"])
        self.result.pack(fill="x", pady=(8, 0))
        self.executing = False

    def render_proposal(self):
        self.prop_tree.delete(*self.prop_tree.get_children())
        p = self.proposal
        if not p:
            self.prop_reason.config(text="제안 없음 (플랜과 실제 주문이 같음)")
            return
        n = len(p["todo"])
        self.prop_reason.config(text=f"{p['reason']} — 변경 {n}건" if n else f"{p['reason']} — 변경 없음")
        for st, coin, o in p["rows"]:
            side = "매도" if o["side"] == "ask" else "매수"
            label = o["label"] if o["label"] != "플랜 밖" else f"플랜 밖 {side}"
            self.prop_tree.insert("", "end", tags=(st,), values=(
                st, coin, label, fmt(o["price"]), T.fmtq(o["volume"]), T.fmtk(o["price"] * o["volume"])))

    def approve(self):
        if self.executing:
            return
        p = self.proposal
        if not p or not p["todo"]:
            messagebox.showinfo("FibTrader", "실행할 변경이 없습니다.")
            return
        cancels = sum(1 for k, _, _ in p["todo"] if k == "cancel")
        places = [o for k, _, o in p["todo"] if k == "place"]
        buy_krw = sum(o["price"] * o["volume"] for o in places if o["side"] == "bid")
        sim = self.cfg["simulate"] or not self.engine.api
        head = "[모의 모드] 실제 주문은 나가지 않습니다.\n\n" if sim else "⚠ 실전 모드: 업비트에 실제로 주문합니다.\n\n"
        msg = (f"{head}취소 {cancels}건, 새 주문 {len(places)}건\n매수 주문 합계 {buy_krw:,.0f}원\n\n진행할까요?")
        if messagebox.askyesno("승인·실행", msg, icon="warning" if not sim else "question"):
            self.executing = True  # 두 번 눌러도 한 번만
            self.btn_ok.config(text="실행 중…")
            self.engine.request("execute", p["id"])

    def dismiss(self):
        if self.proposal and self.proposal.get("id"):
            self.engine.request("dismiss", self.proposal["id"])

    def recalc(self):
        if messagebox.askyesno("레벨 재계산", "지금 캔들로 남은 단계의 레벨을 다시 계산하고 주문 제안을 만들까요?\n"
                               "(플랜 규칙상 체결 후나 월요일 주봉 마감 후에 하는 것이 원칙입니다)"):
            self.engine.request("recalc_levels", "수동 재계산")
            self.engine.request("make_proposal", "재계산 후 비교", True)

    def emergency(self):
        self.show()
        ans = messagebox.askyesnocancel(
            "긴급 정지", "자동 제안과 자동매매를 멈추고 '알림만' 모드로 바꿉니다.\n\n"
            "업비트의 BTC·ETH·XRP 미체결 주문도 전부 취소할까요?\n(예: 전부 취소 / 아니요: 모드만 변경)")
        if ans is not None:
            self.engine.request("emergency_stop", ans)
            self.mode_var.set("alert")
            self.g_on.set(False)
            self.root.after(500, self.refresh_chrome)

    # ---------------- ③ 알림·기록 ----------------
    def build_logs(self, nb):
        f = self.page(nb, "알림·기록")
        ttk.Label(f, text="알림", style="Title.TLabel").pack(anchor="w", pady=(0, 6))
        self.alert_tree = self.table(f, (("ts", "시간", 170), ("title", "제목", 240), ("msg", "내용", 800)), 12)
        ttk.Label(f, text="주문 실행 기록", style="Title.TLabel").pack(anchor="w", pady=(14, 6))
        self.act_tree = self.table(f, (("ts", "시간", 170), ("sim", "모의", 50), ("what", "내용", 480),
                                       ("res", "결과", 500)), 8)
        T.Btn(f, "새로고침", self.render_logs, bg=T.GROUND).pack(anchor="e", pady=8)

    def table(self, parent, cols, height):
        t = ttk.Treeview(parent, columns=[c for c, _, _ in cols], show="headings", height=height)
        for c, text, w in cols:
            t.heading(c, text=text)
            t.column(c, width=w, anchor="w")
        t.tag_configure("bid", foreground=T.UP)
        t.tag_configure("ask", foreground=T.DOWN)
        t.pack(fill="both", expand=True)
        return t

    def render_logs(self):
        self.alert_tree.delete(*self.alert_tree.get_children())
        for ts, kind, title, msg in self.db.query("SELECT * FROM alerts ORDER BY rowid DESC LIMIT 300"):
            self.alert_tree.insert("", "end", values=(ts, title, msg.replace("\n", " / ")))
        self.act_tree.delete(*self.act_tree.get_children())
        for ts, sim, kind, market, side, price, vol, res in self.db.query(
                "SELECT * FROM actions ORDER BY rowid DESC LIMIT 200"):
            word = ("취소 " if kind == "cancel" else "주문 ") + market + (" 매도 " if side == "ask" else " 매수 ")
            self.act_tree.insert("", "end", tags=(side,), values=(ts[:19].replace("T", " "), "예" if sim else "",
                                                                  f"{word}{T.fmtp(price)} × {T.fmtq(vol)}", res))

    # ---------------- ④ 설정 ----------------
    def build_settings(self, nb):
        f = self.page(nb, "설정")
        c = self.cfg
        self.mode_var = tk.StringVar(value=c["mode"])
        self.sim_var = tk.BooleanVar(value=c["simulate"])
        self.fields = {}
        r = 0

        def row(label, widget):
            nonlocal r
            ttk.Label(f, text=label, style="Muted.TLabel").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 16))
            widget.grid(row=r, column=1, sticky="w", pady=4)
            r += 1

        mode = ttk.Frame(f)
        ttk.Radiobutton(mode, text="반자동 (제안 → 승인 → 실행)", value="semi", variable=self.mode_var).pack(side="left")
        ttk.Radiobutton(mode, text="알림만", value="alert", variable=self.mode_var).pack(side="left", padx=10)
        row("모드", mode)
        row("모의 모드", ttk.Checkbutton(f, text="켜면 승인해도 실제 주문 안 함 (처음엔 켜 두기)", variable=self.sim_var))

        def entry(key, label, value, width=14):
            e = ttk.Entry(f, width=width)
            e.insert(0, str(value))
            self.fields[key] = e
            row(label, e)

        entry("buy_budget", "매수 예산 (원)", c["buy_budget"])
        for coin in fr.COINS:
            entry(f"split_{coin}", f"  {coin} 예산 비중 (0~1)", c["buy_split"][coin], 8)
        entry("near_pct", "근접 알림 범위 (%)", c["near_pct"], 8)
        self.near_hl = ttk.Combobox(f, values=["끔", "3%", "5%", "10%"], width=6, state="readonly")
        nh = c["ui"].get("near_highlight_pct", 5)
        self.near_hl.set("끔" if not nh else f"{nh:g}%")
        row("근접 강조 범위 (표 배경)", self.near_hl)
        entry("every_sec", "확인 간격 (초)", c["every_sec"], 8)
        entry("max_order_krw", "1건 최대 금액 (원)", c["max_order_krw"])
        entry("max_orders_per_day", "하루 최대 실주문 (건)", c["max_orders_per_day"], 8)
        entry("volume_tol_pct", "수량 차이 허용 (%)", c["volume_tol_pct"], 8)
        for coin in fr.COINS:
            entry(f"dca_{coin}", f"  {coin} 매일 모으기 (원)", c["dca_daily"].get(coin, 0), 10)
        for coin in fr.COINS:
            pg = c["progress"][coin]
            box = ttk.Frame(f)
            sd = tk.Spinbox(box, from_=0, to=3, width=3, bg=T.PANEL, fg=T.TEXT, buttonbackground=T.PANEL,
                            highlightthickness=1, highlightbackground=T.DIVIDER, relief="flat", insertbackground=T.TEXT)
            bd = tk.Spinbox(box, from_=0, to=3, width=3, bg=T.PANEL, fg=T.TEXT, buttonbackground=T.PANEL,
                            highlightthickness=1, highlightbackground=T.DIVIDER, relief="flat", insertbackground=T.TEXT)
            sd.delete(0, "end"), sd.insert(0, pg["sell_done"])
            bd.delete(0, "end"), bd.insert(0, pg["buy_done"])
            ttk.Label(box, text="매도 체결 단계", style="Muted.TLabel").pack(side="left")
            sd.pack(side="left", padx=4)
            ttk.Label(box, text="매수 체결 단계", style="Muted.TLabel").pack(side="left", padx=(10, 0))
            bd.pack(side="left", padx=4)
            self.fields[f"sd_{coin}"], self.fields[f"bd_{coin}"] = sd, bd
            row(f"  {coin} 진행", box)
        keys = "연결됨 (UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY)" if self.engine.api else "없음 — setx로 키를 저장한 뒤 다시 실행"
        row("업비트 API 키", ttk.Label(f, text=keys))
        btns = ttk.Frame(f)
        T.Btn(btns, "저장", self.save_settings, "primary", bg=T.GROUND).pack(side="left")
        T.Btn(btns, "바탕화면 바로가기 만들기", self.desktop_link, bg=T.GROUND).pack(side="left", padx=6)
        T.Btn(btns, "PC 켤 때 자동 실행", self.startup_link, bg=T.GROUND).pack(side="left")
        T.Btn(btns, "자동 실행 해제", self.remove_startup, bg=T.GROUND).pack(side="left", padx=6)
        row("", btns)

    def save_settings(self):
        c, fl = self.cfg, self.fields
        try:
            c["mode"], c["simulate"] = self.mode_var.get(), self.sim_var.get()
            c["buy_budget"] = int(float(fl["buy_budget"].get()))
            c["buy_split"] = {coin: float(fl[f"split_{coin}"].get()) for coin in fr.COINS}
            for k in ("near_pct", "volume_tol_pct"):
                c[k] = float(fl[k].get())
            for k in ("every_sec", "max_order_krw", "max_orders_per_day"):
                c[k] = int(float(fl[k].get()))
            c["dca_daily"] = {coin: int(float(fl[f"dca_{coin}"].get())) for coin in fr.COINS}
            for coin in fr.COINS:
                c["progress"][coin] = {"sell_done": int(fl[f"sd_{coin}"].get()), "buy_done": int(fl[f"bd_{coin}"].get())}
            nh = self.near_hl.get()
            c["ui"]["near_highlight_pct"] = 0 if nh == "끔" else float(nh.rstrip("%"))
        except ValueError as e:
            messagebox.showerror("설정", f"숫자를 확인하세요: {e}")
            return
        if abs(sum(c["buy_split"].values()) - 1) > 0.001:
            messagebox.showwarning("설정", "코인 예산 비중 합이 1이 아닙니다. 그래도 저장합니다.")
        core.save_config(c)
        self.engine.load_levels()
        self.refresh_chrome()
        self.render_board()
        messagebox.showinfo("설정", "저장했습니다.")
        self.engine.request("make_proposal", "설정 변경 후 비교", True)

    def desktop_link(self):
        make_shortcut("Desktop")
        messagebox.showinfo("FibTrader", "바탕화면에 FibTrader 아이콘을 만들었습니다.")

    def startup_link(self):
        make_shortcut("Startup")
        old = os.path.join(startup_dir(), "start_watch.bat")
        if os.path.exists(old):
            os.remove(old)  # 예전 감시 프로그램과 중복 실행 방지
        messagebox.showinfo("FibTrader", "PC를 켜고 로그인하면 자동으로 실행됩니다.")

    def remove_startup(self):
        path = os.path.join(startup_dir(), "FibTrader.lnk")
        if os.path.exists(path):
            os.remove(path)
        messagebox.showinfo("FibTrader", "자동 실행을 해제했습니다.")

    # ---------------- 이벤트 처리 ----------------
    def set_status(self, text):
        err = "오류" in text
        ts = text.split(" ")[0]
        api = "API 연결됨" if self.engine.api else "API 키 없음"
        self.status.config(text=f"{api} · {ts} 확인" if not err else text[:80], fg=T.UP if err else T.MUTED)
        self.status_dot.config(fg=T.UP if err or not self.engine.api else T.DOWN)
        self.refresh_chrome()

    def pump(self):
        if getattr(self, "closing", False):
            return
        while not self.ui_calls.empty():
            self.ui_calls.get_nowait()()
        changed_logs = False
        while not self.events.empty():
            ev = self.events.get_nowait()
            kind = ev[0]
            if kind == "status":
                self.set_status(ev[1])
            elif kind == "prices":
                if not self.live:  # 실시간 시세가 오기 전까지만 엔진 가격 사용
                    self.prices = dict(ev[1])
                    self.render_board()
            elif kind == "board":
                self.board = ev[1]
                self.render_board()
            elif kind == "alert":
                title, msg, akind = ev[1], ev[2], ev[3]
                if WIN:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                self.tray_alert(title, msg)
                if akind in POPUP_KINDS:
                    self.popup(title, msg)
                changed_logs = True
            elif kind == "live":
                if getattr(self, "closing", False):
                    return
                self.render_strip(ev[1])
                self.render_board()
                if self.accounts:
                    self.render_invest()
            elif kind == "hold":
                self.hold = ev[1]
                self.render_board()
            elif kind == "accounts":
                self.accounts = ev[1]
                self.render_invest()
            elif kind == "candles":
                key, data = ev[1], ev[2]
                if key.startswith("inv:") and key[4:] in self.inv_rows:
                    self.inv_rows[key[4:]]["candles"] = data
                    self.render_invest()
            elif kind == "history":
                self.render_history(ev[1])
            elif kind == "history_error":
                self.hist_tree.delete(*self.hist_tree.get_children())
                self.hist_tree.insert("", "end", values=("거래내역 조회 실패", "", "", "", "", "", "", ev[1][:60]))
            elif kind == "open_orders":
                self.render_orders(ev[1])
            elif kind == "drift_report":
                self.show_drift_report(ev[1], ev[2])
            elif kind == "drift":
                self.render_drift(ev[1])
            elif kind == "grid":
                self.render_grid(ev[1])
            elif kind == "proposal":
                self.proposal = ev[1]
                self.render_proposal()
            elif kind == "done":
                self.executing = False
                self.drift_btn.config(text="레벨 변화 지금 확인")  # 확인 중 오류가 나도 버튼 원래대로
                self.btn_ok.config(text="승인·실행")
                self.result.delete("1.0", "end")
                self.result.insert("end", "\n".join(ev[1]))
                changed_logs = True
        if changed_logs:
            self.render_logs()
            self.render_grid_log()
        self.root.after(500, self.pump)

    def run(self):
        self.render_logs()
        self.render_grid_log()
        self.root.mainloop()


if __name__ == "__main__":
    if not single_instance():
        if WIN and signal_existing():
            sys.exit(0)  # 이미 떠 있는 창이 앞으로 나온다
        message("FibTrader가 이미 실행 중입니다.\n\n작업표시줄 오른쪽 아래 ^ (숨겨진 아이콘)에서 F 아이콘을 찾아\n"
                "오른쪽 클릭 → 종료한 뒤 다시 실행하세요.\n\n아이콘이 없으면 작업 관리자에서 pythonw.exe를 끝내세요.")
        sys.exit(0)
    try:
        App().run()
    except Exception:
        tb = traceback.format_exc()
        print(tb, flush=True)  # fibtrader.log에 남는다
        message("FibTrader를 시작하지 못했습니다.\n\n" + tb[-1800:] + "\n\n이 창을 캡처해서 보내 주세요.\n"
                f"(기록: {os.path.join(HERE, 'fibtrader.log')})", "FibTrader 실행 오류", 0x10)
        raise
