"""FibTrader 디자인 토큰·글꼴·스타일 (디자인 스펙 1장).

색은 스펙의 hex 그대로. 상승·매수 = UP(빨강), 하락·매도 = DOWN(파랑).
Barlow는 C:\\fib\\fonts 에 받아 둔 ttf를 이 프로세스에만 등록해서 쓴다(시스템 설치 불필요).
Barlow에는 한글이 없어서 한글 글자는 맑은 고딕, 숫자·영문은 Barlow로 나눠 쓴다.
"""
import glob
import os
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

GROUND = "#121C26"
PANEL = "#192634"
TEXT = "#F5F5F8"
MUTED = "#B7B7BA"
DIVIDER = "#384350"
DIVIDER_SOFT = "#222E3B"
ACCENT = "#5980A6"
ACCENT_HOVER = "#749DC4"
ACCENT_200 = "#D6EBFF"
UP = "#F0716A"
DOWN = "#94BCE3"
ROW_CURRENT = "#283C4F"
ROW_NEAR = "#203041"
ROW_SELECTED = "#233446"
BANNER_BG = "#1F2E3D"
LINE_NOW = "#B5D9FD"   # 차트 현재가·매수평균가 기준선
HOVER_7 = "#253240"    # TEXT 7%를 PANEL 위에 섞은 색 (보조 버튼 hover)
TRACK_10 = "#2F3A47"   # TEXT 10%를 PANEL 위에 섞은 색 (비중 막대 트랙)

HERE = os.path.dirname(os.path.abspath(__file__))
F = {}  # 역할 → (family, size, weight) 튜플. setup_fonts() 뒤에 채워진다


def load_private_fonts():
    """fonts 폴더의 ttf를 이 프로세스 전용으로 등록 (윈도우). tk.Tk() 만들기 전에 불러야 한다."""
    if sys.platform != "win32":
        return
    import ctypes
    for path in glob.glob(os.path.join(HERE, "fonts", "*.ttf")):
        ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)  # FR_PRIVATE


def setup_fonts(root):
    fams = set(tkfont.families(root))
    kr = next((f for f in ("맑은 고딕", "Malgun Gothic", "NanumGothic", "Noto Sans CJK KR") if f in fams), "TkDefaultFont")
    cond = next((f for f in ("Barlow Condensed SemiBold", "Barlow Condensed") if f in fams), None)
    num = "Barlow" if "Barlow" in fams else next((f for f in ("Consolas", "Segoe UI", "DejaVu Sans Mono") if f in fams), kr)
    cond_w = "bold" if cond == "Barlow Condensed" else "normal"
    cf = cond or num
    # 음수 크기 = 픽셀 (스펙이 px 기준)
    F.update({
        "kr": (kr, -13), "kr_b": (kr, -13, "bold"), "kr_s": (kr, -12), "kr_xs": (kr, -11), "kr_btn": (kr, -13, "bold"),
        "kr_title": (kr, -16, "bold"), "kr_big": (kr, -20, "bold"),
        "num": (num, -13), "num_b": (num, -13, "bold"), "num_cell": (num, -15), "num_cell_b": (num, -15, "bold"),
        "num_s": (num, -12), "num_xs": (num, -11),
        "brand": (cf, -18, cond_w), "sym": (cf, -20, cond_w), "price": (cf, -42, cond_w), "chg": (cf, -20, cond_w),
        "sum_val": (cf, -19, cond_w), "sum_val_l": (cf, -30, cond_w), "panel_t": (cf, -17, cond_w),
        "ghost": (cf, -13, cond_w), "tag": (num, -11, "bold"),
    })
    return F


