"""FibTrader: 피보나치 플랜 감시·알림·반자동 주문 (트레이 + 대시보드).

처음 한 번: install.bat 실행 (라이브러리·글꼴 설치 + 바탕화면 아이콘)
실행: 바탕화면 FibTrader 아이콘 더블클릭
창을 닫으면 트레이로 숨고, 트레이 아이콘 오른쪽 클릭 → 종료로 끝낸다.
화면 디자인: 다크 테마, 현황 1b(선택 집중) + 통합 앱 사양 12장 (디자인 스펙 md 기준)
"""
import ctypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
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
ALERT_GROUP = {"proposal": "주문", "fill": "주문", "hit": "주문", "near": "주문", "cancel": "주문", "grid": "매매"}
GROUP_COLOR = {"주문": T.DOWN, "매매": T.UP, "시스템": T.MUTED}
TAB_BOARD, TAB_INVEST, TAB_JOURNAL, TAB_GRID, TAB_ORDERS, TAB_LOGS, TAB_SETTINGS = range(7)

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


def lab(parent, text="", font="kr", fg=T.TEXT, bg=T.PANEL, **kw):
    return tk.Label(parent, text=text, font=T.F[font], fg=fg, bg=bg, **kw)


def card(parent, title=None, sub=None, packed=True, **pack):
    """카드: PANEL 배경 + 1px DIVIDER 테두리. (카드, 제목줄) 반환. 제목줄 오른쪽에 버튼을 붙일 수 있다."""
    box = tk.Frame(parent, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
    if packed:
        box.pack(fill="x", **pack)
    head = None
    if title:
        head = tk.Frame(box, bg=T.PANEL)
        head.pack(fill="x", padx=16, pady=(14, 8))
        lab(head, title, "kr_panel").pack(side="left")
        if sub:
            lab(head, sub, "kr_xs", fg=T.MUTED).pack(side="left", padx=10, pady=(3, 0))
    return box, head


def num(text):
    """입력칸 숫자 (콤마·공백 허용)."""
    return float(str(text).replace(",", "").replace(" ", "") or "nan")


def man(v):
    """만 원 단위 짧은 표기: 30,005 → 3.0만, 5,000,000 → 500만."""
    v = v / 10_000
    return f"{v:,.1f}만" if v < 100 else f"{v:,.0f}만"


def plan_label(label):
    """플랜 라벨 '1차 매수 38.2% (20%)' → ('1차 매수', '38.2% · 20%')."""
    parts = label.split()
    return " ".join(parts[:2]), " ".join(parts[2:]).replace("(", "· ").replace(")", "")


class App:
    def __init__(self):
        self.cfg = core.load_config()
        ui = self.cfg.setdefault("ui", {})
        for k, v in {"charts_open": [], "inv_charts_open": [], "near_highlight_pct": 5, "last_tab": 0,
                     "sel_coin": "BTC", "chart_1b": False, "grid_rules_open": False, "orders_filter": "변경만",
                     "alerts_seen": 0, "alerts_read": 0}.items():
            ui.setdefault(k, v)
        self.db = core.DB()
        self.events = queue.Queue()
        self.ui_calls = queue.Queue()
        self.engine = core.Engine(self.cfg, self.db, self.events)
        self.proposal, self.prop_seen, self.prop_time = None, None, ""
        self.prices, self.board = {}, {}
        self.live = {}      # coin -> (현재가, 전일 대비 %, 전일 대비 금액)
        self.hold = {}      # currency -> 보유 수량 (주문에 묶인 것 포함)
        self.accounts = []  # 업비트 잔고 (평단 포함)
        self.open_orders = {c: [] for c in fr.COINS}
        self.grid_rows = []
        self.alert_data, self.recent_alerts, self.alert_open, self.alert_readset = [], None, set(), set()
        self.alert_filter = "전체"
        self.executing, self.closing = False, False
        self.last_status_ts = 0
        self.sel_coin = ui["sel_coin"] if ui["sel_coin"] in fr.COINS else fr.COINS[0]
        self.stale = set()

        T.load_private_fonts()
        self.root = tk.Tk()
        self.root.title("FibTrader")
        self.root.geometry("1440x900")
        self.root.minsize(1280, 800)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        T.setup_fonts(self.root)
        T.apply_ttk(self.root)
        W.install_wheel(self.root)

        # 12-1 상단바: 브랜드 | 탭(배지) | (빈칸) | 상태 태그 | API 상태 | 긴급 정지·재개
        top = tk.Frame(self.root, bg=T.PANEL, height=40)
        top.pack(fill="x")
        lab(top, "FIBTRADER", "brand", padx=18).pack(side="left", fill="y")
        tk.Frame(top, bg=T.DIVIDER, width=1).pack(side="left", fill="y")
        tabbar = tk.Frame(top, bg=T.PANEL)
        tabbar.pack(side="left", fill="y")
        right = tk.Frame(top, bg=T.PANEL)
        right.pack(side="right", fill="y", padx=(0, 12))
        self.tags = {}
        for key in ("mode", "sim"):
            t = lab(right, "", "tag", fg=T.ACCENT, padx=6, pady=1, highlightthickness=1, highlightbackground=T.ACCENT)
            t.pack(side="left", padx=3, pady=10)
            self.tags[key] = t
        self.stop_tag = lab(right, "정지됨", "tag", fg=T.GROUND, bg=T.UP, padx=6, pady=2)
        self.status_dot = lab(right, "●", "num_xs", fg=T.DOWN, padx=0)
        self.status_dot.pack(side="left", padx=(12, 4))
        self.status = lab(right, "시작 중…", "kr_s", fg=T.MUTED)
        self.status.pack(side="left", padx=(0, 14))
        self.stop_btn = T.Btn(right, "긴급 정지", self.emergency, "danger")
        self.stop_btn.pack(side="left", pady=5)
        self.topdiv = tk.Frame(self.root, bg=T.DIVIDER, height=1)
        self.topdiv.pack(fill="x")

        # 티커(현황에서는 숨김) · 모의 배너 · 결과 알림 줄: 순서를 지키려고 한 칸에 모아 둔다
        self.chrome = tk.Frame(self.root, bg=T.GROUND)
        self.chrome.pack(fill="x")
        self.ticker_box = tk.Frame(self.chrome, bg=T.GROUND)
        self.ticker = W.Ticker(self.ticker_box)
        self.ticker.pack(fill="x")
        tk.Frame(self.ticker_box, bg=T.DIVIDER, height=1).pack(fill="x")
        self.sim_banner = lab(self.chrome, "모의 모드 · 승인해도 실제 주문은 나가지 않습니다", "kr_s", fg=T.ACCENT_200,
                              bg=T.BANNER_BG, anchor="w", padx=16, pady=3)
        self.notice = tk.Frame(self.chrome, bg=T.BANNER_BG)
        self.notice_lab = lab(self.notice, "", "kr_s", fg=T.TEXT, bg=T.BANNER_BG, anchor="w", justify="left")
        self.notice_lab.pack(side="left", padx=16, pady=4)
        x = lab(self.notice, "✕", "kr_s", fg=T.MUTED, bg=T.BANNER_BG, cursor="hand2", padx=12)
        x.pack(side="right")
        x.bind("<Button-1>", lambda e: self.hide_notice())
        link = lab(self.notice, "알림·기록 보기", "kr_s", fg=T.ACCENT, bg=T.BANNER_BG, cursor="hand2")
        link.pack(side="right", padx=6)
        link.bind("<Button-1>", lambda e: self.nb.select(TAB_LOGS))
        self.notice_after = None

        self.nb = W.Tabs(self.root, tabbar)
        self.nb.pack(fill="both", expand=True)
        self.build_board(self.nb)
        self.build_invest(self.nb)
        self.build_journal(self.nb)
        self.build_grid(self.nb)
        self.build_orders(self.nb)
        self.build_logs(self.nb)
        self.build_settings(self.nb)
        self.renderers = {TAB_BOARD: self.render_board, TAB_INVEST: self.render_invest, TAB_JOURNAL: self.render_journal,
                          TAB_GRID: self.render_grid_tab,
                          TAB_ORDERS: self.render_proposal, TAB_LOGS: self.render_logs}
        self.prev_tab = None
        self.nb.on_change = self.on_tab
        last = ui.get("last_tab", 0)
        self.nb.select(last if isinstance(last, int) and 0 <= last < 7 else 0)
        self.refresh_chrome()
        self.root.bind("<Map>", lambda e: e.widget is self.root and self.root.after(50, self.redraw_stale))

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
        self.root.after(50, self.redraw_stale)
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

    def hidden(self):
        try:
            return self.root.state() in ("withdrawn", "iconic")
        except tk.TclError:
            return True

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

    def center(self, w):
        w.update_idletasks()
        ww, wh = w.winfo_reqwidth(), w.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - ww) // 2
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - wh) // 2)
        w.geometry(f"{ww}x{wh}+{max(0, x)}+{max(0, y)}")

    def dialog(self, title, tag=None, tag_color=T.ACCENT):
        """스펙 확인 창: PANEL, 1px 테두리, 제목 + 오른쪽 태그. (창, 본문) 반환."""
        w = tk.Toplevel(self.root, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        w.title(title)
        w.transient(self.root)
        w.resizable(False, False)
        head = tk.Frame(w, bg=T.PANEL)
        head.pack(fill="x", padx=16, pady=(16, 10))
        lab(head, title, "kr_big").pack(side="left")
        if tag:
            lab(head, tag, "tag", fg=tag_color, padx=8, pady=2, highlightthickness=1,
                highlightbackground=tag_color).pack(side="right")
        body = tk.Frame(w, bg=T.PANEL)
        body.pack(fill="x", padx=16)
        return w, body

    def dialog_buttons(self, w, cancel, ok, on_ok, danger=False):
        row = tk.Frame(w, bg=T.PANEL)
        row.pack(fill="x", padx=16, pady=16)
        T.Btn(row, ok, lambda: (w.destroy(), on_ok()), "danger" if danger else "primary").pack(side="right")
        T.Btn(row, cancel, w.destroy).pack(side="right", padx=8)
        self.center(w)
        w.grab_set()
        w.focus_force()

    # ---------------- 공통 크롬 ----------------
    def relayout_chrome(self):
        """티커 → 모의 배너 → 결과 알림 줄 순서로 보여야 할 것만 다시 붙인다."""
        want = [(self.ticker_box, self.nb.index() != TAB_BOARD),
                (self.sim_banner, self.cfg["simulate"] or not self.engine.api),
                (self.notice, self.notice_lab.cget("text") != "")]
        for w_, _ in want:
            w_.pack_forget()
        for w_, on in want:
            if on:
                w_.pack(fill="x")

    def refresh_chrome(self):
        """상단 태그·모의 배너·정지 상태를 설정에 맞춘다."""
        self.tags["mode"].config(text="반자동" if self.cfg["mode"] == "semi" else "알림만")
        sim = self.cfg["simulate"] or not self.engine.api
        if sim:
            self.tags["sim"].config(text="모의")
            if not self.tags["sim"].winfo_ismapped():
                self.tags["sim"].pack(side="left", padx=3, pady=10, after=self.tags["mode"])
        else:  # 실전이면 모의 태그와 배너를 모든 탭에서 숨긴다
            self.tags["sim"].pack_forget()
        stopped = bool(self.cfg.get("stopped"))
        if stopped and not self.stop_tag.winfo_ismapped():
            self.stop_tag.pack(side="left", padx=3, pady=10, before=self.status_dot)
        elif not stopped:
            self.stop_tag.pack_forget()
        b = self.stop_btn
        if stopped:
            b.config(text="재개", bg=T.UP, fg=T.GROUND, highlightbackground=T.UP)
            b.normal_bg, b.command = T.UP, self.resume
        else:
            b.config(text="긴급 정지", bg=T.PANEL, fg=T.UP, highlightbackground=T.UP)
            b.normal_bg, b.command = T.PANEL, self.emergency
        self.relayout_chrome()

    def show_notice(self, text, secs=15):
        self.notice_lab.config(text=text)
        self.relayout_chrome()
        if self.notice_after:
            self.root.after_cancel(self.notice_after)
        self.notice_after = self.root.after(secs * 1000, self.hide_notice)

    def hide_notice(self):
        self.notice_lab.config(text="")
        self.notice_after = None
        self.relayout_chrome()

    def on_tab(self, idx):
        if self.prev_tab == TAB_LOGS and idx != TAB_LOGS:  # 알림·기록을 보고 나가면 본 알림은 읽음
            self.cfg["ui"]["alerts_read"] = self.max_alert_id()
        if idx == TAB_LOGS:
            self.cfg["ui"]["alerts_seen"] = self.max_alert_id()
            self.nb.set_badge(TAB_LOGS, 0)
        self.prev_tab = idx
        self.cfg["ui"]["last_tab"] = idx
        core.save_config(self.cfg)
        if hasattr(self, "notice"):
            self.relayout_chrome()
        self.stale.add(idx)
        self.redraw_stale()

    def shown(self, tab):
        """그 탭이 지금 화면에 보이는지. 안 보이면 다시 그리지 않고 표시만 해 뒀다가 보일 때 그린다 (가볍게)."""
        on = not self.hidden() and self.nb.index() == tab
        if not on:
            self.stale.add(tab)
        return on

    def redraw_stale(self, *_):
        if not hasattr(self, "renderers") or self.hidden():
            return
        idx = self.nb.index()
        if idx in self.stale:
            self.stale.discard(idx)
            self.renderers.get(idx, lambda: None)()
        if self.live and idx != TAB_BOARD:
            self.render_strip({})

    # ---------------- ① 현황 (1b: 선택 집중) ----------------
    def build_board(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "현황")
        self.board_tab = f
        # 하단 요약바
        self.sumbar = W.SummaryBar(f, [("coins", "코인 평가 (BTC·ETH·XRP)"), ("cash", "현금"), ("total", "총자산"),
                                       ("free", "주문 가능 현금"), ("dca", "모으기"), ("grid", "자동매매 예산"),
                                       ("lvl", "레벨 기준 시각")])
        self.sumbar.pack(side="bottom", fill="x")
        self.drift_btn = T.Btn(self.sumbar, "레벨 변화 지금 확인", self.check_drift_now)
        self.drift_btn.pack(side="right", padx=16)
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
        ttk.Checkbutton(db, text="앞으로 자동 반영", variable=self.auto_drift, command=self.toggle_auto_drift,
                        style="Panel.TCheckbutton").pack(side="left", padx=6)

        body = tk.Frame(f, bg=T.GROUND)
        body.pack(fill="both", expand=True)
        self.board_body = body
        self.coin_list = W.CoinList(body, on_select=self.select_coin, on_link=lambda _t: self.nb.select(TAB_GRID))
        self.coin_list.pack(side="left", fill="y")
        tk.Frame(body, bg=T.DIVIDER, width=1).pack(side="left", fill="y")
        side = tk.Frame(body, bg=T.PANEL, width=460)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)
        tk.Frame(body, bg=T.DIVIDER, width=1).pack(side="right", fill="y")
        center = tk.Frame(body, bg=T.GROUND)
        center.pack(side="left", fill="both", expand=True, padx=24, pady=(18, 16))
        self.build_center(center)
        self.build_side(side)

    def build_center(self, c):
        g = T.GROUND
        hdr = tk.Frame(c, bg=g)
        hdr.pack(fill="x")
        self.c_sym = lab(hdr, self.sel_coin, "sym", bg=g)
        self.c_sym.pack(side="left")
        self.c_state = lab(hdr, "", "kr_s", fg=T.MUTED, bg=g)
        self.c_state.pack(side="left", padx=8, pady=(4, 0))
        self.c_hold_line = lab(hdr, "", "kr_s", fg=T.MUTED, bg=g)
        prow = tk.Frame(c, bg=g)
        prow.pack(fill="x")
        self.c_holdbox = tk.Frame(prow, bg=g)
        self.c_holdbox.pack(side="right", anchor="s", pady=(0, 12))
        self.c_hold1 = lab(self.c_holdbox, "", "kr_s", fg=T.MUTED, bg=g)
        self.c_hold1.pack(anchor="e")
        self.c_hold2 = lab(self.c_holdbox, "", "kr_s", fg=T.MUTED, bg=g)
        self.c_hold2.pack(anchor="e")
        self.c_price = lab(prow, "-", "price_xl", bg=g)
        self.c_price.pack(side="left")
        self.c_chg = lab(prow, "", "chg", bg=g)
        self.c_chg.pack(side="left", padx=(14, 0), anchor="s", pady=(0, 12))
        self.c_narrow = False
        c.bind("<Configure>", self.center_resize)
        ma = tk.Frame(c, bg=g)
        ma.pack(fill="x", pady=(6, 0))
        self.c_ma, self.c_ma_boxes = [], []
        for i in range(2):
            box = tk.Frame(ma, bg=g, highlightthickness=1, highlightbackground=T.DIVIDER)
            box.pack(side="left", fill="x", expand=True, padx=(0, 10) if i == 0 else 0)
            self.c_ma_boxes.append(box)
            parts = [lab(box, "", "num_s", fg=T.MUTED, bg=g) for _ in range(4)]
            parts[0].pack(side="left", padx=(12, 0), pady=9)
            parts[1].pack(side="left", padx=(18, 0))
            parts[2].pack(side="left", padx=(18, 0))
            parts[3].pack(side="right", padx=12)
            self.c_ma.append(parts)
        ct = tk.Frame(c, bg=g)
        ct.pack(fill="x", pady=(14, 6))
        lab(ct, "4H 캔들 · 피보나치 레벨", "kr_xs", fg=T.MUTED, bg=g).pack(side="left")
        self.c_chart_btn = T.Btn(ct, "차트 ▾", self.toggle_center_chart, "ghost", bg=g)
        self.c_chart_btn.pack(side="right")
        self.c_chart = W.Candles(c, height=220)
        self.c_ruler = W.Ruler(c)
        self.c_ruler.pack(fill="both", expand=True)
        if self.cfg["ui"]["chart_1b"]:
            self.c_chart.pack(fill="x", pady=(0, 12), before=self.c_ruler)
            self.c_chart_btn.config(text="차트 ▴")

    def center_resize(self, e):
        narrow = e.width < 600  # 1280px 창: 보유·평가를 가격 줄 오른쪽에서 제목 줄로 올린다
        if narrow == self.c_narrow:
            return
        self.c_narrow = narrow
        if narrow:  # MA 지표 2칸도 위아래로
            self.c_holdbox.pack_forget()
            self.c_hold_line.pack(side="right", pady=(4, 0))
            for i, box in enumerate(self.c_ma_boxes):
                box.pack_configure(side="top", padx=0, pady=(0, 6) if i == 0 else 0)
        else:
            self.c_hold_line.pack_forget()
            self.c_holdbox.pack(side="right", anchor="s", pady=(0, 12), before=self.c_price)
            for i, box in enumerate(self.c_ma_boxes):
                box.pack_configure(side="left", padx=(0, 10) if i == 0 else 0, pady=0)

    def build_side(self, s):
        head = tk.Frame(s, bg=T.PANEL)
        head.pack(fill="x", padx=16, pady=(16, 6))
        self.s_title = lab(head, "", "kr_panel")
        self.s_title.pack(side="left")
        self.s_count = lab(head, "", "kr_xs", fg=T.MUTED)
        self.s_count.pack(side="right")
        cols = [{"key": "chk", "w": 22}, {"key": "st", "title": "상태", "w": 72},
                {"key": "name", "title": "구분", "w": 64, "grow": 1},
                {"key": "price", "title": "가격", "w": 96, "anchor": "e"},
                {"key": "qty", "title": "수량", "w": 80, "anchor": "e"},
                {"key": "amt", "title": "금액", "w": 74, "anchor": "e"}]
        self.s_table = W.Table(s, cols, rh=36, check=True, fit=True, pad=12, min_rows=6,
                               empty=["예약 주문이 없습니다", "레벨 계산이 끝나면 플랜 주문이 표시됩니다"])
        self.s_table.pack(fill="x")
        btns = tk.Frame(s, bg=T.PANEL)
        btns.pack(fill="x", padx=16, pady=12)
        T.Btn(btns, "선택 취소", self.cancel_selected).pack(side="left")
        T.Btn(btns, "전체 취소", lambda: self.cancel_coin(self.sel_coin)).pack(side="left", padx=8)
        T.Btn(btns, "플랜대로 다시 걸기", lambda: self.replan_coin(self.sel_coin), "primary").pack(side="right")
        self.s_approve = tk.Frame(s, bg=T.PANEL, highlightthickness=1, highlightbackground=T.ACCENT)
        self.s_approve_lab = lab(self.s_approve, "", "kr_b")
        self.s_approve_lab.pack(side="left", padx=12, pady=12)
        T.Btn(self.s_approve, "주문 탭에서 승인", lambda: self.nb.select(TAB_ORDERS), "primary").pack(side="right", padx=8)
        self.s_div = tk.Frame(s, bg=T.DIVIDER, height=1)
        self.s_div.pack(fill="x")
        ah = tk.Frame(s, bg=T.PANEL)
        ah.pack(fill="x", padx=16, pady=(14, 4))
        lab(ah, "최근 알림", "kr_panel").pack(side="left")
        link = lab(ah, "알림·기록 전체", "kr_xs", fg=T.ACCENT, cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda e: self.nb.select(TAB_LOGS))
        self.s_alerts = tk.Frame(s, bg=T.PANEL)
        self.s_alerts.pack(fill="both", expand=True)
        self.s_alerts_shown = None

    def toggle_center_chart(self):
        on = not self.cfg["ui"]["chart_1b"]
        self.cfg["ui"]["chart_1b"] = on
        core.save_config(self.cfg)
        if on:
            self.c_chart.pack(fill="x", pady=(0, 12), before=self.c_ruler)
        else:
            self.c_chart.pack_forget()
        self.c_chart_btn.config(text="차트 ▴" if on else "차트 ▾")
        self.render_board()

    def select_coin(self, coin):
        if coin not in fr.COINS:  # 자동매매 코인은 자동매매 탭에서
            self.nb.select(TAB_GRID)
            return
        self.sel_coin = coin
        self.cfg["ui"]["sel_coin"] = coin
        core.save_config(self.cfg)
        self.s_table.checked.clear()
        self.render_board()

    def plan_base(self, coin):
        """매도 수량 기준(체결 전 보유량)과 매수 예산."""
        pg = self.cfg["progress"][coin]
        hold = self.hold.get(coin, 0.0)
        done_w = sum(w for _, w in fr.SELL_STEPS[:pg["sell_done"]])
        base = hold / (1 - done_w) if done_w < 1 else 0
        return base, self.cfg["buy_budget"] * self.cfg["buy_split"][coin]

    def order_rows(self, coin):
        """오른쪽 주문 패널: 플랜 레벨마다 대기(주문 걸림) / 승인 필요(미주문) / 지남, 플랜 밖 예약은 따로."""
        p = self.prices.get(coin)
        lv = self.cfg.get("levels", {}).get(coin)
        if not lv or not p:
            return []
        pg = self.cfg["progress"][coin]
        base, budget = self.plan_base(coin)
        orders = list(self.open_orders.get(coin, []))
        out = []

        def take(side, price):
            m = next((o for o in orders if o["side"] == side and abs(o["price"] - price) < 1e-9), None)
            if m:
                orders.remove(m)
            return m

        steps = [("ask", i, f"{name} 매도", price, base * w, price > p, T.DOWN)
                 for i, ((name, w), price) in enumerate(zip(fr.SELL_STEPS, lv["sells"])) if i >= pg["sell_done"]]
        steps += [("bid", i, f"{i + 1}차 매수", price, budget * w / price, price < p, T.UP)
                  for i, ((_, w), price) in enumerate(zip(fr.BUY_STEPS, lv["buys"])) if i >= pg["buy_done"]]
        for side, i, name, price, qty, eligible, color in steps:
            m = take(side, price)
            if m:
                st, rid, qty = ("대기", T.DOWN), m["uuid"], m["volume"]
            else:
                st, rid = (("승인 필요", T.MUTED) if eligible else ("지남", T.MUTED)), f"{side}{i}"
            out.append({"id": rid, "check": bool(m), "price": price, "cells": {
                "st": {"tag": st}, "name": {"text": name, "fg": color},
                "price": {"text": T.fmtp(price), "font": "num"},
                "qty": {"text": T.fmtq_c(coin, qty), "fg": T.MUTED, "font": "num_s"},
                "amt": {"text": T.fmtk(qty * price), "font": "num_s"}}})
        for o in orders:  # 플랜 가격과 다른 예약 주문
            out.append({"id": o["uuid"], "check": True, "price": o["price"], "bg": T.blend(T.UP, T.PANEL, 0.07), "cells": {
                "st": {"tag": ("플랜 밖", T.UP, True)},
                "name": {"text": "예약 매도" if o["side"] == "ask" else "예약 매수"},
                "price": {"text": T.fmtp(o["price"]), "font": "num"},
                "qty": {"text": T.fmtq_c(coin, o["volume"]), "fg": T.MUTED, "font": "num_s"},
                "amt": {"text": T.fmtk(o["volume"] * o["price"]), "font": "num_s"}}})
        out.sort(key=lambda r: -r["price"])
        return out

    def ruler_rows(self, coin):
        p = self.prices.get(coin)
        lv = self.cfg.get("levels", {}).get(coin)
        if not lv or not p:
            return []
        pg = self.cfg["progress"][coin]
        near = self.cfg["ui"].get("near_highlight_pct", 5)
        rows = []
        for i, ((name, w), price) in enumerate(zip(fr.SELL_STEPS, lv["sells"])):
            done = i < pg["sell_done"]
            rows.append({"kind": "sell", "name": f"{name} 매도", "sub": "체결" if done else f"{w * 100:g}%",
                         "price": price, "color": T.MUTED if done else T.DOWN, "first": i == pg["sell_done"]})
        for i, ((r, w), price) in enumerate(zip(fr.BUY_STEPS, lv["buys"])):
            done = i < pg["buy_done"]
            rows.append({"kind": "buy", "name": f"{i + 1}차 매수", "sub": "체결" if done else f"{r * 100:g}% · {w * 100:g}%",
                         "price": price, "color": T.MUTED if done else T.UP, "first": i == pg["buy_done"]})
        rows.append({"kind": "stop", "name": "매수 중단선", "sub": "78.6%", "price": lv["stop"], "color": T.MUTED})
        for o in self.open_orders.get(coin, []):
            same = next((r for r in rows if abs(r["price"] - o["price"]) < 1e-9), None)
            if same:  # 같은 가격이면 선을 따로 긋지 않는다 (반대 방향 주문이면 보조표시로 알림)
                if (same["kind"] == "sell") != (o["side"] == "ask") and "플랜 밖" not in same["sub"]:
                    same["sub"] += " · 플랜 밖 예약 있음"
                continue
            rows.append({"kind": "outside", "name": "플랜 밖 예약 " + ("매도" if o["side"] == "ask" else "매수"),
                         "price": o["price"], "color": T.MUTED})
        for r in rows:
            r["pct"] = (r["price"] / p - 1) * 100
            r["near"] = bool(near) and r["kind"] in ("sell", "buy") and abs(r["pct"]) <= near and r["color"] != T.MUTED
        rows.append({"kind": "now", "name": "현재가", "price": p, "color": T.TEXT})
        return rows

    def render_board(self):
        if not self.shown(TAB_BOARD):
            return
        self.render_coin_list()
        self.render_center(self.sel_coin)
        self.render_side(self.sel_coin)
        self.render_sumbar()

    def grid_price(self, r):
        live = self.live.get(r["coin"])
        return (live[0], live[1]) if live else (r["price"], 0.0)

    def render_coin_list(self):
        fib = []
        for coin in fr.COINS:
            p = self.prices.get(coin)
            live = self.live.get(coin)
            ch = live[1] if live else 0.0
            pg = self.cfg["progress"][coin]
            lv = self.cfg.get("levels", {}).get(coin, {})
            sd, bd = pg["sell_done"], pg["buy_done"]
            s = lv.get("sells", [])[sd] if sd < len(lv.get("sells", [])) else None
            b = lv.get("buys", [])[bd] if bd < len(lv.get("buys", [])) else None
            left = [(f"{sd + 1}차 매도 {(s / p - 1) * 100:+.1f}%", T.DOWN, "kr_xs")] if s and p else []
            right = [(f"{bd + 1}차 매수 {(b / p - 1) * 100:+.1f}%", T.UP, "kr_xs")] if b and p else []
            fib.append({"id": coin, "h": 93, "lines": [
                ([(coin, T.TEXT, "sym_s")], [(T.fmtp(p) if p else "-", T.chg_color(ch), "num")]),
                ([(f"매도 {sd}/3 · 매수 {bd}/3", T.MUTED, "kr_xs")], [(f"{T.arrow(ch)}{abs(ch):.2f}%", T.chg_color(ch), "num_s")]),
                (left, right)]})
        g = self.cfg["grid"]
        state = "꺼짐" if not g["enabled"] else "모의" if g["simulate"] or not self.engine.api else "실전"
        items = []
        for r in self.grid_rows:
            p, ch = self.grid_price(r)
            listed = r.get("listed", True)
            pnl = r["pnl"] + r["qty"] * ((p or 0) - (r["price"] or 0)) * (1 - core.FEE) if r["qty"] else 0
            if not listed:
                l2 = "조회만 · 매매 안 함"
            elif r["buys"]:
                l2 = f"평단 {T.fmtp(r['avg'])} · {r['buys']}회"
            else:
                l2 = r["status"] if r["status"] != "자동매매 중" else "시작 매수 대기"
            items.append({"id": r["coin"], "h": 60, "dim": not listed, "lines": [
                ([(r["coin"], T.TEXT, "sym_s")], [(T.fmtp(p), T.chg_color(ch), "num_s"),
                                                  (f"{T.arrow(ch)}{abs(ch):.2f}%", T.chg_color(ch), "num_xs")]),
                ([(l2, T.MUTED, "kr_xs")], [(f"{pnl:+,.0f}", T.chg_color(pnl), "num_xs")] if r["qty"] else [])]})
        used, cap = self.grid_budget()
        self.coin_list.set([("피보나치", None, fib), (f"자동매매 · {state} · {man(used)}/{man(cap)}", "전체 보기", items)],
                           self.sel_coin)

    def grid_budget(self):
        """자동매매 예산: (지금 코인에 들어간 원가, 적용 중인 전체 한도)."""
        st = self.cfg["grid"]["state"]
        return sum(v.get("cost", 0.0) for v in st.values()), self.engine.grid_total_cap()

    def render_center(self, coin):
        p = self.prices.get(coin)
        live = self.live.get(coin)
        ch, amt = (live[1], live[2]) if live else (0.0, 0.0)
        pg = self.cfg["progress"][coin]
        self.c_sym.config(text=coin)
        self.c_state.config(text=f"매도 {pg['sell_done']}/3 · 매수 {pg['buy_done']}/3 체결")
        self.c_price.config(text=T.fmtp(p) if p else "-", fg=T.chg_color(ch) if live else T.TEXT)
        self.c_chg.config(text=f"{T.arrow(amt)}{T.fmtp(abs(amt))}  {T.arrow(ch)}{abs(ch):.2f}%" if live else "",
                          fg=T.chg_color(ch))
        q = self.hold.get(coin)
        if q is not None and p:
            h1, h2 = f"보유 {T.fmtq_c(coin, q)} {coin}", f"평가 {q * p:,.0f}원"
            self.c_hold1.config(text=h1)
            self.c_hold2.config(text=h2)
            self.c_hold_line.config(text=f"{h1} · {h2}")
        b = self.board.get(coin, {})
        for parts, ind in zip(self.c_ma, b.get("ind", [])):
            label, side, dist, slope, rsi = ind
            parts[0].config(text=f"{label} MA20")
            parts[1].config(text=f"{side} {dist:+.1f}%", fg=T.UP if side == "위" else T.DOWN)
            parts[2].config(text=f"기울기 {slope:+.2f}%", fg=T.TEXT)
            parts[3].config(text=f"RSI {rsi:.0f}", fg=T.TEXT)
        if self.cfg["ui"]["chart_1b"] and b.get("candles"):
            lv = self.cfg.get("levels", {}).get(coin, {})
            sd, bd = pg["sell_done"], pg["buy_done"]
            s1 = lv.get("sells", [])[sd] if sd < len(lv.get("sells", [])) else None
            b1 = lv.get("buys", [])[bd] if bd < len(lv.get("buys", [])) else None
            cs = list(b["candles"])
            if p and cs:  # 마지막 봉은 실시간 가격으로
                o, h, l, _c, *rest = cs[-1]
                cs[-1] = (o, max(h, p), min(l, p), p, *rest)
            self.c_chart.set(cs, [(f"{sd + 1}차 매도", s1, T.DOWN, False), ("현재가", p, T.LINE_NOW, True),
                                  (f"{bd + 1}차 매수", b1, T.UP, False)], "4h · 48봉")
        self.c_ruler.set(self.ruler_rows(coin))

    def render_side(self, coin):
        rows = self.order_rows(coin)
        self.s_title.config(text=f"{coin} 주문")
        wait = sum(1 for r in rows if r["cells"]["st"]["tag"][0] == "대기")
        need = sum(1 for r in rows if r["cells"]["st"]["tag"][0] == "승인 필요")
        out = sum(1 for r in rows if r["cells"]["st"]["tag"][0] == "플랜 밖")
        self.s_count.config(text=f"대기 {wait} · 승인 필요 {need}" + (f" · 플랜 밖 {out}" if out else ""))
        self.s_table.set_rows(rows)
        n = len(self.proposal["todo"]) if self.proposal else 0
        if n:
            self.s_approve_lab.config(text=f"승인 대기 {n}건 (전체 코인)")
            if not self.s_approve.winfo_ismapped():
                self.s_approve.pack(fill="x", padx=16, pady=(0, 14), before=self.s_div)
        else:
            self.s_approve.pack_forget()
        self.render_side_alerts()

    def render_side_alerts(self):
        recent = self.alert_data[:4]
        if recent == self.s_alerts_shown:
            return
        self.s_alerts_shown = recent
        for w in self.s_alerts.winfo_children():
            w.destroy()
        if not recent:
            lab(self.s_alerts, "알림이 없습니다", "kr_s", fg=T.MUTED).pack(anchor="w", padx=16, pady=8)
        for rid, ts, kind, title, msg in recent:
            box = tk.Frame(self.s_alerts, bg=T.PANEL)
            box.pack(fill="x", padx=16, pady=(8, 0))
            top = tk.Frame(box, bg=T.PANEL)
            top.pack(fill="x")
            lab(top, T.fit(title, "kr_b", 330), "kr_b").pack(side="left")
            lab(top, ts[11:19], "num_xs", fg=T.MUTED).pack(side="right")
            lab(box, T.fit(msg.replace("\n", " / "), "kr_xs", 420), "kr_xs", fg=T.MUTED, anchor="w").pack(fill="x", pady=(3, 8))
            tk.Frame(self.s_alerts, bg=T.DIVIDER_SOFT, height=1).pack(fill="x")

    def render_sumbar(self):
        total = sum(self.hold.get(c, 0) * self.prices[c] for c in fr.COINS if self.prices.get(c) and c in self.hold)
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
        self.sumbar.set("lvl", at[5:16].replace("T", " ") if len(at) > 5 else at or "-")
        used, cap = self.grid_budget()
        self.sumbar.set("grid", f"{man(used)} / {man(cap)}", "", color=T.UP if cap and used / cap > 0.8 else T.TEXT,
                        label=f"자동매매 예산 · {used / cap * 100:.0f}% 사용" if cap else "자동매매 예산")

    def render_strip(self, data):
        self.live.update(data)
        for coin in fr.COINS:
            if coin in data:
                self.prices[coin] = data[coin][0]
        if self.icon and data:
            self.icon.title = "\n".join(f"{c} {v[0]:,.0f} ({v[1]:+.2f}%)" for c, v in data.items() if c in fr.COINS)
        if self.hidden() or self.nb.index() == TAB_BOARD:  # 현황은 왼쪽 목록이 티커 대신
            return
        grid = [c for c in self.engine.grid_tracked() if c not in fr.COINS]
        held = [a["currency"] for a in self.accounts if a["currency"] in self.live and a["qty"] > 0
                and a["currency"] not in fr.COINS and a["currency"] not in grid]
        pick = lambda cs: [(c, self.live[c][0], self.live[c][1]) for c in cs if c in self.live]  # noqa: E731
        groups = [("피보나치", pick(fr.COINS)), ("자동매매", pick(grid))]
        if self.nb.index() == TAB_INVEST:  # 투자내역에서는 보유 코인도
            groups.append(("보유", pick(held)))
        self.ticker.set(groups)

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
            self.drift_box.pack(fill="x", padx=18, pady=(12, 0), before=self.board_body)

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
        self.center(w)

    def fib_sim_note(self):
        return ("\n\n※ 설정 탭의 '모의 모드'가 켜져 있어 새 주문은 실제로 나가지 않고 기록만 됩니다."
                if self.cfg["simulate"] or not self.engine.api else "")

    def apply_drift(self):
        if messagebox.askyesno("현행 기준으로 바꾸기",
                               "지금 캔들로 레벨을 다시 계산하고,\nBTC·ETH·XRP 예약 주문 중 새 플랜과 다른 것은 취소한 뒤 새 가격으로 다시 겁니다."
                               + self.fib_sim_note() + "\n\n진행할까요?", icon="warning"):
            self.drift_box.pack_forget()
            self.engine.request("apply_plan", True, None, "현행 기준으로 바꾸기")
            self.nb.select(TAB_ORDERS)  # 주문 탭에서 결과 확인

    def toggle_auto_drift(self):
        on = self.auto_drift.get()
        if on and not messagebox.askyesno("자동 반영", "앞으로 레벨이 유의적으로 바뀌면 확인 없이 자동으로 주문을 새 가격으로 바꿉니다.\n켤까요?"
                                          + self.fib_sim_note(), icon="warning"):
            self.auto_drift.set(False)
            return
        self.cfg["auto_apply_drift"] = on
        core.save_config(self.cfg)

    def cancel_selected(self):
        coin = self.sel_coin
        sel = list(self.s_table.checked)
        if not sel:
            messagebox.showinfo("취소", "오른쪽 표에서 취소할 주문의 체크박스(☐)를 누르세요.\n(대기·플랜 밖 주문만 고를 수 있습니다)")
            return
        if messagebox.askyesno("선택 취소", f"{coin} 예약 주문 {len(sel)}건을 업비트에서 실제로 취소할까요?"):
            self.engine.request("cancel_orders", [coin], sel)
            self.s_table.checked.clear()
            self.s_table.draw()

    def cancel_coin(self, coin):
        name = coin or "BTC·ETH·XRP"
        if messagebox.askyesno("전체 취소", f"{name} 예약(미체결) 주문을 업비트에서 전부 실제로 취소할까요?", icon="warning"):
            self.engine.request("cancel_orders", [coin] if coin else None, None)

    def replan_coin(self, coin):
        if messagebox.askyesno("플랜대로 다시 걸기", f"{coin} 예약 주문을 지금 플랜과 비교해서, 다른 것은 취소하고 플랜대로 다시 겁니다."
                               + self.fib_sim_note() + "\n\n진행할까요?"):
            self.engine.request("apply_plan", False, [coin], f"{coin} 플랜대로 다시 걸기")

    # ---------------- ② 투자내역 (2a) ----------------
    INV_COLS = (("arrow", "", 28, "center"), ("coin", "코인", 80, "w"), ("qty", "보유수량", 130, "e"),
                ("avg", "매수평균가", 120, "e"), ("buy", "매수금액", 120, "e"), ("price", "현재가", 120, "e"),
                ("value", "평가금액", 120, "e"), ("pnl", "평가손익", 120, "e"), ("rate", "수익률", 90, "e"),
                ("weight", "비중", 130, "e"))

    def build_invest(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "투자내역")
        self.inv_sum = W.StatCells(f, [("krw", "보유 KRW"), ("buy", "총매수"), ("val", "총평가"), ("pnl", "평가손익"),
                                       ("total", "총 보유자산")])
        self.inv_sum.pack(fill="x")
        outer, body = W.scroll_page(f)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(body, bg=T.GROUND)
        inner.pack(fill="x", padx=18, pady=18)

        hp, hh = card(inner, "보유 코인")
        lab(hh, "업비트 매수평균가 기준 · 현재가 2초마다 갱신 · 스테이킹·원화마켓 없는 코인 제외 · 행을 누르면 차트",
            "kr_xs", fg=T.MUTED).pack(side="right")
        self.inv_table = tk.Frame(hp, bg=T.PANEL)
        self.inv_table.pack(fill="x", padx=16, pady=(0, 14))
        head = tk.Frame(self.inv_table, bg=T.PANEL)
        head.pack(fill="x")
        self.inv_grid_cfg(head)
        for i, (key, text, w, anchor) in enumerate(self.INV_COLS):
            lab(head, text, "kr_xs", fg=T.MUTED, anchor=anchor).grid(row=0, column=i, sticky="ew", padx=4, pady=6)
        tk.Frame(self.inv_table, bg=T.DIVIDER, height=1).pack(fill="x")
        self.inv_rows = {}

        tp, th = card(inner, "거래내역", "업비트 최근 체결 100건 · 5분마다 갱신", pady=(18, 0))
        T.Btn(th, "새로고침", self.feed_history_now).pack(side="right")
        self.hist_filter, self.hist_orders = "전체", []
        W.Segmented(th, ["전체", "매수", "매도"], "전체", self.set_hist_filter).pack(side="right", padx=10)
        cols = [{"key": "ts", "title": "체결시간", "w": 170}, {"key": "coin", "title": "코인", "w": 80},
                {"key": "side", "title": "종류", "w": 70}, {"key": "qty", "title": "거래수량", "w": 150, "anchor": "e", "grow": 1},
                {"key": "px", "title": "거래단가", "w": 150, "anchor": "e"}, {"key": "krw", "title": "거래금액", "w": 150, "anchor": "e"},
                {"key": "fee", "title": "수수료", "w": 100, "anchor": "e"}, {"key": "type", "title": "주문", "w": 90, "anchor": "e"}]
        self.hist_table = W.Table(tp, cols, rh=38, fit=True, min_rows=2, empty=["불러오는 중…"])
        self.hist_table.pack(fill="x", pady=(0, 8))

    def inv_grid_cfg(self, frame):
        for i, (_, _, w, _) in enumerate(self.INV_COLS):
            frame.columnconfigure(i, minsize=w, weight=1 if i in (1,) else 0)

    def set_hist_filter(self, name):
        self.hist_filter = name
        self.render_history(self.hist_orders)

    def feed_history_now(self):
        if hasattr(self, "feed"):
            self.feed.want_history.set()

    def inv_row(self, cur):
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
                w = lab(inner, "", font, fg=T.MUTED if key == "qty" else T.TEXT, anchor=anchor)
                w.grid(row=0, column=i, sticky="ew", padx=4, pady=11)
                cells[key] = w
                widgets = [w]
            for wdg in widgets:
                wdg.bind("<Button-1>", lambda e, c=cur: self.toggle_inv_chart(c))
        for wdg in (row, inner):
            wdg.bind("<Button-1>", lambda e, c=cur: self.toggle_inv_chart(c))
        tk.Frame(wrap, bg=T.DIVIDER_SOFT, height=1).pack(fill="x")
        chart = W.Candles(wrap, height=260)
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
        if not self.shown(TAB_INVEST):
            return
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
        order = sorted(items, key=lambda x: -x[1]["qty"] * x[2])  # 비중 큰 순서
        for cur, a, price in order:
            r = self.inv_row(cur)
            cells = r["cells"]
            buy, val = a["qty"] * a["avg"], a["qty"] * price
            pnl = val - buy
            rate = pnl / buy * 100 if buy else 0
            col = T.chg_color(pnl)
            cells["arrow"].config(text="▴" if r["chart"].winfo_ismapped() else "▾", fg=T.MUTED)
            cells["coin"].config(text=cur)
            cells["qty"].config(text=T.fmtq_c(cur, a["qty"]))
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
        if [c for c, _, _ in order] != getattr(self, "inv_order", None):  # 순서가 바뀌면 줄을 다시 붙인다
            self.inv_order = [c for c, _, _ in order]
            for cur in self.inv_order:
                self.inv_rows[cur]["wrap"].pack_forget()
            for cur in self.inv_order:
                self.inv_rows[cur]["wrap"].pack(fill="x")
        pnl = val_tot - buy_tot
        rate = pnl / buy_tot * 100 if buy_tot else 0
        self.inv_sum.set("krw", T.fmtk(krw), "원")
        self.inv_sum.set("buy", T.fmtk(buy_tot), "원")
        self.inv_sum.set("val", T.fmtk(val_tot), "원")
        self.inv_sum.set("pnl", T.fmtk(pnl, sign=True), "원", color=T.chg_color(pnl), extra=f"{rate:+.2f}%")
        self.inv_sum.set("total", T.fmtk(krw + val_tot), "원")

    def render_history(self, orders):
        self.hist_orders = orders
        rows = []
        for i, o in enumerate(orders):
            vol = float(o.get("executed_volume") or 0)
            if vol <= 0:
                continue
            if (self.hist_filter == "매수" and o["side"] != "bid") or (self.hist_filter == "매도" and o["side"] != "ask"):
                continue
            funds = float(o.get("executed_funds") or 0) or vol * float(o.get("price") or 0)
            px = funds / vol if funds else float(o.get("price") or 0)
            coin = o["market"].split("-")[-1]
            bid = o["side"] == "bid"
            rows.append({"id": i, "cells": {
                "ts": {"text": (o.get("created_at") or "")[:19].replace("T", " "), "font": "num_s", "fg": T.MUTED},
                "coin": {"text": coin, "font": "num_b"},
                "side": {"text": "매수" if bid else "매도", "fg": T.UP if bid else T.DOWN},
                "qty": {"text": T.fmtq_c(coin, vol), "fg": T.MUTED},
                "px": T.fmtp(px), "krw": T.fmtk(funds),
                "fee": {"text": f"{float(o.get('paid_fee') or 0):,.1f}", "fg": T.MUTED},
                "type": {"text": {"limit": "지정가", "price": "시장가", "market": "시장가"}.get(o.get("ord_type"),
                                                                                           o.get("ord_type", "")), "font": "kr_s"}}})
        self.hist_table.empty = ["해당하는 체결이 없습니다"]
        self.hist_table.set_rows(rows)

    # ---------------- 투자일지 (자동매매 거래별·일별·월별 손익) ----------------
    def build_journal(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "투자일지")
        g = T.GROUND
        top = tk.Frame(f, bg=g)
        top.pack(fill="x", padx=18, pady=(16, 10))
        lab(top, "투자일지", "kr_big", bg=g).pack(side="left")
        lab(top, "자동매매 거래 기준 · 손익은 수수료를 뺀 실현 손익 (판 만큼의 원가를 빼서 계산)", "kr_xs", fg=T.MUTED,
            bg=g).pack(side="left", padx=12, pady=(6, 0))
        T.Btn(top, "CSV 저장 (엑셀)", self.export_journal, bg=g).pack(side="right")
        self.j_filter = "모의" if self.cfg["grid"]["simulate"] or not self.engine.api else "실전"
        W.Segmented(top, ["실전", "모의", "전체"], self.j_filter, self.set_journal_filter).pack(side="right", padx=10)
        self.j_stats = W.StatCells(f, [("today", "오늘 손익"), ("month", "이번 달 손익"), ("total", "누적 실현 손익"),
                                       ("fee", "이번 달 수수료"), ("trades", "이번 달 거래")])
        self.j_stats.pack(fill="x", padx=18)
        outer, body = W.scroll_page(f)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(body, bg=T.GROUND)
        inner.pack(fill="x", padx=18, pady=(14, 18))
        num_col = lambda k, t, w=110: {"key": k, "title": t, "w": w, "anchor": "e"}  # noqa: E731
        mc, _ = card(inner, "월별", "수익률 = 실현 손익 ÷ 판 코인의 원가")
        self.j_month = W.Table(mc, [{"key": "key", "title": "월", "w": 90}, num_col("buys", "매수", 60),
                                    num_col("buy_krw", "매수 금액"), num_col("sells", "매도", 60), num_col("sell_krw", "매도 금액"),
                                    num_col("pnl", "실현 손익"), num_col("rate", "수익률", 80), num_col("fee", "수수료", 90),
                                    {"key": "cyc", "title": "익절 완료", "w": 80, "anchor": "e", "grow": 1}],
                               rh=36, fit=True, min_rows=1, empty=["아직 자동매매 거래가 없습니다"])
        self.j_month.pack(fill="x", pady=(0, 8))
        cc, _ = card(inner, "코인별", "선택한 구분(실전/모의) 전체 기간", pady=(18, 0))
        self.j_coin = W.Table(cc, [{"key": "key", "title": "코인", "w": 90}, num_col("buys", "매수", 60),
                                   num_col("buy_krw", "매수 금액"), num_col("sells", "매도", 60), num_col("sell_krw", "매도 금액"),
                                   num_col("pnl", "실현 손익"), num_col("rate", "수익률", 80), num_col("fee", "수수료", 90),
                                   {"key": "cyc", "title": "익절 완료", "w": 80, "anchor": "e", "grow": 1}],
                              rh=36, fit=True, min_rows=1, empty=["아직 자동매매 거래가 없습니다"])
        self.j_coin.pack(fill="x", pady=(0, 8))
        dc, _ = card(inner, "일별", "최근 90일 · 행을 누르면 아래에 그날 거래", pady=(18, 0))
        self.j_day = W.Table(dc, [{"key": "key", "title": "날짜", "w": 110}, num_col("buys", "매수", 60),
                                  num_col("buy_krw", "매수 금액"), num_col("sells", "매도", 60), num_col("sell_krw", "매도 금액"),
                                  num_col("pnl", "실현 손익"), num_col("fee", "수수료", 90),
                                  {"key": "cum", "title": "누적 손익", "w": 110, "anchor": "e", "grow": 1}],
                             rh=36, fit=True, min_rows=1, selectable=True, on_click=self.select_journal_day,
                             empty=["아직 자동매매 거래가 없습니다"])
        self.j_day.pack(fill="x", pady=(0, 8))
        tc, th = card(inner, "거래 상세", pady=(18, 0))
        self.j_detail_title = lab(th, "", "kr_xs", fg=T.MUTED)
        self.j_detail_title.pack(side="left", padx=10, pady=(3, 0))
        self.j_detail = W.Table(tc, [{"key": "ts", "title": "시간", "w": 80}, {"key": "sim", "title": "모의", "w": 50},
                                     {"key": "coin", "title": "코인", "w": 70}, {"key": "kind", "title": "구분", "w": 100},
                                     num_col("price", "가격"), num_col("qty", "수량", 130), num_col("krw", "금액", 100),
                                     num_col("fee", "수수료", 80), num_col("pnl", "이 거래 손익", 150),
                                     {"key": "after", "title": "거래 후 평단 · 보유 원가", "w": 170, "anchor": "e", "grow": 1}],
                                rh=40, fit=True, min_rows=1, empty=["이 날 거래가 없습니다"])
        self.j_detail.pack(fill="x", pady=(0, 8))
        self.j_day_sel, self.j_trades = None, []

    def set_journal_filter(self, name):
        self.j_filter = name
        self.render_journal()

    def select_journal_day(self, day):
        self.j_day_sel = day
        self.render_journal_detail()

    def journal_trades(self):
        return core.build_journal(self.db, {"실전": False, "모의": True}.get(self.j_filter))

    def render_journal(self):
        if not self.shown(TAB_JOURNAL):
            return
        tr = self.j_trades = self.journal_trades()
        today, month = time.strftime("%Y-%m-%d"), time.strftime("%Y-%m")
        days = core.journal_summary(tr, "date")
        months = core.journal_summary(tr, "month")
        coins = core.journal_summary(tr, "coin")
        total = sum(t["pnl"] or 0 for t in tr)
        d, m = days.get(today), months.get(month)
        zero = {"buys": 0, "buy_krw": 0, "sells": 0, "sell_krw": 0, "pnl": 0, "base": 0, "fee": 0, "cycles": 0}
        d, m = d or zero, m or zero
        rate = (lambda a: f"{a['pnl'] / a['base'] * 100:+.2f}%" if a["base"] else "-")  # noqa: E731
        self.j_stats.set("today", T.fmtk(d["pnl"], sign=True), "원", color=T.chg_color(d["pnl"]),
                         sub=f"매수 {d['buys']}건 · 매도 {d['sells']}건 · 익절 {d['cycles']}번")
        self.j_stats.set("month", T.fmtk(m["pnl"], sign=True), "원", color=T.chg_color(m["pnl"]),
                         sub=f"수익률 {rate(m)} · 익절 {m['cycles']}번")
        self.j_stats.set("total", T.fmtk(total, sign=True), "원", color=T.chg_color(total),
                         sub=f"전체 수수료 {sum(t['fee'] for t in tr):,.0f}원 · 거래 {len(tr)}건")
        self.j_stats.set("fee", T.fmtk(m["fee"]), "원", sub=f"오늘 {d['fee']:,.0f}원")
        self.j_stats.set("trades", f"{m['buys'] + m['sells']}", "건",
                         sub=f"매수 {m['buy_krw']:,.0f}원 · 매도 {m['sell_krw']:,.0f}원")

        def agg_row(a, cyc=True):
            return {"id": a["key"], "cells": {
                "key": {"text": a["key"], "font": "num_b" if len(a["key"]) < 8 else "num"},
                "buys": str(a["buys"]), "buy_krw": T.fmtk(a["buy_krw"]), "sells": str(a["sells"]),
                "sell_krw": T.fmtk(a["sell_krw"]), "pnl": {"text": T.fmtk(a["pnl"], sign=True), "fg": T.chg_color(a["pnl"]), "font": "num_b"},
                "rate": {"text": rate(a), "fg": T.chg_color(a["pnl"])}, "fee": {"text": f"{a['fee']:,.0f}", "fg": T.MUTED},
                "cyc": f"{a['cycles']}번" if cyc else ""}}
        self.j_month.set_rows([agg_row(a) for a in sorted(months.values(), key=lambda a: a["key"], reverse=True)])
        self.j_coin.set_rows([agg_row(a) for a in sorted(coins.values(), key=lambda a: -a["pnl"])])
        cum, rows = 0.0, []
        for a in sorted(days.values(), key=lambda a: a["key"]):
            cum += a["pnl"]
            r = agg_row(a)
            r["cells"]["cum"] = {"text": T.fmtk(cum, sign=True), "fg": T.chg_color(cum)}
            rows.append(r)
        rows = rows[::-1][:90]
        self.j_day.set_rows(rows)
        if self.j_day_sel not in days:
            self.j_day_sel = rows[0]["id"] if rows else None
        self.j_day.selected = self.j_day_sel
        self.j_day.draw()
        self.render_journal_detail()

    def render_journal_detail(self):
        day = self.j_day_sel
        tr = [t for t in self.j_trades if t["date"] == day]
        self.j_detail_title.config(text=f"{day} · {len(tr)}건 (최근 거래가 위)" if day else "")
        rows = []
        for t in reversed(tr):
            bid = t["side"] == "bid"
            after = (f"평단 {T.fmtp(t['avg'])} · {t['hold_cost']:,.0f}원" if bid
                     else f"남은 원가 {t['hold_cost']:,.0f}원" if t.get("hold_cost") else "사이클 끝 (보유 0)")
            rows.append({"id": t["id"], "cells": {
                "ts": {"text": t["ts"][11:19], "font": "num_s", "fg": T.MUTED}, "sim": {"text": "예" if t["sim"] else "", "fg": T.MUTED},
                "coin": {"text": t["coin"], "font": "num_b"},
                "kind": {"text": t["kind"], "fg": T.UP if bid else T.DOWN},
                "price": T.fmtp(t["price"]), "qty": {"text": T.fmtq(t["qty"]), "fg": T.MUTED, "font": "num_s"},
                "krw": T.fmtk(t["krw"]), "fee": {"text": f"{t['fee']:,.1f}", "fg": T.MUTED},
                "pnl": {"text": "-" if t["pnl"] is None else T.fmtk(t["pnl"], sign=True),
                        "fg": T.MUTED if t["pnl"] is None else T.chg_color(t["pnl"]), "font": "num_b",
                        "sub": f"원가 {t['base']:,.0f} 대비 {t['pnl'] / t['base'] * 100:+.1f}%" if t["base"] else None},
                "after": {"text": after, "fg": T.MUTED, "font": "kr_s"}}})
        self.j_detail.set_rows(rows)

    def export_journal(self):
        import csv
        tr = self.journal_trades()
        if not tr:
            messagebox.showinfo("투자일지", "저장할 거래가 없습니다.")
            return
        path = os.path.join(HERE, f"투자일지_{self.j_filter}_{time.strftime('%Y%m%d_%H%M')}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as fp:  # utf-8-sig: 엑셀에서 한글이 안 깨지게
            w = csv.writer(fp)
            w.writerow(["시간", "모의", "코인", "구분", "가격", "수량", "금액(원)", "수수료(원)", "실현 손익(원)", "판 원가(원)",
                        "거래 후 보유 원가(원)"])
            for t in tr:
                w.writerow([t["ts"], "예" if t["sim"] else "", t["coin"], t["kind"], t["price"], f"{t['qty']:.8f}",
                            round(t["krw"]), round(t["fee"], 2), "" if t["pnl"] is None else round(t["pnl"], 1),
                            "" if t["base"] is None else round(t["base"]), round(t.get("hold_cost") or 0)])
        self.show_notice(f"저장했습니다: {path}", 10)
        if WIN:
            os.startfile(path)  # 엑셀(또는 기본 프로그램)로 바로 연다

    # ---------------- ③ 자동매매 (12-4) ----------------
    GRID_FIELDS = (("coins", "코인", "", 3), ("unit_krw", "1회", "원", 1), ("multiplier", "배수", "배", 1), ("drop_pct", "하락", "%", 1),
                   ("profit_krw", "익절", "원", 1), ("max_krw", "코인한도", "원", 1), ("total_max_krw", "전체한도", "원", 1))

    def build_grid(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "자동매매")
        g = self.cfg["grid"]
        self.g_stats = W.StatCells(f, [("state", "상태"), ("cost", "투입 원가"), ("pnl", "평가손익 (수수료 뺀 금액)"),
                                       ("real", "누적 실현 (수수료 뺀 금액)"),
                                       ("cap", "전체 한도 사용")])
        self.g_stats.pack(fill="x")
        outer, body = W.scroll_page(f)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(body, bg=T.GROUND)
        inner.pack(fill="x", padx=18, pady=18)

        # 규칙 · 설정 (기본 접힘, 접혀도 핵심 값 한 줄)
        rc, rh = card(inner, "규칙 · 설정")
        self.g_rule_sum = lab(rh, "", "kr_xs", fg=T.MUTED)
        self.g_rule_sum.pack(side="left", padx=12, pady=(3, 0))
        self.g_rule_btn = T.Btn(rh, "펼치기 ▾", self.toggle_rules, "ghost")
        self.g_rule_btn.pack(side="right")
        self.g_rule_body = tk.Frame(rc, bg=T.PANEL)
        self.g_chips = tk.Frame(self.g_rule_body, bg=T.PANEL)
        self.g_chips.pack(fill="x", padx=16, pady=(4, 14))
        fields = tk.Frame(self.g_rule_body, bg=T.PANEL)
        fields.pack(fill="x", padx=16)
        self.g_fields = {}
        vals = {"coins": ",".join(g["coins"]), "unit_krw": f"{g['unit_krw']:,}", "multiplier": f"{g.get('multiplier', 1.0):g}",
                "drop_pct": f"{g['drop_pct']:g}",
                "profit_krw": f"{g['profit_krw']:,}", "max_krw": f"{g['max_krw']:,}", "total_max_krw": f"{g['total_max_krw']:,}"}
        for i, (key, label, unit, weight) in enumerate(self.GRID_FIELDS):
            fields.columnconfigure(i, weight=weight, uniform="gf" if weight == 1 else None)
            cell = tk.Frame(fields, bg=T.PANEL)
            cell.grid(row=0, column=i, sticky="ew", padx=(0, 12))
            lab(cell, label, "kr_xs", fg=T.MUTED).pack(anchor="w", pady=(0, 4))
            row = tk.Frame(cell, bg=T.PANEL)
            row.pack(fill="x")
            e = ttk.Entry(row, style="Card.TEntry", justify="left" if key == "coins" else "right", font=T.F["num"])
            e.insert(0, vals[key])
            e.pack(side="left", fill="x", expand=True)
            if unit:
                lab(row, unit, "kr_s", fg=T.MUTED).pack(side="left", padx=(6, 0))
            self.g_fields[key] = e
        chk = tk.Frame(self.g_rule_body, bg=T.PANEL)
        chk.pack(fill="x", padx=16, pady=(12, 14))
        self.g_on = tk.BooleanVar(value=g["enabled"])
        self.g_sim = tk.BooleanVar(value=g["simulate"])
        self.g_half = tk.BooleanVar(value=g["half_at_breakeven"])
        self.g_reinvest = tk.BooleanVar(value=g.get("reinvest", True))
        for text, var in (("켜기", self.g_on), ("모의", self.g_sim), ("본전 절반 매도", self.g_half),
                          ("수익 재투자 (실현 수익만큼 전체 한도 늘림)", self.g_reinvest)):
            ttk.Checkbutton(chk, text=text, variable=var, style="Panel.TCheckbutton").pack(side="left", padx=(0, 16))
        lab(chk, "BTC·ETH·XRP는 제외. 코인은 쉼표나 띄어쓰기로 나눠 적습니다. 코인 칸에 적고 [저장]한 코인만 사고팝니다.",
            "kr_xs", fg=T.MUTED).pack(side="left")
        T.Btn(chk, "저장", self.save_grid, "primary").pack(side="right")
        # 하락 코인 자동 추가 (추천 목록 안에서만)
        dp = g["dip"]
        dbox = tk.Frame(self.g_rule_body, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        dbox.pack(fill="x", padx=16, pady=(0, 14))
        dh = tk.Frame(dbox, bg=T.PANEL)
        dh.pack(fill="x", padx=12, pady=(10, 6))
        self.g_dip = tk.BooleanVar(value=dp["enabled"])
        ttk.Checkbutton(dh, text="자동매매 감시", variable=self.g_dip, style="Panel.TCheckbutton").pack(side="left")
        lab(dh, "추천 목록 중 전일 대비 아래 % 이상 떨어진 코인은 자동매매를 시작합니다(1회 금액으로 시작 매수). "
                "익절로 사이클이 끝나면 다시 감시로 돌아갑니다. 투자유의·경고 코인은 제외.", "kr_xs", fg=T.MUTED).pack(side="left", padx=10)
        dr = tk.Frame(dbox, bg=T.PANEL)
        dr.pack(fill="x", padx=12, pady=(0, 6))
        self.g_dipf = {}
        for key, label, unit, w in (("min_pct", "하락", "% 이상", 5), ("max_pct", "~", "% 이하", 5),
                                    ("min_vol_eok", "거래대금", "억 이상", 6), ("per_day", "하루 최대", "개", 4),
                                    ("max_coins", "목록 최대", "개", 4)):
            lab(dr, label, "kr_xs", fg=T.MUTED).pack(side="left", padx=(0 if key == "min_pct" else 10, 4))
            e = ttk.Entry(dr, style="Card.TEntry", justify="right", width=w, font=T.F["num"])
            e.insert(0, f"{dp[key]:g}")
            e.pack(side="left")
            lab(dr, unit, "kr_xs", fg=T.MUTED).pack(side="left", padx=(4, 0))
            self.g_dipf[key] = e
        pr = tk.Frame(dbox, bg=T.PANEL)
        pr.pack(fill="x", padx=12, pady=(0, 10))
        lab(pr, "후보(추천 목록)", "kr_xs", fg=T.MUTED).pack(side="left", padx=(0, 6))
        e = ttk.Entry(pr, style="Card.TEntry", font=T.F["num"])
        e.insert(0, " ".join(dp["pool"]))
        e.pack(side="left", fill="x", expand=True)
        self.g_dipf["pool"] = e
        if self.cfg["ui"]["grid_rules_open"]:
            self.g_rule_body.pack(fill="x")
            self.g_rule_btn.config(text="접기 ▴")
        self.render_rules()

        # 대상 코인 (조회)
        tc, th = card(inner, "대상 코인", "30초마다 갱신 · 코인 칸에 적은 코인 + 자동매매로 산 수량이 남은 코인", pady=(18, 0))
        self.g_liq_btn = T.Btn(th, "선택 코인 청산", self.grid_liquidate, "danger")
        self.g_liq_btn.pack(side="right")
        T.Btn(th, "구분 변경", self.grid_toggle_listed).pack(side="right", padx=(0, 16))
        T.Btn(th, "조회", lambda: self.engine.request("grid_refresh")).pack(side="right", padx=8)
        self.g_watch_btn = T.Btn(th, "", self.toggle_watch)
        self.g_watch_btn.pack(side="right")
        cols = [{"key": "chk", "w": 26}, {"key": "st", "title": "상태", "w": 104},
                {"key": "coin", "title": "코인", "w": 58}, {"key": "price", "title": "현재가", "w": 90, "anchor": "e"},
                {"key": "avg", "title": "평단 · 매수", "w": 100, "anchor": "e"},
                {"key": "pnl", "title": "손익(수수료 뺌)", "w": 96, "anchor": "e"},
                {"key": "pos", "title": "다음 매수 ← 현재 → 익절", "w": 200, "anchor": "center"},
                {"key": "next", "title": "다음 매수가 · 금액", "w": 120, "anchor": "e"},
                {"key": "tp", "title": "익절가", "w": 90, "anchor": "e"},
                {"key": "cyc", "title": "사이클", "w": 60, "anchor": "e"},
                {"key": "tot", "title": "누적 수익", "w": 80, "anchor": "e"},
                {"key": "own", "title": "기존 보유(별도)", "w": 120, "anchor": "e", "grow": 1}]
        self.g_table = W.Table(tc, cols, rh=44, check=True, fit=True, min_rows=2, on_check=self.update_liq_btn,
                               empty=["자동매매 대상 코인이 없습니다", "규칙 · 설정의 코인 칸에 적고 [저장]하세요"])
        self.g_table.pack(fill="x")
        self.g_note = lab(tc, "", "kr_xs", fg=T.MUTED, anchor="w")
        self.g_note.pack(fill="x", padx=16, pady=(8, 4))
        self.g_watch = tk.Frame(tc, bg=T.PANEL)
        self.g_watch.pack(fill="x", padx=16, pady=(0, 12))
        self.dip_watch, self.dip_at = [], ""
        self.render_watch()

        # 거래 기록
        lc, _ = card(inner, "거래 기록", "최근 100건", pady=(18, 0))
        cols = [{"key": "ts", "title": "시간", "w": 170}, {"key": "sim", "title": "모의", "w": 60},
                {"key": "coin", "title": "코인", "w": 80}, {"key": "side", "title": "구분", "w": 70},
                {"key": "price", "title": "가격", "w": 150, "anchor": "e"},
                {"key": "qty", "title": "수량", "w": 160, "anchor": "e", "grow": 1},
                {"key": "krw", "title": "금액", "w": 140, "anchor": "e"}]
        self.grid_log = W.Table(lc, cols, rh=36, fit=True, min_rows=2, empty=["거래 기록이 없습니다"])
        self.grid_log.pack(fill="x", pady=(0, 8))

    def render_rules(self):
        g = self.cfg["grid"]
        dp = g["dip"]
        dip = (f" · 감시 중(−{dp['min_pct']:g}% 이상 하락 시 시작, 하루 {dp['per_day']}개)" if dp["enabled"]
               else " · 감시 꺼짐")
        mult = g.get("multiplier", 1.0)
        self.g_rule_sum.config(text=f"1회 {g['unit_krw']:,}원 · " + (f"추가 매수 {mult:g}배씩 · " if mult > 1 else "") +
                                    f"하락 {g['drop_pct']:g}%마다 추가 · 익절 {g['profit_krw']:,}원 · "
                                    f"코인한도 {g['max_krw']:,}원 · 전체한도 {g['total_max_krw']:,}원 · "
                                    f"본전 절반 {'켬' if g['half_at_breakeven'] else '끔'}" + dip)
        for w in self.g_chips.winfo_children():
            w.destroy()
        mult = g.get("multiplier", 1.0)
        amounts = " → ".join(f"{g['unit_krw'] * mult ** i:,.0f}" for i in range(5)) + " …" if mult > 1 else ""
        steps = ["시작 매수", (f"{g['drop_pct']:g}% 하락마다 직전 매수의 {mult:g}배 추가 매수 ({amounts})" if mult > 1
                           else f"마지막 매수가 대비 {g['drop_pct']:g}% 하락마다 1회 금액 추가 매수"),
                 "2회 이상 샀으면 본전에 절반 매도" if g["half_at_breakeven"] else "본전 절반 매도 안 함",
                 f"사이클 수익이 익절 {g['profit_krw']:,}원 이상이면 전량 매도", "다시 시작"]
        for i, text in enumerate(steps, start=1):
            if i > 1:
                lab(self.g_chips, "→", "kr", fg=T.MUTED).pack(side="left", padx=8)
            chip = tk.Frame(self.g_chips, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
            chip.pack(side="left")
            lab(chip, str(i), "num_b", fg=T.DOWN).pack(side="left", padx=(10, 6), pady=6)
            lab(chip, text, "kr_s").pack(side="left", padx=(0, 10))

    def toggle_rules(self):
        on = not self.cfg["ui"]["grid_rules_open"]
        self.cfg["ui"]["grid_rules_open"] = on
        core.save_config(self.cfg)
        if on:
            self.g_rule_body.pack(fill="x")
        else:
            self.g_rule_body.pack_forget()
        self.g_rule_btn.config(text="접기 ▴" if on else "펼치기 ▾")

    @staticmethod
    def pos_bar(nb, tp, p):
        """위치 막대: 왼쪽 끝 = 다음 매수가(UP), 오른쪽 끝 = 익절가(DOWN), 현재가에 2×14 표시."""
        def draw(c, x0, x1, cy):
            if not (nb and tp and p) or tp <= nb:
                c.create_text((x0 + x1) / 2, cy, text="-", fill=T.MUTED, font=T.F["num_s"])
                return
            n = 24
            seg = (x1 - x0) / n
            for i in range(n):
                col = T.blend(T.blend(T.DOWN, T.UP, i / (n - 1)), T.PANEL, 0.55)
                c.create_rectangle(x0 + i * seg, cy - 2, x0 + (i + 1) * seg + 0.5, cy + 2, fill=col, outline="")
            frac = max(0.0, min(1.0, (p - nb) / (tp - nb)))
            x = x0 + frac * (x1 - x0)
            c.create_rectangle(x - 1, cy - 7, x + 1, cy + 7, fill=T.TEXT, outline="")
        return draw

    def render_grid(self, rows):
        self.grid_rows = rows
        self.render_grid_tab()
        self.render_board()

    STATUS_TAG = {"자동매매 중": T.DOWN, "결과 확인 중": T.ACCENT, "투자유의 중지": T.UP, "시세 대기": T.MUTED}

    def render_grid_tab(self):
        if not self.shown(TAB_GRID):
            return
        g = self.cfg["grid"]
        sim = g["simulate"] or not self.engine.api
        rows, cost, pnl_t, tot, cycles, holding, gross_t, fees = [], 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0
        for r in self.grid_rows:
            p, _ = self.grid_price(r)
            listed = r.get("listed", True)
            pnl = r["pnl"] + r["qty"] * ((p or 0) - (r["price"] or 0)) * (1 - core.FEE) if r["qty"] else 0
            done = r["profit_total"] + r.get("realized", 0.0)  # 끝난 사이클 + 진행 중 사이클의 절반 매도분 (투자일지와 같은 기준)
            cost, pnl_t, tot, cycles = cost + r["cost"], pnl_t + pnl, tot + done, cycles + r["cycles"]
            # 수수료 전 손익 = 수수료 뺀 손익 + 보유분 매수 때 낸 수수료 + 지금 팔면 낼 수수료
            gross = pnl + (r["cost"] * core.FEE + r["qty"] * (p or 0) * core.FEE if r["qty"] else 0)
            gross_t += gross
            fees += r.get("fee_total", 0.0)
            holding += 1 if r["qty"] else 0
            st = r["status"]
            tag = ("조회만", T.MUTED) if not listed else (st, self.STATUS_TAG.get(st, T.UP))
            if self.ledger_mismatch(r):  # 업비트에서 직접 팔아 잔고가 장부보다 적음 → 매매하면 기존 보유분을 팔 수 있어 표시
                tag = ("정리 필요", T.UP)
            pct = (lambda v: f"{(v / p - 1) * 100:+.1f}%" if v and p else "")  # noqa: E731
            rows.append({"id": r["coin"], "check": True, "dim": not listed, "cells": {
                "st": {"tag": tag}, "coin": {"text": r["coin"], "font": "num_b", "sub": "감시로 시작" if r.get("auto") else None},
                "price": {"text": T.fmtp(p), "fg": T.chg_color(self.grid_price(r)[1])},
                "avg": {"text": T.fmtp(r["avg"]) if r["avg"] else "-", "sub": f"{r['buys']}회 · {r['cost']:,.0f}원"},
                "pnl": {"text": f"{pnl:+,.0f}" if r["qty"] else "-", "fg": T.chg_color(pnl),
                        "sub": f"수수료 전 {gross:+,.0f}" if r["qty"] else None},
                "pos": {"draw": self.pos_bar(r["next_buy"], r["tp"], p)},
                "next": {"text": T.fmtp(r["next_buy"]) if r["next_buy"] else "-", "fg": T.UP,
                         "sub": f"{pct(r['next_buy'])} · {r['next_amt']:,.0f}원" if r["next_buy"] and r.get("next_amt") else pct(r["next_buy"])},
                "tp": {"text": T.fmtp(r["tp"]) if r["tp"] else "-", "fg": T.DOWN, "sub": pct(r["tp"])},
                "cyc": str(r["cycles"]), "tot": {"text": f"{done:+,.0f}", "fg": T.chg_color(done)},
                "own": {"text": self.own_text(r), "fg": T.MUTED, "font": "num_s"}}})
        self.g_table.set_rows(rows)
        self.update_liq_btn()
        be = [f"{r['coin']} {T.fmtp(r['breakeven'])}" for r in self.grid_rows if r.get("breakeven")]
        self.g_note.config(text="본전 절반가: " + " · ".join(be) if be else "본전 절반가는 2회 이상 매수한 뒤에 계산됩니다")
        self.g_stats.set("state", "켜짐" if g["enabled"] else "꺼짐", color=T.TEXT if g["enabled"] else T.UP,
                         sub="모의" if sim else "실전")
        buys = {r["buys"] for r in self.grid_rows if r["qty"]}
        self.g_stats.set("cost", T.fmtk(cost), "원",
                         sub=f"{holding}개 코인 · " + (f"각 {buys.pop()}회" if len(buys) == 1 else "매수 횟수 다름") if holding else "보유 없음")
        self.g_stats.set("pnl", T.fmtk(pnl_t, sign=True), "원", color=T.chg_color(pnl_t),
                         sub=(f"{pnl_t / cost * 100:+.2f}% · 수수료 전 {gross_t:+,.0f}원 (팔 때 수수료 포함 계산)" if cost else ""))
        self.g_stats.set("real", T.fmtk(tot, sign=True), "원", color=T.chg_color(tot),
                         sub=f"완료 사이클 {cycles} · 지금까지 낸 수수료 {fees:,.0f}원")
        cap = self.engine.grid_total_cap()
        extra = cap - g["total_max_krw"]
        self.g_stats.set("cap", f"{cost / cap * 100:.1f}%" if cap else "-",
                         sub=f"{cost:,.0f} / {cap:,.0f}원" + (f" (한도 {g['total_max_krw']:,} + 수익 {extra:,.0f})" if extra > 0 else ""))

    def update_liq_btn(self):
        st = self.cfg["grid"]["state"]
        n = sum(1 for c in self.g_table.checked if st.get(c, {}).get("qty"))
        self.g_liq_btn.config(text=f"선택 코인 청산 ({n})" if n else "선택 코인 청산")

    def own_text(self, r):
        """업비트 실제 잔고에서 자동매매 몫을 뺀 기존 보유분 (모의면 전체 잔고가 기존 보유)."""
        bal = self.hold.get(r["coin"])
        if bal is None or not r["price"]:
            return "—"
        g = self.cfg["grid"]
        mine = 0 if g["simulate"] or not self.engine.api else r["qty"]
        own = max(bal - mine, 0)
        return f"{T.fmtq(own)}개 ({own * r['price']:,.0f}원)" if own > 1e-12 else "—"

    def render_grid_log(self):
        rows = []
        for i, (ts, sim, coin, side, price, qty, krw, _) in enumerate(self.db.query(
                "SELECT * FROM grid_trades ORDER BY rowid DESC LIMIT 100")):
            bid = side == "bid"
            rows.append({"id": i, "cells": {"ts": {"text": ts[:19].replace("T", " "), "font": "num_s", "fg": T.MUTED},
                                            "sim": {"text": "예" if sim else "", "fg": T.MUTED},
                                            "coin": {"text": coin, "font": "num_b"},
                                            "side": {"text": "매수" if bid else "매도", "fg": T.UP if bid else T.DOWN},
                                            "price": T.fmtp(price), "qty": {"text": T.fmtq(qty), "fg": T.MUTED},
                                            "krw": f"{krw:,.0f}"}})
        self.grid_log.set_rows(rows)

    def save_grid(self):
        g, fl = self.cfg["grid"], self.g_fields
        try:
            # 쉼표·띄어쓰기·슬래시 어느 것으로 나눠 적어도 된다 (예: "SOL DOGE ADA" / "SOL,DOGE")
            coins = list(dict.fromkeys(c.upper() for c in re.split(r"[\s,，/;·]+", fl["coins"].get()) if c))
            blocked = [c for c in coins if c in core.GRID_BLOCKED]
            new = {"coins": [c for c in coins if c not in core.GRID_BLOCKED],
                   "unit_krw": int(num(fl["unit_krw"].get())), "multiplier": num(fl["multiplier"].get()),
                   "drop_pct": num(fl["drop_pct"].get()),
                   "profit_krw": int(num(fl["profit_krw"].get())), "max_krw": int(num(fl["max_krw"].get())),
                   "total_max_krw": int(num(fl["total_max_krw"].get()))}
            df = self.g_dipf
            pool = list(dict.fromkeys(c.upper() for c in re.split(r"[\s,，/;·]+", df["pool"].get()) if c))
            dip = {"enabled": self.g_dip.get(), "pool": [c for c in pool if c not in core.GRID_BLOCKED],
                   "min_pct": abs(num(df["min_pct"].get())), "max_pct": abs(num(df["max_pct"].get())),
                   "min_vol_eok": num(df["min_vol_eok"].get()), "per_day": int(num(df["per_day"].get())),
                   "max_coins": int(num(df["max_coins"].get()))}
            if dip["min_pct"] >= dip["max_pct"]:
                raise ValueError("하락 범위: 앞 숫자가 뒤 숫자보다 작아야 합니다")
        except ValueError as e:
            messagebox.showerror("자동매매", f"숫자를 확인하세요: {e}")
            return
        try:
            listed = {m["market"][4:] for m in fr.get("/market/all") if m["market"].startswith("KRW-")}
        except Exception:
            listed = None
        unknown = [c for c in new["coins"] + dip["pool"] if listed is not None and c not in listed]
        if unknown:
            messagebox.showerror("자동매매", f"업비트 원화마켓에 없는 코인입니다: {', '.join(unknown)}\n"
                                            "기호를 확인하세요 (예: BCH, SOL, DOGE, ADA).")
            return
        if not 1 <= new["multiplier"] <= 3:
            messagebox.showerror("자동매매", "배수는 1~3 사이로 적어 주세요. (1 = 매번 같은 금액, 2 = 마틴게일)")
            return
        if new["unit_krw"] < 5000:
            messagebox.showerror("자동매매", "업비트 최소 주문이 5,000원이라 1회 금액은 5,000원 이상이어야 합니다.")
            return
        if new["multiplier"] > 1 and new["multiplier"] != g.get("multiplier", 1.0):
            steps, cum, amt, n = [], 0, new["unit_krw"], 0
            while cum + amt <= new["max_krw"] and n < 12:  # 코인 한도 안에서 몇 번까지 사는지
                cum += amt
                n += 1
                steps.append(f"{n}회 {amt:,.0f}원 (누적 {cum:,.0f}원, 시작 대비 약 {(1 - (1 - new['drop_pct'] / 100) ** (n - 1)) * -100:.0f}%)")
                amt = round(new["unit_krw"] * new["multiplier"] ** n / 10) * 10
            if not messagebox.askyesno(
                    "마틴게일 (배수 매수)", f"추가 매수 금액이 {new['multiplier']:g}배씩 커집니다. 코인 1개 기준:\n\n" + "\n".join(steps)
                    + f"\n\n→ 그다음 {amt:,.0f}원은 코인 한도 {new['max_krw']:,}원을 넘어 사지 않습니다."
                    f"\n전체 한도 {new['total_max_krw']:,}원에 닿으면 모든 코인의 추가 매수가 멈춥니다.\n\n저장할까요?", icon="warning"):
                return
        going_live = self.g_on.get() and not self.g_sim.get() and (g["simulate"] or not g["enabled"])
        if going_live and not messagebox.askyesno(
                "자동매매 실전", f"⚠ 실전으로 켜면 승인 없이 업비트에 시장가 주문이 자동으로 나갑니다.\n"
                f"코인 {', '.join(new['coins'])} · 1회 {new['unit_krw']:,}원 · 코인별 한도 {new['max_krw']:,}원 · "
                f"전체 한도 {new['total_max_krw']:,}원\n\n진행할까요?",
                icon="warning"):
            return
        live_after = not self.g_sim.get() and self.engine.api
        if dip["enabled"] and not g["dip"]["enabled"] and live_after and self.g_on.get() and not messagebox.askyesno(
                "자동매매 감시 · 실전", f"⚠ 실전입니다. 추천 목록 {len(dip['pool'])}개 중 전일 대비 {dip['min_pct']:g}~{dip['max_pct']:g}% "
                f"떨어진 코인을 자동으로 목록에 넣고 {new['unit_krw']:,}원씩 시장가로 삽니다 (하루 최대 {dip['per_day']}개).\n\n켤까요?",
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
        if self.cfg.get("stopped") and self.g_on.get():
            self.cfg["stopped"]["grid"] = True  # 정지 중이면 재개할 때 켠다
            self.g_on.set(False)
            msg += "\n긴급 정지 중이라 [재개]를 누르면 켜집니다."
        g.update(new, enabled=self.g_on.get(), simulate=self.g_sim.get(), half_at_breakeven=self.g_half.get(),
                 reinvest=self.g_reinvest.get())
        g["dip"].update(dip)
        core.save_config(self.cfg)
        self.set_grid_fields()
        self.render_watch()
        self.render_rules()
        msg += f"\n자동매매 코인: {', '.join(new['coins']) or '없음'}"
        messagebox.showinfo("자동매매", msg)
        self.engine.request("grid_refresh")

    def set_grid_fields(self):
        g = self.cfg["grid"]
        vals = {"coins": ",".join(g["coins"]), "unit_krw": f"{g['unit_krw']:,}", "multiplier": f"{g.get('multiplier', 1.0):g}",
                "drop_pct": f"{g['drop_pct']:g}",
                "profit_krw": f"{g['profit_krw']:,}", "max_krw": f"{g['max_krw']:,}", "total_max_krw": f"{g['total_max_krw']:,}"}
        for k, e in self.g_fields.items():
            e.delete(0, "end")
            e.insert(0, vals[k])
        self.g_on.set(g["enabled"])
        self.g_sim.set(g["simulate"])

    def grid_toggle_listed(self):
        """[구분 변경]: 체크한 코인이 자동매매 중이면 조회만으로, 조회만이면 자동매매로."""
        g = self.cfg["grid"]
        sel = list(self.g_table.checked)
        if not sel:
            messagebox.showinfo("자동매매", "표에서 바꿀 코인의 체크박스(☐)를 누르세요.")
            return
        to_on = [c for c in sel if c not in g["coins"]]
        to_off = [c for c in sel if c in g["coins"]]
        live = not (g["simulate"] or not self.engine.api)
        held = [c for c in to_on if g["state"].get(c, {}).get("qty")]
        lines = []
        if to_on:
            lines.append(f"조회만 → 자동매매: {', '.join(to_on)}" + (f"\n  ({', '.join(held)}: 지금 평단·매수 횟수를 이어서 매매)" if held else ""))
        if to_off:
            lines.append(f"자동매매 → 조회만: {', '.join(to_off)}\n  (보유분은 그대로, 추가 매수·익절만 멈춤. 산 적 없는 코인은 표에서 빠짐)")
        if to_on:
            lines.append("⚠ 실전입니다. 자동매매 코인은 승인 없이 시장가 주문이 나갑니다." if live else "모의입니다. 가상으로만 사고팝니다.")
            if not g["enabled"]:
                lines.append("※ 자동매매가 꺼져 있어 [켜기]를 체크하고 저장해야 움직입니다.")
        if not messagebox.askyesno("구분 변경", "\n\n".join(lines) + "\n\n바꿀까요?", icon="warning" if live and to_on else "question"):
            return
        g["coins"] = [c for c in g["coins"] if c not in to_off] + to_on
        for c in sel:  # 직접 바꾼 코인은 감시 표시를 지운다 (익절 뒤에도 목록 유지)
            g["state"].get(c, {}).pop("auto", None)
        core.save_config(self.cfg)
        self.set_grid_fields()
        self.g_table.checked.clear()
        self.update_liq_btn()
        self.show_notice(" · ".join(filter(None, [f"자동매매로: {', '.join(to_on)}" if to_on else "",
                                                  f"조회만으로: {', '.join(to_off)}" if to_off else ""])), 8)
        self.engine.request("grid_refresh")

    def toggle_watch(self):
        g = self.cfg["grid"]
        d = g["dip"]
        on = not d["enabled"]
        live = not (g["simulate"] or not self.engine.api)
        if on:
            msg = (f"추천 목록 {len(d['pool'])}개 중 자동매매 목록에 없는 코인을 5분마다 확인해서,\n"
                   f"전일 대비 {d['min_pct']:g}% 이상 떨어지면(−{d['max_pct']:g}%보다 더 빠진 급락은 제외) 자동매매를 시작합니다.\n"
                   f"1회 {g['unit_krw']:,}원 시작 매수 · 하루 최대 {d['per_day']}개 · 목록 최대 {d['max_coins']}개\n\n"
                   + ("⚠ 실전입니다. 시장가 주문이 자동으로 나갑니다.\n\n" if live else "모의입니다. 가상으로만 사고팝니다.\n\n")
                   + ("" if g["enabled"] else "※ 자동매매가 꺼져 있어 [켜기]를 체크하고 저장해야 움직입니다.\n\n") + "감시를 켤까요?")
            if not messagebox.askyesno("자동매매 감시", msg, icon="warning" if live else "question"):
                return
        d["enabled"] = on
        core.save_config(self.cfg)
        self.g_dip.set(on)
        self.render_rules()
        self.render_watch()
        if on:
            self.engine.request("grid_dip", True)

    def render_watch(self):
        d = self.cfg["grid"]["dip"]
        on = d["enabled"]
        self.g_watch_btn.config(text="자동매매 감시 중" if on else "자동매매 감시 꺼짐",
                                bg=T.ACCENT if on else T.PANEL, fg=T.GROUND if on else T.TEXT,
                                highlightbackground=T.ACCENT if on else T.DIVIDER)
        self.g_watch_btn.normal_bg = T.ACCENT if on else T.PANEL
        for w in self.g_watch.winfo_children():
            w.destroy()
        if not on:
            lab(self.g_watch, "감시 꺼짐 · [자동매매 감시 꺼짐]을 누르면 추천 목록 중 떨어진 코인을 자동으로 시작합니다",
                "kr_xs", fg=T.MUTED).pack(side="left")
            return
        lab(self.g_watch, f"감시 중 · 전일 대비 −{d['min_pct']:g}% 이상이면 시작 ({self.dip_at or '확인 대기'})",
            "kr_xs", fg=T.ACCENT).pack(side="left", padx=(0, 10))
        for coin, chg, note in self.dip_watch[:12]:
            hit = note == "조건 충족"
            col = T.UP if hit else T.chg_color(chg) if not note else T.MUTED
            lab(self.g_watch, f"{coin} {chg:+.1f}%" + (f"({note})" if note and not hit else ""), "num_xs" if not note else "kr_xs",
                fg=col).pack(side="left", padx=(0, 10))

    def ledger_mismatch(self, r):
        """실전인데 업비트 실제 잔고가 자동매매 장부보다 적으면 True (업비트에서 직접 판 경우)."""
        g = self.cfg["grid"]
        bal = self.hold.get(r["coin"])
        return (not g["simulate"] and self.engine.api and r["qty"] > 0 and bal is not None
                and bal < r["qty"] * 0.99)

    def grid_liquidate(self):
        g = self.cfg["grid"]
        rows = {r["coin"]: r for r in self.grid_rows}
        sel = [c for c in self.g_table.checked if g["state"].get(c, {}).get("qty")]
        if not sel:
            messagebox.showinfo("자동매매", "표에서 청산할 코인의 체크박스(☐)를 누르세요.\n(자동매매 보유분이 있는 코인만 청산됩니다)")
            return
        live = not g["simulate"] and self.engine.api
        sell, forget, lines = [], [], []
        for c in sel:
            r = rows.get(c)
            p = self.grid_price(r)[0] if r else None
            value = (r["qty"] * p) if r and p else 0
            if r and self.ledger_mismatch(r):
                forget.append(c)
                lines.append(f"• {c}: 업비트 잔고({T.fmtq(self.hold.get(c, 0))}개)가 장부({T.fmtq(r['qty'])}개)보다 적습니다 "
                             "(업비트에서 직접 파셨나요?) → 장부만 정리")
            elif live and value < 5_500:
                forget.append(c)
                lines.append(f"• {c}: {value:,.0f}원어치라 업비트 최소 주문(5,000원) 미만이라 팔 수 없습니다 → 장부만 정리 "
                             "(코인은 계좌에 남고 기존 보유로 표시)")
            else:
                sell.append(c)
        msg = []
        if sell:
            msg.append(f"시장가로 전량 매도하고 목록에서 뺍니다: {', '.join(sell)}\n(기존 보유분은 건드리지 않습니다)")
        if forget:
            msg.append("장부만 정리합니다 (현재가로 판 것으로 추정해 투자일지에 기록):\n" + "\n".join(lines))
        if not messagebox.askyesno("청산", "\n\n".join(msg) + "\n\n진행할까요?", icon="warning"):
            return
        for coin in sell:
            self.engine.request("grid_liquidate", coin)
        for coin in forget:
            self.engine.request("grid_forget", coin)
        self.g_table.checked.clear()
        self.update_liq_btn()

    # ---------------- ④ 주문 (3a: 승인 흐름) ----------------
    def build_orders(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "주문")
        self.orders_tab = f
        g = T.GROUND
        top = tk.Frame(f, bg=g)
        top.pack(fill="x", padx=18, pady=(18, 12))
        self.o_title = lab(top, "제안 없음", "kr_big", bg=g)
        self.o_title.pack(side="left")
        self.o_meta = lab(top, "", "kr_xs", fg=T.MUTED, bg=g)
        self.o_meta.pack(side="left", padx=12, pady=(6, 0))
        self.o_seg = W.Segmented(top, ["변경만", "전체"], self.cfg["ui"]["orders_filter"], self.set_orders_filter)
        self.o_seg.pack(side="right")
        self.o_done = tk.Frame(f, bg=T.BANNER_BG)
        self.o_done_lab = lab(self.o_done, "", "kr_s", fg=T.TEXT, bg=T.BANNER_BG)
        self.o_done_lab.pack(side="left", padx=12, pady=6)
        link = lab(self.o_done, "주문 실행 기록 보기", "kr_s", fg=T.ACCENT, bg=T.BANNER_BG, cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e: self.nb.select(TAB_LOGS))
        x = lab(self.o_done, "✕", "kr_s", fg=T.MUTED, bg=T.BANNER_BG, cursor="hand2", padx=12)
        x.pack(side="right")
        x.bind("<Button-1>", lambda e: self.o_done.pack_forget())
        self.o_stats = W.StatCells(f, [("chg", "변경"), ("buy", "신규 매수"), ("sell", "신규 매도"), ("cancel", "취소"),
                                       ("cash", "실행 후 주문 가능 현금")])
        self.o_stats.pack(fill="x", padx=18)
        bottom = tk.Frame(f, bg=g)
        bottom.pack(side="bottom", fill="x", padx=18, pady=(12, 14))
        T.Btn(bottom, "플랜과 다시 비교", lambda: self.engine.request("make_proposal", "수동 비교", True), bg=g).pack(side="left")
        T.Btn(bottom, "레벨 재계산", self.recalc, bg=g).pack(side="left", padx=8)
        self.o_ok = T.Btn(bottom, "승인·실행", self.approve, "primary", bg=g)
        self.o_ok.pack(side="right")
        tk.Frame(bottom, bg=g, width=32).pack(side="right")  # 무시와 실행 사이 32px 이상
        ign = T.Btn(bottom, "무시", self.dismiss, "ghost", bg=g)
        ign.config(fg=T.MUTED, font=T.F["kr_btn"])
        ign.pack(side="right")
        self.o_sel = tk.Frame(bottom, bg=g)
        self.o_sel.pack(side="right", padx=16)
        tw = tk.Frame(f, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        tw.pack(fill="both", expand=True, padx=18, pady=(14, 0))
        cols = [{"key": "chk", "w": 40}, {"key": "st", "title": "상태", "w": 80, "anchor": "center"},
                {"key": "name", "title": "구분", "w": 200, "grow": 1},
                {"key": "price", "title": "가격", "w": 160, "anchor": "e"},
                {"key": "pct", "title": "현재가 대비", "w": 130, "anchor": "e"},
                {"key": "qty", "title": "수량", "w": 170, "anchor": "e"},
                {"key": "amt", "title": "금액(원)", "w": 160, "anchor": "e"}]
        self.o_table = W.Table(tw, cols, rh=36, check=True, on_check=self.update_order_sums, pad=16,
                               empty=["변경할 주문이 없습니다", "플랜과 업비트 예약 주문이 같습니다 · [플랜과 다시 비교]로 다시 확인할 수 있습니다"])
        self.o_table.pack(fill="both", expand=True)

    def set_orders_filter(self, name):
        self.cfg["ui"]["orders_filter"] = name
        core.save_config(self.cfg)
        self.render_proposal()

    def proposal_counts(self):
        p = self.proposal
        return len(p["todo"]) if p and p.get("todo") else 0

    def render_proposal(self):
        n = self.proposal_counts()
        self.nb.set_badge(TAB_ORDERS, n, T.DOWN)
        if not self.shown(TAB_ORDERS):
            return
        p = self.proposal
        at = self.board.get("_levels_at", "")
        lv_at = at[5:16].replace("T", " ") if len(at) > 5 else "-"
        if not p:
            self.o_title.config(text="변경할 주문 없음")
            self.o_meta.config(text=f"레벨 기준 {lv_at}")
            self.o_table.set_rows([])
            self.update_order_sums()
            return
        self.o_title.config(text=p["reason"])
        self.o_meta.config(text=f"{self.prop_time} 비교 · 레벨 기준 {lv_at}")
        if p.get("id") != self.prop_seen:  # 새 제안이면 변경 행을 모두 선택해 둔다
            self.prop_seen = p.get("id")
            self.o_table.checked = set(range(len(p["todo"])))
        index = {id(o): i for i, (_, _, o) in enumerate(p["todo"])}
        only = self.cfg["ui"]["orders_filter"] == "변경만"
        rows = []
        for coin in fr.COINS:
            mine = [(st, o) for st, c, o in p["rows"] if c == coin]
            if not mine:
                continue
            cnt = {k: sum(1 for st, _ in mine if st == k) for k in ("주문", "취소", "유지")}
            sub = " · ".join(f"{k} {v}" for k, v in cnt.items() if v)
            rows.append({"group": coin, "sub": sub, "right": f"유지 {cnt['유지']}건 숨김" if only and cnt["유지"] else ""})
            cur = self.prices.get(coin)
            for k in ("취소", "주문", "유지"):
                for n_, (st, o) in enumerate(x for x in mine if x[0] == k):
                    if st == "유지" and only:
                        continue
                    ask = o["side"] == "ask"
                    if o["label"] == "플랜 밖":
                        name, after, color = f"플랜 밖 {'매도' if ask else '매수'} 예약", "", T.TEXT
                    else:
                        name, after = plan_label(o["label"])
                        color = T.DOWN if ask else T.UP
                    tagc = {"주문": T.DOWN, "취소": T.UP, "유지": T.MUTED}[st]
                    change = st != "유지"
                    rows.append({"id": index.get(id(o)) if change else f"keep-{coin}-{n_}", "check": change,
                                 "dim": not change, "cells": {
                                     "st": {"tag": (st, tagc)}, "name": {"text": name, "fg": color, "after": after},
                                     "price": T.fmtp(o["price"]),
                                     "pct": {"text": f"{(o['price'] / cur - 1) * 100:+.1f}%" if cur else "-",
                                             "fg": color if color != T.TEXT else T.MUTED},
                                     "qty": {"text": T.fmtq_c(coin, o["volume"]), "fg": T.MUTED},
                                     "amt": T.fmtk(o["price"] * o["volume"])}})
        self.o_table.set_rows(rows)
        self.update_order_sums()

    def selected_todo(self):
        p = self.proposal
        if not p or not p.get("todo"):
            return []
        return [(i, t) for i, t in enumerate(p["todo"]) if i in self.o_table.checked]

    def order_sums(self):
        sel = self.selected_todo()
        buys = [o for k, _, o in (t for _, t in sel) if k == "place" and o["side"] == "bid"]
        sells = [o for k, _, o in (t for _, t in sel) if k == "place" and o["side"] == "ask"]
        cancels = [o for k, _, o in (t for _, t in sel) if k == "cancel"]
        buy = sum(o["price"] * o["volume"] for o in buys)
        sell = sum(o["price"] * o["volume"] for o in sells)
        freed = sum(o["price"] * o["volume"] for o in cancels if o["side"] == "bid")
        cash = self.board.get("_krw_free")
        if cash is None:
            cash = self.hold.get("KRW")
        after = cash + freed - buy if cash is not None else None
        return sel, buys, sells, cancels, buy, sell, cash, after

    def update_order_sums(self):
        n = self.proposal_counts()
        sel, buys, sells, cancels, buy, sell, cash, after = self.order_sums()
        self.o_stats.set("chg", f"{n}", "건", sub="승인 대기" if n else "변경 없음")
        self.o_stats.set("buy", T.fmtk(buy), "원", color=T.UP if buy else T.TEXT, sub=f"{len(buys)}건 선택")
        self.o_stats.set("sell", T.fmtk(sell), "원", color=T.DOWN if sell else T.TEXT, sub=f"{len(sells)}건 선택")
        self.o_stats.set("cancel", f"{len(cancels)}", "건", sub="플랜 밖 예약 주문")
        self.o_stats.set("cash", T.fmtk(after) if after is not None else "-", "원",
                         color=T.UP if after is not None and after < 0 else T.TEXT,
                         sub=f"현재 {cash:,.0f}원" if cash is not None else "")
        for w in self.o_sel.winfo_children():
            w.destroy()
        parts = [("선택 ", T.MUTED, "kr_s"), (f"{len(sel)}건", T.TEXT, "kr_b"), (" · 매수 ", T.MUTED, "kr_s"),
                 (f"{buy:,.0f}원", T.UP, "num"), (" · 매도 ", T.MUTED, "kr_s"), (f"{sell:,.0f}원", T.DOWN, "num"),
                 (" · 취소 ", T.MUTED, "kr_s"), (f"{len(cancels)}건", T.TEXT, "kr_s")]
        for text, fg, font in parts:
            lab(self.o_sel, text, font, fg=fg, bg=T.GROUND).pack(side="left")
        if not self.executing:
            self.o_ok.config(text=f"{len(sel)}건 승인·실행" if sel else "승인·실행")

    def approve(self):
        if self.executing:
            return
        p = self.proposal
        sel, buys, sells, cancels, buy, sell, cash, after = self.order_sums()
        if not p or not sel:
            messagebox.showinfo("FibTrader", "실행할 변경이 없습니다. 표에서 실행할 행을 체크하세요.")
            return
        if self.cfg.get("stopped"):
            messagebox.showwarning("FibTrader", "긴급 정지 중입니다. 상단의 [재개]를 누른 뒤 승인하세요.")
            return
        sim = self.cfg["simulate"] or not self.engine.api
        w, body = self.dialog(f"주문 {len(sel)}건 실행", "모의" if sim else "실전", T.ACCENT if sim else T.UP)
        items = [("신규 매수", f"{len(buys)}건 · {buy:,.0f}원", T.UP), ("신규 매도", f"{len(sells)}건 · {sell:,.0f}원", T.DOWN),
                 ("취소", f"{len(cancels)}건", T.TEXT),
                 ("실행 후 주문 가능 현금", f"{after:,.0f}원" if after is not None else "-", T.UP if after and after < 0 else T.TEXT)]
        for i, (k, v, c) in enumerate(items):
            lab(body, k, "kr").grid(row=i, column=0, sticky="w", pady=4)
            lab(body, v, "kr_b", fg=c).grid(row=i, column=1, sticky="e", pady=4, padx=(60, 0))
        body.columnconfigure(1, weight=1)
        note = ("모의 모드입니다. 실제 주문은 나가지 않고 기록만 남습니다." if sim
                else "업비트 계좌로 주문이 나갑니다. 실행 직전에 업비트 주문 상태를 다시 확인하고, 바뀌었으면 실행하지 않습니다.")
        box = tk.Frame(w, bg=T.GROUND)
        box.pack(fill="x", padx=16, pady=(12, 0))
        lab(box, note, "kr_s", fg=T.TEXT if sim else T.UP, bg=T.GROUND, wraplength=420, justify="left").pack(
            anchor="w", padx=10, pady=8)
        if len(sel) < self.proposal_counts():
            lab(w, f"※ 체크하지 않은 {self.proposal_counts() - len(sel)}건은 실행하지 않습니다.", "kr_xs",
                fg=T.MUTED).pack(anchor="w", padx=16, pady=(8, 0))
        self.dialog_buttons(w, "돌아가기", "실행", lambda: self.run_approve(p["id"], [i for i, _ in sel]), danger=not sim)

    def run_approve(self, pid, idx):
        self.executing = True  # 두 번 눌러도 한 번만
        self.o_ok.config(text="실행 중…")
        self.engine.request("execute", pid, sorted(idx))

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
            self.root.after(700, self.after_mode_change)

    def resume(self):
        st = self.cfg.get("stopped") or {}
        mode = "반자동" if st.get("mode", "semi") == "semi" else "알림만"
        if messagebox.askyesno("재개", f"긴급 정지를 풉니다.\n\n모드: {mode}\n자동매매: {'켜짐' if st.get('grid') else '꺼짐'}\n\n"
                                     "정지 때 취소한 주문은 되살리지 않습니다. 반자동이면 플랜과 다시 비교한 제안이 주문 탭에 뜹니다.\n\n재개할까요?"):
            self.engine.request("resume")
            self.root.after(700, self.after_mode_change)

    def after_mode_change(self):
        self.mode_var.set(self.cfg["mode"])
        self.g_on.set(self.cfg["grid"]["enabled"])
        self.settings_snapshot = self.settings_values()
        self.update_dirty()
        self.refresh_chrome()
        self.render_grid_tab()

    # ---------------- ⑤ 알림·기록 (12-6) ----------------
    def build_logs(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "알림·기록")
        wrap = tk.Frame(f, bg=T.GROUND)
        wrap.pack(fill="both", expand=True, padx=18, pady=18)
        wrap.columnconfigure(0, weight=3, uniform="logs")
        wrap.columnconfigure(1, weight=2, uniform="logs")
        wrap.rowconfigure(0, weight=1)
        left, lh = card(wrap, "알림", "행을 누르면 전체 내용", packed=False)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        W.Segmented(lh, ["전체", "주문", "매매", "시스템"], "전체", self.set_alert_filter).pack(side="right")
        cols = [{"key": "dot", "w": 16}, {"key": "ts", "title": "시간", "w": 130},
                {"key": "kind", "title": "종류", "w": 64}, {"key": "title", "title": "제목", "w": 190},
                {"key": "msg", "title": "내용", "w": 120, "grow": 1}]
        self.al_table = W.Table(left, cols, rh=42, on_click=self.toggle_alert, pad=12, empty=["알림이 없습니다"])
        self.al_table.pack(fill="both", expand=True)
        right, rh = card(wrap, "주문 실행 기록", packed=False)
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        T.Btn(rh, "새로고침", self.render_logs).pack(side="right")
        cols = [{"key": "ts", "title": "시간", "w": 118}, {"key": "sim", "title": "모의", "w": 44},
                {"key": "what", "title": "내용", "w": 150, "grow": 3}, {"key": "res", "title": "결과", "w": 60, "grow": 1, "anchor": "e"}]
        self.act_table = W.Table(right, cols, rh=40, pad=12,
                                 empty=["실행된 주문이 없습니다", "주문 탭에서 승인하면 여기에 결과가 남습니다"])
        self.act_table.pack(fill="both", expand=True)
        self.act_empty_btn = T.Btn(right, "주문 탭 열기", lambda: self.nb.select(TAB_ORDERS))

    def set_alert_filter(self, name):
        self.alert_filter = name
        self.render_logs()

    def max_alert_id(self):
        return self.alert_data[0][0] if self.alert_data else 0

    def toggle_alert(self, rid):
        self.alert_open.symmetric_difference_update({rid})
        self.alert_readset.add(rid)
        self.render_logs()

    def load_alerts(self):
        """알림 데이터·배지·현황 최근 알림은 탭이 안 보여도 갱신 (표는 보일 때만 그린다)."""
        self.alert_data = self.db.query("SELECT rowid, * FROM alerts ORDER BY rowid DESC LIMIT 300")
        seen = self.cfg["ui"]["alerts_seen"]
        if self.nb.index() == TAB_LOGS:
            self.cfg["ui"]["alerts_seen"] = seen = self.max_alert_id()
        self.nb.set_badge(TAB_LOGS, sum(1 for r in self.alert_data if r[0] > seen), T.MUTED)
        if self.shown(TAB_BOARD):
            self.render_side_alerts()

    def render_logs(self):
        self.load_alerts()
        if not self.shown(TAB_LOGS):
            return
        read = self.cfg["ui"]["alerts_read"]
        pending = self.proposal_counts()
        newest_prop = next((r[0] for r in self.alert_data if r[2] == "proposal"), None)
        rows = []
        for rid, ts, kind, title, msg in self.alert_data:
            grp = ALERT_GROUP.get(kind, "시스템")
            if self.alert_filter != "전체" and grp != self.alert_filter:
                continue
            unread = rid > read and rid not in self.alert_readset
            opened = rid in self.alert_open
            dot = (lambda c, x0, x1, cy: c.create_oval(x0, cy - 3, x0 + 6, cy + 3, fill=T.DOWN, outline="")) if unread else None
            row = {"id": rid, "cells": {
                "dot": {"draw": dot} if dot else None,
                "ts": {"text": ts[5:19], "font": "num_s", "fg": T.MUTED},
                "kind": {"tag": (grp, GROUP_COLOR[grp])},
                "title": {"text": title, "font": "kr_b" if unread else "kr"},
                "msg": {"text": msg if opened else msg.replace("\n", " / "), "fg": T.TEXT if opened else T.MUTED}}}
            if opened:
                row["wrap"] = "msg"
            if kind == "proposal" and rid == newest_prop and pending:
                row["wrap"] = "msg"
                row["button"] = ("주문 탭으로 이동", lambda: self.nb.select(TAB_ORDERS))
            rows.append(row)
        self.al_table.set_rows(rows)
        acts = []
        for i, (ts, sim, kind, market, side, price, vol, res) in enumerate(self.db.query(
                "SELECT * FROM actions ORDER BY rowid DESC LIMIT 200")):
            word = ("취소 " if kind == "cancel" else "주문 ") + market.replace("KRW-", "") + (" 매도 " if side == "ask" else " 매수 ")
            ok = res == "ok"
            acts.append({"id": i, "cells": {"ts": {"text": ts[5:19].replace("T", " "), "font": "num_s", "fg": T.MUTED},
                                            "sim": {"text": "예" if sim else "", "fg": T.MUTED},
                                            "what": f"{word}{T.fmtp(price)} × {T.fmtq(vol)}",
                                            "res": {"text": "완료" if ok else res, "fg": T.LINE_NOW if ok else T.UP,
                                                    "font": "kr_s"}}})
        self.act_table.set_rows(acts)
        if acts:
            self.act_empty_btn.place_forget()
        else:
            self.act_empty_btn.place(relx=0.5, rely=0.5, y=56, anchor="center")

    # ---------------- ⑥ 설정 (3b) ----------------
    def build_settings(self, nb):
        f = tk.Frame(nb, bg=T.GROUND)
        nb.add(f, "설정")
        c = self.cfg
        bar = tk.Frame(f, bg=T.PANEL, height=60, highlightthickness=1, highlightbackground=T.DIVIDER)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self.set_state = lab(bar, "", "kr_s", fg=T.MUTED)
        self.set_state.pack(side="left", padx=18)
        T.Btn(bar, "저장", self.save_settings, "primary").pack(side="right", padx=(8, 18), pady=13)
        T.Btn(bar, "되돌리기", self.revert_settings).pack(side="right", pady=13)
        cols = tk.Frame(f, bg=T.GROUND)
        cols.pack(fill="both", expand=True, padx=18, pady=18)
        colf = []
        for i in range(3):
            cols.columnconfigure(i, weight=1, uniform="set")
            fr_ = tk.Frame(cols, bg=T.GROUND)
            fr_.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 9, 0 if i == 2 else 9))
            colf.append(fr_)
        self.sv = {}

        def var(key, value):
            v = tk.StringVar(value=value)
            v.trace_add("write", lambda *_: self.update_dirty())
            self.sv[key] = v
            return v

        def entry(parent, key, value, unit, width=12, integer=True):
            row = tk.Frame(parent, bg=T.PANEL)
            e = ttk.Entry(row, textvariable=var(key, value), style="Card.TEntry", justify="right", width=width,
                          font=T.F["num"])
            e.pack(side="left", fill="x", expand=True)
            if integer:  # 칸을 떠나면 천 단위 콤마
                e.bind("<FocusOut>", lambda ev, k=key: self.comma(k))
            lab(row, unit, "kr_s", fg=T.MUTED, width=2, anchor="w").pack(side="left", padx=(6, 0))
            return row

        def field(parent, title, desc, key, value, unit, integer=True):
            r = tk.Frame(parent, bg=T.PANEL)
            r.pack(fill="x", pady=(0, 12))
            t = tk.Frame(r, bg=T.PANEL)
            t.pack(side="left", fill="x", expand=True)
            lab(t, title, "kr_b").pack(anchor="w")
            lab(t, desc, "kr_xs", fg=T.MUTED).pack(anchor="w")
            entry(r, key, value, unit, width=9, integer=integer).pack(side="right")

        # 1열: 운영 모드 / 매수 예산 · 비중
        m, _ = card(colf[0], "운영 모드", pady=(0, 18))
        mb = tk.Frame(m, bg=T.PANEL)
        mb.pack(fill="x", padx=16, pady=(0, 14))
        self.mode_var = tk.StringVar(value=c["mode"])
        self.mode_var.trace_add("write", lambda *_: self.update_dirty())
        for val, name, desc in (("semi", "반자동", "제안 → 승인 → 실행"), ("alert", "알림만", "주문 없이 알림만 보냄")):
            r = tk.Frame(mb, bg=T.PANEL)
            r.pack(fill="x", pady=2)
            ttk.Radiobutton(r, text=name, value=val, variable=self.mode_var, style="Panel.TRadiobutton").pack(side="left")
            lab(r, desc, "kr_xs", fg=T.MUTED).pack(side="left", padx=8)
        self.sim_var = tk.BooleanVar(value=c["simulate"])
        self.sim_box = tk.Frame(mb, bg=T.PANEL, highlightthickness=1, highlightbackground=T.DIVIDER)
        self.sim_box.pack(fill="x", pady=(10, 0))
        self.sim_toggle = W.Toggle(self.sim_box, c["simulate"], self.toggle_sim)
        self.sim_toggle.pack(side="left", padx=12, pady=14)
        st = tk.Frame(self.sim_box, bg=T.PANEL)
        st.pack(side="left", fill="x")
        self.sim_title = lab(st, "", "kr_b")
        self.sim_title.pack(anchor="w")
        self.sim_desc = lab(st, "", "kr_xs", fg=T.MUTED)
        self.sim_desc.pack(anchor="w")

        b, _ = card(colf[0], "매수 예산 · 비중")
        bb = tk.Frame(b, bg=T.PANEL)
        bb.pack(fill="x", padx=16, pady=(0, 14))
        lab(bb, "매수 예산", "kr_xs", fg=T.MUTED).pack(anchor="w")
        entry(bb, "buy_budget", f"{c['buy_budget']:,}", "원").pack(fill="x", pady=(4, 10))
        self.split_amt = {}
        for coin in fr.COINS:
            r = tk.Frame(bb, bg=T.PANEL)
            r.pack(fill="x", pady=3)
            lab(r, coin, "num_b", width=5, anchor="w").pack(side="left")
            entry(r, f"split_{coin}", f"{c['buy_split'][coin]:g}", "", width=7, integer=False).pack(side="left")
            self.split_amt[coin] = lab(r, "", "num_s", fg=T.MUTED)
            self.split_amt[coin].pack(side="right")
        self.split_bar = tk.Canvas(bb, height=4, bg=T.TRACK_10, highlightthickness=0)
        self.split_bar.pack(fill="x", pady=(10, 6))
        sr = tk.Frame(bb, bg=T.PANEL)
        sr.pack(fill="x")
        lab(sr, "비중 합계", "kr_xs", fg=T.MUTED).pack(side="left")
        self.split_sum = lab(sr, "", "kr_b")
        self.split_sum.pack(side="right")

        # 2열: 알림 · 표시 / 안전장치
        a, _ = card(colf[1], "알림 · 표시", pady=(0, 18))
        ab = tk.Frame(a, bg=T.PANEL)
        ab.pack(fill="x", padx=16, pady=(0, 2))
        field(ab, "근접 알림 범위", "레벨에 이만큼 가까워지면 알림을 보냄", "near_pct", f"{c['near_pct']:g}", "%", False)
        r = tk.Frame(ab, bg=T.PANEL)
        r.pack(fill="x", pady=(0, 12))
        t = tk.Frame(r, bg=T.PANEL)
        t.pack(side="left", fill="x", expand=True)
        lab(t, "근접 강조 범위", "kr_b").pack(anchor="w")
        lab(t, "현황 눈금자에서 배경을 칠할 범위", "kr_xs", fg=T.MUTED).pack(anchor="w")
        nh = c["ui"].get("near_highlight_pct", 5)
        box = tk.Frame(r, bg=T.PANEL)
        box.pack(side="right")
        cb = ttk.Combobox(box, textvariable=var("near_hl", "끔" if not nh else f"{nh:g}"), values=["끔", "3", "5", "10"],
                          width=7, state="readonly", style="Card.TCombobox", justify="right")
        cb.pack(side="left")
        lab(box, "%", "kr_s", fg=T.MUTED, width=2, anchor="w").pack(side="left", padx=(6, 0))
        field(ab, "확인 간격", "시세·주문 확인 주기", "every_sec", f"{c['every_sec']}", "초")
        s, _ = card(colf[1], "안전장치")
        sb = tk.Frame(s, bg=T.PANEL)
        sb.pack(fill="x", padx=16, pady=(0, 2))
        field(sb, "1건 최대 금액", "넘는 주문은 막음", "max_order_krw", f"{c['max_order_krw']:,}", "원")
        field(sb, "하루 최대 실주문", "모의 주문은 세지 않음", "max_orders_per_day", f"{c['max_orders_per_day']}", "건")
        field(sb, "수량 차이 허용", "플랜과 이 % 이상 다르면 변경으로 봄", "volume_tol_pct", f"{c['volume_tol_pct']:g}", "%", False)

        # 3열: 매일 모으기 / 진행 단계 / 연결 · 실행
        d, _ = card(colf[2], "매일 모으기", pady=(0, 18))
        dbx = tk.Frame(d, bg=T.PANEL)
        dbx.pack(fill="x", padx=16, pady=(0, 14))
        for coin in fr.COINS:
            r = tk.Frame(dbx, bg=T.PANEL)
            r.pack(fill="x", pady=3)
            lab(r, coin, "num_b", width=5, anchor="w").pack(side="left")
            entry(r, f"dca_{coin}", f"{c['dca_daily'].get(coin, 0):,}", "원").pack(side="left", fill="x", expand=True)
        dr = tk.Frame(dbx, bg=T.PANEL)
        dr.pack(fill="x", pady=(8, 0))
        lab(dr, "하루 합계", "kr_xs", fg=T.MUTED).pack(side="left")
        self.dca_sum = lab(dr, "", "kr_b")
        self.dca_sum.pack(side="right")
        p, _ = card(colf[2], "진행 단계", pady=(0, 18))
        pb = tk.Frame(p, bg=T.PANEL)
        pb.pack(fill="x", padx=16, pady=(0, 14))
        lab(pb, "", "kr_xs").grid(row=0, column=0)
        lab(pb, "매도 체결 단계", "kr_xs", fg=T.MUTED).grid(row=0, column=1, pady=(0, 6))
        lab(pb, "매수 체결 단계", "kr_xs", fg=T.MUTED).grid(row=0, column=2, pady=(0, 6))
        pb.columnconfigure(1, weight=1)
        pb.columnconfigure(2, weight=1)
        self.step_labels = {}
        for i, coin in enumerate(fr.COINS, start=1):
            lab(pb, coin, "num_b", width=5, anchor="w").grid(row=i, column=0, sticky="w", pady=3)
            for j, kind in enumerate(("sd", "bd"), start=1):
                key = f"{kind}_{coin}"
                var(key, str(c["progress"][coin]["sell_done" if kind == "sd" else "buy_done"]))
                cell = tk.Frame(pb, bg=T.PANEL)
                cell.grid(row=i, column=j)
                T.Btn(cell, "−", lambda k=key: self.step(k, -1)).pack(side="left")
                self.step_labels[key] = lab(cell, "", "num", width=5)
                self.step_labels[key].pack(side="left")
                T.Btn(cell, "+", lambda k=key: self.step(k, 1)).pack(side="left")
        k, kh = card(colf[2], "연결 · 실행")
        api = bool(self.engine.api)
        lab(kh, "업비트 API 연결됨" if api else "API 키 없음", "tag", fg=T.ACCENT if api else T.UP, padx=8, pady=2,
            highlightthickness=1, highlightbackground=T.ACCENT if api else T.UP).pack(side="right")
        kb = tk.Frame(k, bg=T.PANEL)
        kb.pack(fill="x", padx=16, pady=(0, 14))
        lab(kb, "UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY" if api else "setx로 키를 저장한 뒤 다시 실행하세요",
            "kr_xs", fg=T.MUTED).pack(anchor="w", pady=(0, 8))
        r1 = tk.Frame(kb, bg=T.PANEL)
        r1.pack(fill="x")
        T.Btn(r1, "바탕화면 바로가기 만들기", self.desktop_link).pack(side="left")
        T.Btn(r1, "PC 켤 때 자동 실행", self.startup_link).pack(side="left", padx=8)
        T.Btn(kb, "자동 실행 해제", self.remove_startup).pack(anchor="w", pady=(8, 0))

        self.settings_snapshot = self.settings_values()
        self.saved_at = time.strftime("%H:%M")
        self.update_dirty()

    def comma(self, key):
        try:
            v = num(self.sv[key].get())
            self.sv[key].set(f"{v:,.0f}")
        except ValueError:
            pass

    def step(self, key, d):
        v = max(0, min(3, int(self.sv[key].get() or 0) + d))
        self.sv[key].set(str(v))

    def toggle_sim(self, on):
        if on:  # 다시 켤 때는 확인 없이
            self.sim_var.set(True)
            self.update_dirty()
            return
        w, body = self.dialog("모의 모드를 끌까요?", "실전", T.UP)
        line = tk.Frame(body, bg=T.PANEL)
        line.pack(anchor="w")
        lab(line, "저장하면 승인한 주문이 ", "kr").pack(side="left")
        lab(line, "실제 업비트 계좌로", "kr_b", fg=T.UP).pack(side="left")
        lab(line, " 나갑니다.", "kr").pack(side="left")
        lab(body, "안전장치", "kr_xs", fg=T.MUTED).pack(anchor="w", pady=(12, 4))
        for k_, v_ in (("1건 최대 금액", self.sv["max_order_krw"].get() + "원"),
                       ("하루 최대 실주문", self.sv["max_orders_per_day"].get() + "건"),
                       ("수량 차이 허용", self.sv["volume_tol_pct"].get() + "%"),
                       ("운영 모드", "반자동 (승인해야 실행)" if self.mode_var.get() == "semi" else "알림만 (주문 안 함)")):
            r = tk.Frame(body, bg=T.PANEL)
            r.pack(fill="x", pady=1)
            lab(r, k_, "kr_s").pack(side="left")
            lab(r, v_, "num", fg=T.TEXT).pack(side="right", padx=(40, 0))
        if not self.engine.api:
            lab(body, "※ API 키가 없어 저장해도 모의로 동작합니다.", "kr_xs", fg=T.MUTED).pack(anchor="w", pady=(8, 0))

        def go():
            self.sim_var.set(False)
            self.update_dirty()
        self.dialog_buttons(w, "모의 유지", "실전으로 전환", go, danger=True)

    def settings_values(self):
        vals = {k: v.get().replace(",", "") for k, v in self.sv.items()}
        vals["mode"], vals["sim"] = self.mode_var.get(), str(self.sim_var.get())
        return vals

    def update_dirty(self):
        if not hasattr(self, "settings_snapshot") or not hasattr(self, "sim_toggle"):
            return
        sim = self.sim_var.get()
        self.sim_toggle.set(sim)
        self.sim_title.config(text="모의 모드 켜짐" if sim else "모의 모드 꺼짐 · 실전", fg=T.TEXT if sim else T.UP)
        self.sim_desc.config(text="승인해도 실제 주문은 나가지 않음 (처음엔 켜 두기)" if sim else "승인한 주문이 업비트 계좌로 나감")
        self.sim_box.config(highlightbackground=T.DIVIDER if sim else T.UP)
        try:  # 비중 환산 금액·막대·합계
            budget = num(self.sv["buy_budget"].get())
            split = {c: num(self.sv[f"split_{c}"].get()) for c in fr.COINS}
        except ValueError:
            budget, split = None, {}
        self.split_bar.delete("all")
        wbar = max(self.split_bar.winfo_width(), 300)
        x = 0
        for c, col in zip(fr.COINS, (T.ACCENT, T.ACCENT_HOVER, T.blend(T.ACCENT, T.PANEL, 0.6))):
            v = split.get(c)
            self.split_amt[c].config(text=f"{budget * v:,.0f}원" if budget and v == v and v is not None else "-")
            if v and v == v:
                self.split_bar.create_rectangle(x, 0, x + wbar * v - 2, 4, fill=col, outline="")
                x += wbar * v
        total = sum(v for v in split.values() if v == v) if split else float("nan")
        ok = total == total and abs(total - 1) <= 0.001
        self.split_sum.config(text=f"{total:.2f} 정상" if ok else f"{total:.2f} · 합계가 1이어야 저장됩니다" if total == total
                              else "숫자를 확인하세요", fg=T.TEXT if ok else T.UP)
        try:
            dca = sum(num(self.sv[f"dca_{c}"].get()) for c in fr.COINS)
            free = self.board.get("_krw_free")
            self.dca_sum.config(text=f"{dca:,.0f}원" + (f" · 현금 기준 약 {free / dca:,.0f}일분" if free and dca else ""))
        except ValueError:
            self.dca_sum.config(text="-")
        for k, l in self.step_labels.items():
            l.config(text=f"{self.sv[k].get()} / 3")
        now_vals = self.settings_values()
        n = sum(1 for k, v in now_vals.items() if self.settings_snapshot.get(k) != v)
        self.set_state.config(text=f"저장하지 않은 변경 {n}개" if n else f"모든 변경 저장됨 · {self.saved_at}",
                              fg=T.LINE_NOW if n else T.MUTED)

    def revert_settings(self):
        for k, v in self.settings_snapshot.items():
            if k in self.sv:
                cur = self.sv[k].get()
                if cur.replace(",", "") != v:
                    self.sv[k].set(f"{float(v):,.0f}" if k in ("buy_budget", "max_order_krw") or k.startswith("dca_") else v)
        self.mode_var.set(self.settings_snapshot["mode"])
        self.sim_var.set(self.settings_snapshot["sim"] == "True")
        self.update_dirty()

    def save_settings(self):
        c, sv = self.cfg, self.sv
        try:
            split = {coin: num(sv[f"split_{coin}"].get()) for coin in fr.COINS}
            if abs(sum(split.values()) - 1) > 0.001:
                messagebox.showerror("설정", f"코인 예산 비중 합이 {sum(split.values()):.2f}입니다. 합이 1이 되게 고친 뒤 저장하세요.")
                return
            new = {"buy_budget": int(num(sv["buy_budget"].get())), "buy_split": split,
                   "near_pct": num(sv["near_pct"].get()), "volume_tol_pct": num(sv["volume_tol_pct"].get()),
                   "every_sec": int(num(sv["every_sec"].get())), "max_order_krw": int(num(sv["max_order_krw"].get())),
                   "max_orders_per_day": int(num(sv["max_orders_per_day"].get())),
                   "dca_daily": {coin: int(num(sv[f"dca_{coin}"].get())) for coin in fr.COINS}}
            prog = {coin: {"sell_done": int(sv[f"sd_{coin}"].get()), "buy_done": int(sv[f"bd_{coin}"].get())} for coin in fr.COINS}
            nh = sv["near_hl"].get()
        except ValueError as e:
            messagebox.showerror("설정", f"숫자를 확인하세요: {e}")
            return
        if any(v != v for v in list(new.values()) if isinstance(v, float)):
            messagebox.showerror("설정", "빈 칸이 있습니다.")
            return
        mode = self.mode_var.get()
        if c.get("stopped") and mode != c["mode"]:
            c["stopped"]["mode"] = mode  # 정지 중이면 재개할 때 이 모드로
            mode = c["mode"]
        c.update(new, mode=mode, simulate=self.sim_var.get())
        c["progress"].update(prog)
        c["ui"]["near_highlight_pct"] = 0 if nh == "끔" else float(nh)
        core.save_config(c)
        self.engine.load_levels()
        self.saved_at = time.strftime("%H:%M")
        self.settings_snapshot = self.settings_values()
        self.update_dirty()
        self.refresh_chrome()
        self.stale.update({TAB_BOARD, TAB_ORDERS})
        self.show_notice("설정을 저장했습니다. 플랜과 다시 비교합니다.", 6)
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
        self.last_status_ts = time.time()
        api = "API 연결됨" if self.engine.api else "API 키 없음"
        self.status.config(text=f"{api} · {ts} 확인" if not err else text[:80], fg=T.UP if err else T.MUTED)
        self.status_dot.config(fg=T.UP if err or not self.engine.api else T.DOWN)
        self.refresh_chrome()

    def check_stale_status(self):
        """마지막 확인이 확인 간격의 2배 넘게 지나면 점과 글자를 UP 색으로."""
        if self.last_status_ts and time.time() - self.last_status_ts > 2 * max(self.cfg["every_sec"], 10) + 5:
            self.status_dot.config(fg=T.UP)
            self.status.config(fg=T.UP)

    def on_done(self, lines):
        self.drift_btn.config(text="레벨 변화 지금 확인")  # 확인 중 오류가 나도 버튼 원래대로
        text = "\n".join(lines)
        if self.executing:
            self.executing = False
            sim = self.cfg["simulate"] or not self.engine.api
            bad = [l for l in lines if "실패" in l or "건너뜀" in l or "불명확" in l or "않았습니다" in l]
            self.o_done_lab.config(text=f"{'[모의] ' if sim else ''}{time.strftime('%H:%M:%S')} 주문 실행 "
                                        f"{'완료' if not bad else '끝 · 일부 실패'} · 결과는 알림·기록 탭에 남았습니다",
                                   fg=T.TEXT if not bad else T.UP)
            if not self.o_done.winfo_ismapped():
                self.o_done.pack(fill="x", padx=18, pady=(0, 12), before=self.o_stats)
            if bad:
                self.popup("주문 실행 결과", text[:1500])
            self.update_order_sums()
        else:
            self.show_notice(lines[0] if len(lines) == 1 else f"{lines[0]} 외 {len(lines) - 1}건")

    def pump(self):
        if self.closing:
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
                if akind == "stop":
                    self.root.after(300, self.after_mode_change)
            elif kind == "live":
                if self.closing:
                    return
                self.render_strip(ev[1])
                self.render_board()
                if self.accounts:
                    self.render_invest()
                self.render_grid_tab()
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
                self.hist_table.empty = ["거래내역 조회 실패", ev[1][:80]]
                self.hist_table.set_rows([])
            elif kind == "open_orders":
                self.render_orders(ev[1])
            elif kind == "drift_report":
                self.show_drift_report(ev[1], ev[2])
            elif kind == "drift":
                self.render_drift(ev[1])
            elif kind == "dip_watch":
                self.dip_watch, self.dip_at = ev[1], ev[2]
                self.render_watch()
            elif kind == "grid":
                self.render_grid(ev[1])
                changed_logs = True  # 자동매매 거래 기록
            elif kind == "proposal":
                self.proposal = ev[1]
                self.prop_time = time.strftime("%H:%M:%S")
                self.render_proposal()
                self.render_board()
            elif kind == "done":
                self.on_done(ev[1])
                changed_logs = True
        if changed_logs:
            self.render_logs()
            self.render_grid_log()
            self.render_journal()
        self.check_stale_status()
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
