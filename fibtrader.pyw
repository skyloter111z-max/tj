"""FibTrader: 피보나치 플랜 감시·알림·반자동 주문 (트레이 + 대시보드).

처음 한 번: install.bat 실행 (라이브러리 설치 + 바탕화면 아이콘)
실행: 바탕화면 FibTrader 아이콘 더블클릭
창을 닫으면 트레이로 숨고, 트레이 아이콘 오른쪽 클릭 → 종료로 끝낸다.
"""
import ctypes
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)
if sys.stdout is None:  # pythonw엔 콘솔이 없음
    sys.stdout = sys.stderr = open(os.path.join(HERE, "fibtrader.log"), "a", encoding="utf-8", buffering=1)

import fib_recalc as fr  # noqa: E402
import fibtrader_core as core  # noqa: E402

WIN = sys.platform == "win32"
try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:  # 라이브러리가 없거나 트레이를 못 쓰는 환경이면 창만 띄운다
    pystray = None

POPUP_KINDS = {"hit", "fill", "proposal", "levels", "stop"}  # 근접(near)은 소리·트레이 알림만


def single_instance():
    if not WIN:
        return True
    ctypes.windll.kernel32.CreateMutexW(None, False, "FibTraderSingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


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
    return f"{v:,.0f}" if v is not None else "-"


class App:
    def __init__(self):
        self.cfg = core.load_config()
        self.db = core.DB()
        self.events = queue.Queue()
        self.ui_calls = queue.Queue()
        self.engine = core.Engine(self.cfg, self.db, self.events)
        self.proposal = None
        self.prices = {}
        self.board = {}
        self.live = {}      # coin -> (현재가, 24h 등락%)
        self.hold = {}      # currency -> 보유 수량
        self.strip = {}     # coin -> 상단 시세 라벨

        self.root = tk.Tk()
        self.root.title("FibTrader")
        self.root.geometry("1120x720")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        style = ttk.Style()
        style.configure("Treeview", rowheight=22)
        style.configure("Big.TLabel", font=("맑은 고딕", 15, "bold"))

        top = ttk.Frame(self.root, padding=(8, 6))
        top.pack(fill="x")
        self.status = ttk.Label(top, text="시작 중…")
        self.status.pack(side="left")
        ttk.Button(top, text="긴급 정지", command=self.emergency).pack(side="right")
        self.strip_bar = tk.Frame(self.root, bg="#111827")
        self.strip_bar.pack(fill="x", padx=6, pady=(0, 6))

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.nb = nb
        self.build_board(nb)
        self.build_grid(nb)
        self.build_orders(nb)
        self.build_logs(nb)
        self.build_settings(nb)

        self.icon = None
        if pystray:
            threading.Thread(target=self.run_tray, daemon=True).start()
        self.engine.start()
        core.PriceFeed(self.engine, self.events).start()
        self.root.after(300, self.pump)

    # ---------------- 트레이 ----------------
    def tray_image(self, color):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((4, 4, 60, 60), fill=color)
        d.text((24, 18), "F", fill="white")
        return img

    def run_tray(self):
        self.img_ok, self.img_alert = self.tray_image((37, 99, 235)), self.tray_image((220, 38, 38))
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
        self.engine.stop_event.set()
        if self.icon:
            self.icon.stop()
        self.root.destroy()

    def popup(self, title, msg):
        w = tk.Toplevel(self.root)
        w.title(title)
        w.attributes("-topmost", True)
        ttk.Label(w, text=title, style="Big.TLabel").pack(padx=16, pady=(12, 4), anchor="w")
        ttk.Label(w, text=msg, justify="left", wraplength=460).pack(padx=16, pady=4, anchor="w")
        row = ttk.Frame(w)
        row.pack(pady=10)
        ttk.Button(row, text="대시보드 열기", command=lambda: (w.destroy(), self.show())).pack(side="left", padx=4)
        ttk.Button(row, text="확인", command=w.destroy).pack(side="left", padx=4)

    # ---------------- ① 현황 ----------------
    def build_board(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="  현황  ")
        self.cards = {}
        for i, coin in enumerate(fr.COINS):
            box = ttk.LabelFrame(f, text=f"  {coin}  ", padding=6)
            box.grid(row=0, column=i, sticky="nsew", padx=4)
            f.columnconfigure(i, weight=1)
            price = tk.Label(box, text="-", font=("맑은 고딕", 20, "bold"), anchor="w")
            price.pack(fill="x")
            sub = ttk.Label(box, text="", foreground="#555")
            sub.pack(anchor="w")
            hold = ttk.Label(box, text="", foreground="#111", font=("맑은 고딕", 10, "bold"))
            hold.pack(anchor="w")
            tree = ttk.Treeview(box, columns=("price", "name", "dist"), show="headings", height=9)
            for col, text, w in (("price", "가격", 110), ("name", "구분", 90), ("dist", "현재가 대비", 80)):
                tree.heading(col, text=text)
                tree.column(col, width=w, anchor="e" if col != "name" else "center")
            tree.tag_configure("now", background="#fff3bf")
            tree.tag_configure("sell", foreground="#1d4ed8")
            tree.tag_configure("buy", foreground="#b91c1c")
            tree.tag_configure("done", foreground="#999")
            tree.pack(fill="x", pady=4)
            trend = ttk.Label(box, text="", justify="left", foreground="#333", wraplength=300)
            trend.pack(anchor="w")
            self.cards[coin] = (price, sub, tree, trend, hold)
        f.rowconfigure(0, weight=1)
        self.cash = ttk.Label(f, text="", foreground="#333")
        self.cash.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def render_board(self):
        total = 0.0
        for coin, (price_l, sub, tree, trend, hold_l) in self.cards.items():
            p = self.prices.get(coin)
            b = self.board.get(coin, {})
            live = self.live.get(coin)
            ch = live[1] if live else b.get("change24")
            price_l.config(text=f"{fmt(p)} 원", fg="#b91c1c" if (ch or 0) > 0 else "#1d4ed8" if (ch or 0) < 0 else "#111")
            pg = self.cfg["progress"][coin]
            sub.config(text=(f"{'전일 대비' if live else '24시간'} {ch:+.2f}% · " if ch is not None else "")
                       + f"매도 {pg['sell_done']}/3 · 매수 {pg['buy_done']}/3 체결")
            q = self.hold.get(coin)
            if q is not None and p:
                total += q * p
                hold_l.config(text=f"보유 {q:g} {coin} · 평가 {q * p:,.0f}원")
            trend.config(text=b.get("trend", ""))
            tree.delete(*tree.get_children())
            items = self.engine.levels.get(coin, [])
            rows = [(lvl, name) for name, lvl in items] + ([(p, "현재가")] if p else [])
            for lvl, name in sorted(rows, key=lambda r: -r[0]):
                step = int(name[0]) - 1 if name[0].isdigit() else None
                done = step is not None and step < (pg["sell_done"] if "매도" in name else pg["buy_done"])
                tag = "now" if name == "현재가" else "done" if done else "sell" if "매도" in name else "buy"
                dist = "" if name == "현재가" or not p else f"{(lvl / p - 1) * 100:+.1f}%"
                tree.insert("", "end", values=(fmt(lvl), name + (" ✓" if done else ""), dist), tags=(tag,))
        cash = self.board.get("_cash", "")
        at = self.board.get("_levels_at", "")
        krw = self.hold.get("KRW")
        tot = f"BTC·ETH·XRP 평가 {total:,.0f}원" + (f" + 현금 {krw:,.0f}원 = {total + krw:,.0f}원" if krw is not None else "") \
            if total else ""
        self.cash.config(text="\n".join(x for x in (tot, cash, f"레벨 기준 시각: {at}") if x))

    def render_strip(self, data):
        for coin, (price, ch) in data.items():
            if coin not in self.strip:
                row = 0 if coin in fr.COINS else 1  # 윗줄 피보나치, 아랫줄 자동매매
                if row == 1 and not any(c not in fr.COINS for c in self.strip):
                    tk.Label(self.strip_bar, text="자동매매", bg="#111827", fg="#9ca3af",
                             font=("맑은 고딕", 9)).grid(row=1, column=0, sticky="w", padx=(7, 0))
                if row == 0 and not self.strip:
                    tk.Label(self.strip_bar, text="피보나치", bg="#111827", fg="#9ca3af",
                             font=("맑은 고딕", 9)).grid(row=0, column=0, sticky="w", padx=(7, 0))
                col = 1 + sum(1 for c in self.strip if (c in fr.COINS) == (row == 0))
                lab = tk.Label(self.strip_bar, bg="#111827", fg="white", font=("맑은 고딕", 11, "bold"), padx=7, pady=2,
                               anchor="w")
                lab.grid(row=row, column=col, sticky="w")
                self.strip[coin] = lab
            lab = self.strip[coin]
            old = self.live.get(coin, (price, ch))[0]
            arrow = "▲" if ch > 0 else "▼" if ch < 0 else "-"
            num = f"{price:,.0f}" if price >= 100 else f"{price:,.2f}"
            lab.config(text=f"{coin} {num} {arrow}{abs(ch):.2f}%",
                       fg="#fca5a5" if ch > 0 else "#93c5fd" if ch < 0 else "white")
            if price != old:  # 가격이 바뀌면 잠깐 배경 깜빡임
                lab.config(bg="#7f1d1d" if price > old else "#1e3a8a")
                lab.after(500, lambda l=lab: l.config(bg="#111827"))
        self.live.update(data)
        for coin in fr.COINS:
            if coin in data:
                self.prices[coin] = data[coin][0]
        if self.icon:
            self.icon.title = "\n".join(f"{c} {p:,.0f}" for c, (p, _) in data.items() if c in fr.COINS)

    # ---------------- 자동매매 (물타기) ----------------
    def build_grid(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="  자동매매  ")
        g = self.cfg["grid"]
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        self.g_on = tk.BooleanVar(value=g["enabled"])
        self.g_sim = tk.BooleanVar(value=g["simulate"])
        self.g_half = tk.BooleanVar(value=g["half_at_breakeven"])
        ttk.Checkbutton(bar, text="켜기", variable=self.g_on).pack(side="left")
        ttk.Checkbutton(bar, text="모의", variable=self.g_sim).pack(side="left", padx=6)
        self.g_fields = {}
        for key, label, val, w in (("coins", "코인", ",".join(g["coins"]), 16), ("unit_krw", "1회", g["unit_krw"], 8),
                                   ("drop_pct", "하락%", g["drop_pct"], 5), ("profit_krw", "익절원", g["profit_krw"], 6),
                                   ("max_krw", "한도", g["max_krw"], 9)):
            ttk.Label(bar, text=label).pack(side="left", padx=(8, 2))
            e = ttk.Entry(bar, width=w)
            e.insert(0, str(val))
            e.pack(side="left")
            self.g_fields[key] = e
        ttk.Checkbutton(bar, text="본전 절반 매도", variable=self.g_half).pack(side="left", padx=8)
        ttk.Button(bar, text="저장", command=self.save_grid).pack(side="left")
        ttk.Label(f, text="규칙: 시작 매수 → 마지막 매수가 대비 하락%마다 1회 금액 추가 매수 → (2회 이상 샀으면) 본전에 절반 매도"
                          " → 사이클 수익이 익절원 이상이면 전량 매도 후 다시 시작. BTC·ETH·XRP는 제외.",
                  foreground="#555", wraplength=1000).pack(anchor="w", pady=4)
        cols = (("coin", "코인", 60), ("price", "현재가", 100), ("buys", "매수", 45), ("cost", "원가", 85),
                ("avg", "평단", 95), ("pnl", "평가손익", 80), ("next", "다음 매수가", 100), ("be", "본전 절반가", 100),
                ("tp", "익절가", 100), ("cyc", "사이클", 55), ("tot", "누적 수익", 85))
        self.grid_tree = ttk.Treeview(f, columns=[c for c, _, _ in cols], show="headings", height=5)
        for c, t, w in cols:
            self.grid_tree.heading(c, text=t)
            self.grid_tree.column(c, width=w, anchor="e" if c != "coin" else "center")
        self.grid_tree.tag_configure("up", foreground="#b91c1c")
        self.grid_tree.tag_configure("down", foreground="#1d4ed8")
        self.grid_tree.pack(fill="x")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=4)
        self.grid_sum = ttk.Label(row, text="")
        self.grid_sum.pack(side="left")
        ttk.Button(row, text="선택 코인 청산", command=self.grid_liquidate).pack(side="right")
        ttk.Label(f, text="자동매매 거래 기록").pack(anchor="w", pady=(6, 0))
        self.grid_log = self.table(f, (("ts", "시간", 150), ("sim", "모의", 45), ("coin", "코인", 60), ("side", "구분", 50),
                                       ("price", "가격", 110), ("qty", "수량", 140), ("krw", "금액", 100)), 10)

    def render_grid(self, rows):
        self.grid_tree.delete(*self.grid_tree.get_children())
        num = lambda v: "-" if v is None else f"{v:,.4g}" if v < 1000 else f"{v:,.0f}"  # noqa: E731
        cost = tot = pnl = 0
        for r in rows:
            cost, tot, pnl = cost + r["cost"], tot + r["profit_total"], pnl + r["pnl"]
            self.grid_tree.insert("", "end", iid=r["coin"], tags=("up" if r["pnl"] > 0 else "down",), values=(
                r["coin"], num(r["price"]), r["buys"], f"{r['cost']:,.0f}", num(r["avg"]), f"{r['pnl']:+,.0f}",
                num(r["next_buy"]), num(r["breakeven"]), num(r["tp"]), r["cycles"], f"{r['profit_total']:+,.0f}"))
        g = self.cfg["grid"]
        state = ("꺼짐" if not g["enabled"] else "모의" if g["simulate"] or not self.engine.api else "실전")
        self.grid_sum.config(text=f"[{state}] 투입 원가 {cost:,.0f}원 · 평가손익 {pnl:+,.0f}원 · 누적 실현 {tot:+,.0f}원")

    def render_grid_log(self):
        self.grid_log.delete(*self.grid_log.get_children())
        for ts, sim, coin, side, price, qty, krw, _ in self.db.query(
                "SELECT * FROM grid_trades ORDER BY rowid DESC LIMIT 200"):
            self.grid_log.insert("", "end", values=(ts[:19].replace("T", " "), "예" if sim else "", coin,
                                                    "매수" if side == "bid" else "매도",
                                                    f"{price:,.4g}" if price < 1000 else f"{price:,.0f}",
                                                    f"{qty:g}", f"{krw:,.0f}"))

    def save_grid(self):
        g, fl = self.cfg["grid"], self.g_fields
        try:
            coins = [c.strip().upper() for c in fl["coins"].get().split(",") if c.strip()]
            blocked = [c for c in coins if c in core.GRID_BLOCKED]
            new = {"coins": [c for c in coins if c not in core.GRID_BLOCKED],
                   "unit_krw": int(float(fl["unit_krw"].get())), "drop_pct": float(fl["drop_pct"].get()),
                   "profit_krw": int(float(fl["profit_krw"].get())), "max_krw": int(float(fl["max_krw"].get()))}
        except ValueError as e:
            messagebox.showerror("자동매매", f"숫자를 확인하세요: {e}")
            return
        if new["unit_krw"] < 5000:
            messagebox.showerror("자동매매", "업비트 최소 주문이 5,000원이라 1회 금액은 5,000원 이상이어야 합니다.")
            return
        going_live = self.g_on.get() and not self.g_sim.get() and (g["simulate"] or not g["enabled"])
        if going_live and not messagebox.askyesno(
                "자동매매 실전", f"⚠ 실전으로 켜면 승인 없이 업비트에 시장가 주문이 자동으로 나갑니다.\n"
                f"코인 {', '.join(new['coins'])} · 1회 {new['unit_krw']:,}원 · 코인별 한도 {new['max_krw']:,}원\n\n진행할까요?",
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
        messagebox.showinfo("자동매매", msg)

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
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="  주문  ")
        self.orders_tab = f
        self.prop_reason = ttk.Label(f, text="제안 없음", style="Big.TLabel")
        self.prop_reason.pack(anchor="w")
        cols = (("st", "상태", 70), ("coin", "코인", 60), ("label", "구분", 170), ("price", "가격", 120),
                ("vol", "수량", 130), ("krw", "금액(원)", 120))
        holder = ttk.Frame(f)
        holder.pack(fill="both", expand=True, pady=6)
        self.prop_tree = ttk.Treeview(holder, columns=[c for c, _, _ in cols], show="headings", height=16)
        sb = ttk.Scrollbar(holder, orient="vertical", command=self.prop_tree.yview)
        self.prop_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        for c, t, w in cols:
            self.prop_tree.heading(c, text=t)
            self.prop_tree.column(c, width=w, anchor="e" if c in ("price", "vol", "krw") else "center")
        for tag, color in (("유지", "#666"), ("주문", "#15803d"), ("취소", "#b91c1c")):
            self.prop_tree.tag_configure(tag, foreground=color)
        self.prop_tree.pack(side="left", fill="both", expand=True)
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Button(row, text="플랜과 다시 비교", command=lambda: self.engine.request("make_proposal", "수동 비교", True)).pack(side="left")
        ttk.Button(row, text="레벨 재계산", command=self.recalc).pack(side="left", padx=6)
        self.btn_ok = ttk.Button(row, text="승인·실행", command=self.approve)
        self.btn_ok.pack(side="right")
        ttk.Button(row, text="무시", command=self.dismiss).pack(side="right", padx=6)
        self.result = tk.Text(f, height=7, wrap="none")
        self.result.pack(fill="x", pady=(6, 0))

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
                st, coin, label, fmt(o["price"]), f"{o['volume']:g}", fmt(o["price"] * o["volume"])))

    def approve(self):
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
            self.btn_ok.state(["disabled"])
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
            "긴급 정지", "자동 제안을 멈추고 '알림만' 모드로 바꿉니다.\n\n"
            "업비트의 BTC·ETH·XRP 미체결 주문도 전부 취소할까요?\n(예: 전부 취소 / 아니요: 모드만 변경)")
        if ans is not None:
            self.engine.request("emergency_stop", ans)
            self.mode_var.set("alert")
            self.g_on.set(False)

    # ---------------- ③ 알림·기록 ----------------
    def build_logs(self, nb):
        f = ttk.Frame(nb, padding=8)
        nb.add(f, text="  알림·기록  ")
        ttk.Label(f, text="알림").pack(anchor="w")
        self.alert_tree = self.table(f, (("ts", "시간", 150), ("title", "제목", 200), ("msg", "내용", 620)), 12)
        ttk.Label(f, text="주문 실행 기록").pack(anchor="w", pady=(8, 0))
        self.act_tree = self.table(f, (("ts", "시간", 150), ("sim", "모의", 50), ("what", "내용", 400),
                                       ("res", "결과", 370)), 8)
        ttk.Button(f, text="새로고침", command=self.render_logs).pack(anchor="e", pady=4)

    def table(self, parent, cols, height):
        t = ttk.Treeview(parent, columns=[c for c, _, _ in cols], show="headings", height=height)
        for c, text, w in cols:
            t.heading(c, text=text)
            t.column(c, width=w, anchor="w")
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
            self.act_tree.insert("", "end", values=(ts[:19].replace("T", " "), "예" if sim else "",
                                                    f"{word}{price:,.0f} × {vol:g}", res))

    # ---------------- ④ 설정 ----------------
    def build_settings(self, nb):
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text="  설정  ")
        c = self.cfg
        self.mode_var = tk.StringVar(value=c["mode"])
        self.sim_var = tk.BooleanVar(value=c["simulate"])
        self.fields = {}
        r = 0

        def row(label, widget):
            nonlocal r
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, sticky="w", pady=3)
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
        entry("every_sec", "확인 간격 (초)", c["every_sec"], 8)
        entry("max_order_krw", "1건 최대 금액 (원)", c["max_order_krw"])
        entry("max_orders_per_day", "하루 최대 실주문 (건)", c["max_orders_per_day"], 8)
        entry("volume_tol_pct", "수량 차이 허용 (%)", c["volume_tol_pct"], 8)
        for coin in fr.COINS:
            entry(f"dca_{coin}", f"  {coin} 매일 모으기 (원)", c["dca_daily"].get(coin, 0), 10)
        for coin in fr.COINS:
            pg = c["progress"][coin]
            box = ttk.Frame(f)
            sd, bd = tk.Spinbox(box, from_=0, to=3, width=3), tk.Spinbox(box, from_=0, to=3, width=3)
            sd.delete(0, "end"), sd.insert(0, pg["sell_done"])
            bd.delete(0, "end"), bd.insert(0, pg["buy_done"])
            ttk.Label(box, text="매도 체결 단계").pack(side="left")
            sd.pack(side="left", padx=4)
            ttk.Label(box, text="매수 체결 단계").pack(side="left", padx=(10, 0))
            bd.pack(side="left", padx=4)
            self.fields[f"sd_{coin}"], self.fields[f"bd_{coin}"] = sd, bd
            row(f"  {coin} 진행", box)
        keys = "연결됨 (UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY)" if self.engine.api else "없음 — setx로 키를 저장한 뒤 다시 실행"
        row("업비트 API 키", ttk.Label(f, text=keys))
        btns = ttk.Frame(f)
        ttk.Button(btns, text="저장", command=self.save_settings).pack(side="left")
        ttk.Button(btns, text="바탕화면 바로가기 만들기", command=self.desktop_link).pack(side="left", padx=6)
        ttk.Button(btns, text="PC 켤 때 자동 실행", command=self.startup_link).pack(side="left")
        ttk.Button(btns, text="자동 실행 해제", command=self.remove_startup).pack(side="left", padx=6)
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
        except ValueError as e:
            messagebox.showerror("설정", f"숫자를 확인하세요: {e}")
            return
        if abs(sum(c["buy_split"].values()) - 1) > 0.001:
            messagebox.showwarning("설정", "코인 예산 비중 합이 1이 아닙니다. 그래도 저장합니다.")
        core.save_config(c)
        self.engine.load_levels()
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
    def pump(self):
        while not self.ui_calls.empty():
            self.ui_calls.get_nowait()()
        changed_logs = False
        while not self.events.empty():
            ev = self.events.get_nowait()
            kind = ev[0]
            if kind == "status":
                self.status.config(text=ev[1])
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
                self.render_strip(ev[1])
                self.render_board()
            elif kind == "hold":
                self.hold = ev[1]
                self.render_board()
            elif kind == "grid":
                self.render_grid(ev[1])
            elif kind == "proposal":
                self.proposal = ev[1]
                self.render_proposal()
            elif kind == "done":
                self.btn_ok.state(["!disabled"])
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
        ctypes.windll.user32.MessageBoxW(0, "FibTrader가 이미 실행 중입니다. 트레이 아이콘을 확인하세요.", "FibTrader", 0x40)
        sys.exit(0)
    App().run()