def apply_ttk(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=GROUND, foreground=TEXT, fieldbackground=PANEL, bordercolor=DIVIDER,
                lightcolor=PANEL, darkcolor=PANEL, troughcolor=GROUND, font=F["kr"], focuscolor=ACCENT)
    s.configure("TFrame", background=GROUND)
    s.configure("Panel.TFrame", background=PANEL)
    s.configure("TLabel", background=GROUND, foreground=TEXT)
    s.configure("Muted.TLabel", background=GROUND, foreground=MUTED, font=F["kr_s"])
    s.configure("Title.TLabel", background=GROUND, foreground=TEXT, font=F["kr_title"])
    for w in ("TCheckbutton", "TRadiobutton"):  # 켜짐 = ACCENT 채움 + 어두운 체크, 꺼짐 = 빈 칸
        s.configure(w, background=GROUND, foreground=TEXT, indicatorbackground=PANEL, indicatorforeground=PANEL,
                    upperbordercolor=MUTED, lowerbordercolor=MUTED, indicatormargin=(0, 0, 6, 0))
        s.map(w, indicatorbackground=[("selected", ACCENT)], indicatorforeground=[("selected", GROUND)],
              background=[("active", GROUND)])
    s.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, insertcolor=TEXT, bordercolor=DIVIDER)
    s.configure("TCombobox", fieldbackground=PANEL, foreground=TEXT, background=PANEL, arrowcolor=TEXT)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", TEXT)])
    s.configure("TButton", background=PANEL, foreground=TEXT, bordercolor=DIVIDER, relief="flat", padding=(12, 5),
                font=F["kr_btn"])
    s.map("TButton", background=[("active", HOVER_7), ("disabled", GROUND)], foreground=[("disabled", MUTED)])
    s.configure("Accent.TButton", background=ACCENT, foreground=GROUND, bordercolor=ACCENT)
    s.map("Accent.TButton", background=[("active", ACCENT_HOVER)])
    s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, bordercolor=DIVIDER,
                rowheight=30, font=F["kr"])
    s.map("Treeview", background=[("selected", ROW_SELECTED)], foreground=[("selected", TEXT)])
    s.configure("Treeview.Heading", background=PANEL, foreground=MUTED, bordercolor=DIVIDER, relief="flat",
                font=F["kr_xs"])
    s.map("Treeview.Heading", background=[("active", PANEL)])
    s.configure("Tall.Treeview", rowheight=38)
    s.configure("Vertical.TScrollbar", background=PANEL, troughcolor=GROUND, bordercolor=GROUND, arrowcolor=MUTED)
    s.configure("TLabelframe", background=GROUND, bordercolor=DIVIDER)
    s.configure("TLabelframe.Label", background=GROUND, foreground=MUTED)
    root.configure(bg=GROUND)
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    return s


class Btn(tk.Label):
    """스펙 버튼: primary(ACCENT 채움) / secondary(테두리) / danger(UP 테두리) / ghost(글자만). 모서리 각짐."""

    def __init__(self, parent, text, command, kind="secondary", bg=PANEL, **kw):
        self.kind, self.command, self.base_bg = kind, command, bg
        colors = {"primary": (ACCENT, GROUND, ACCENT), "secondary": (bg, TEXT, DIVIDER),
                  "danger": (bg, UP, UP), "ghost": (bg, ACCENT, bg)}[kind]
        self.normal_bg = colors[0]
        super().__init__(parent, text=text, bg=colors[0], fg=colors[1], cursor="hand2",
                         font=F["ghost"] if kind == "ghost" else F["kr_btn"],
                         padx=12 if kind != "ghost" else 4, pady=5 if kind != "ghost" else 2,
                         highlightthickness=0 if kind == "ghost" else 1, highlightbackground=colors[2],
                         highlightcolor=ACCENT, takefocus=1, **kw)
        self.bind("<Button-1>", lambda e: self.command and self.command())
        self.bind("<Return>", lambda e: self.command and self.command())
        self.bind("<Enter>", self._hover)
        self.bind("<Leave>", lambda e: self.config(bg=self.normal_bg))

    def _hover(self, _e):
        self.config(bg={"primary": ACCENT_HOVER, "ghost": self.normal_bg}.get(self.kind, HOVER_7))


def fmtp(v):
    """가격 표시. 지수 표기 없이, 가격대에 맞는 소수 자리 (1,000 이상은 정수)."""
    if v is None:
        return "-"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    d = 1 if a >= 100 else 2 if a >= 10 else 3 if a >= 1 else 6
    s = f"{v:,.{d}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def fmtk(v, sign=False):
    """원화 금액 (천 단위 콤마, 정수)."""
    return "-" if v is None else (f"{v:+,.0f}" if sign else f"{v:,.0f}")


def fmtq(v):
    """수량: 원본 소수 자리 (최대 8자리, 끝의 0 제거)."""
    s = f"{v:.8f}".rstrip("0").rstrip(".")
    return s or "0"


def chg_color(v):
    return UP if v > 0 else DOWN if v < 0 else TEXT


def arrow(v):
    return "▲" if v > 0 else "▼" if v < 0 else ""


def blend(fg, bg, a):
    """fg를 bg 위에 투명도 a로 겹친 색 (윈도우 Tk는 반투명을 못 그려서 미리 섞는다)."""
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * a + y * (1 - a)):02X}" for x, y in zip(f, b))
