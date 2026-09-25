"""FibTrader 화면 부품: 상단 탭바, 시세 티커, 레벨 사다리 표, 캔들 차트, 요약 칸.

모두 tk.Canvas/Frame으로 그린다. 가격이 바뀌면 텍스트만 다시 그리고 위젯은 새로 만들지 않는다.
"""
import math
import tkinter as tk
import tkinter.font as tkfont

import fibtrader_theme as T


class Tabs(tk.Frame):
    """상단바 안에 들어가는 탭 + 본문 전환. ttk.Notebook 대신 (탭을 상단바 한 줄에 넣기 위해).
    탭 옆 배지(숫자)는 set_badge로. 0이면 숨긴다."""

    def __init__(self, parent, bar):
        super().__init__(parent, bg=T.GROUND)
        self.bar, self.pages, self.labels, self.badges, self.current = bar, [], [], [], None
        self.on_change = None

    def add(self, frame, text):
        idx = len(self.pages)
        holder = tk.Frame(self.bar, bg=T.PANEL, cursor="hand2")
        holder.pack(side="left", fill="y")
        line = tk.Frame(holder, bg=T.PANEL, height=2)
        line.pack(fill="x", side="bottom")
        inner = tk.Frame(holder, bg=T.PANEL)
        inner.pack(fill="both", expand=True, padx=16)
        lab = tk.Label(inner, text=text.strip(), bg=T.PANEL, fg=T.MUTED, font=T.F["kr_tab"])
        lab.pack(side="left", ipady=9)
        badge = tk.Label(inner, text="", bg=T.DOWN, fg=T.GROUND, font=T.F["tag"], width=2)
        for w in (holder, inner, lab, badge):
            w.bind("<Button-1>", lambda e: self.select(idx))
        self.pages.append(frame)
        self.labels.append((lab, line))
        self.badges.append(badge)
        if self.current is None:
            self.select(0)

    def set_badge(self, idx, n, bg=T.DOWN):
        b = self.badges[idx]
        if n:
            b.config(text=str(n) if n < 100 else "99+", bg=bg, width=2 if n < 10 else 3)
            if not b.winfo_ismapped():
                b.pack(side="left", padx=(6, 0))
        elif b.winfo_ismapped():
            b.pack_forget()

    def select(self, which):
        idx = which if isinstance(which, int) else self.pages.index(which)
        for i, (page, (lab, line)) in enumerate(zip(self.pages, self.labels)):
            on = i == idx
            lab.config(fg=T.TEXT if on else T.MUTED)
            line.config(bg=T.ACCENT if on else T.PANEL)
            if on:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        self.current = idx
        if self.on_change:
            self.on_change(idx)

    def index(self):
        return self.current


class Ticker(tk.Canvas):
    """시세 티커: 그룹(피보나치 | 자동매매 | 보유)별로 한 줄, 폭이 모자라면 다음 줄로 넘긴다."""
    LINE = 34

    def __init__(self, parent):
        super().__init__(parent, bg=T.GROUND, height=self.LINE, highlightthickness=0)
        self.groups, self.prev, self.flash, self.fonts, self.unflash, self.widths = [], {}, {}, None, None, {}
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, groups):
        """groups: [(그룹 이름, [(코인, 가격, 등락률%)])]"""
        for _, items in groups:
            for coin, price, _ in items:
                old = self.prev.get(coin)
                if old is not None and price != old:
                    self.flash[coin] = (T.UP if price > old else T.DOWN)
                self.prev[coin] = price
        if self.flash and not self.unflash:  # 바뀐 코인이 여럿이어도 깜빡임 끄기는 한 번만 다시 그림
            self.unflash = self.after(500, self._clear_flash)
        self.groups = groups
        self.draw()

    def _clear_flash(self):
        self.flash.clear()
        self.unflash = None
        self.draw()

    def draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 200)
        if self.fonts is None:  # 글꼴 객체는 한 번만 만든다 (매번 만들면 윈도우에서 느림)
            self.fonts = tuple(tkfont.Font(font=T.F[k]) for k in ("kr_xs", "num_b", "num"))
        fonts, cache = self.fonts, self.widths

        def mw(fi, txt):  # 글자 폭 재기는 느려서(Tk 호출) 같은 글자는 한 번만 잰다
            k = (fi, txt)
            if k not in cache:
                if len(cache) > 2000:
                    cache.clear()
                cache[k] = fonts[fi].measure(txt)
            return cache[k]

        x, y, line = 18, self.LINE / 2, 0
        for gi, (gname, items) in enumerate(self.groups):
            if not items:
                continue
            if gi and x > 18:
                if x + 40 > w:
                    x, line = 18, line + 1
                else:
                    self.create_line(x + 4, y - 9 + line * self.LINE, x + 4, y + 9 + line * self.LINE, fill=T.DIVIDER)
                    x += 18
            self.create_text(x, y + line * self.LINE, text=gname, fill=T.MUTED, font=T.F["kr_xs"], anchor="w")
            x += mw(0, gname) + 10
            for i, (coin, price, ch) in enumerate(items):
                ptxt, ctxt = T.fmtp(price), f"{T.arrow(ch)}{abs(ch):.2f}%"
                width = mw(1, coin) + 6 + mw(2, ptxt) + 6 + mw(2, ctxt) + 18
                if x + width > w - 10 and x > 120:
                    x, line = 18 + mw(0, gname) + 10, line + 1
                cy = y + line * self.LINE
                if coin in self.flash:
                    self.create_rectangle(x - 4, cy - 12, x + width - 12, cy + 12,
                                          fill=T.blend(self.flash[coin], T.GROUND, 0.25), outline="")
                self.create_text(x, cy, text=coin, fill=T.TEXT, font=T.F["num_b"], anchor="w")
                x += mw(1, coin) + 6
                self.create_text(x, cy, text=ptxt, fill=T.TEXT, font=T.F["num"], anchor="w")
                x += mw(2, ptxt) + 6
                self.create_text(x, cy, text=ctxt, fill=T.chg_color(ch), font=T.F["num"], anchor="w")
                x += mw(2, ctxt) + 8
                if i < len(items) - 1:
                    self.create_text(x, cy, text="|", fill=T.DIVIDER, font=T.F["num"], anchor="w")
                    x += 10
        h = (line + 1) * self.LINE
        if int(self.cget("height")) != h:
            self.config(height=h)


class Ladder(tk.Canvas):
    """레벨 사다리 + 예약 주문을 합친 표 (스펙 1a). 행: dict(kind, name, sub, price, pct, qty, amt, uuid, color, near, bold)."""
    HEAD = 24

    def __init__(self, parent, bg=T.PANEL):
        super().__init__(parent, bg=bg, highlightthickness=0, height=self.HEAD + 8 * 40)
        self.rows, self.checked, self.rh = [], set(), 40
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self.click)

    def set_rows(self, rows, rh=None):
        if rows == self.rows and (not rh or rh == self.rh):
            return  # 내용이 그대로면 다시 그리지 않는다 (2초마다 같은 표를 새로 그리던 부분)
        self.rows = rows
        if rh:
            self.rh = rh
        live = {r["uuid"] for r in rows if r.get("uuid")}
        self.checked &= live  # 사라진 주문은 선택 해제
        h = self.HEAD + len(rows) * self.rh
        if int(self.cget("height")) != h:
            self.config(height=h)
        self.draw()

    _num = None

    @classmethod
    def num_font(cls):
        if cls._num is None:
            cls._num = tkfont.Font(font=T.F["num"])
        return cls._num

    def cols(self, w):
        fixed = {"chk": 18, "name": 78, "pct": 96, "qty": 86, "amt": 76}
        if w < 450:  # 카드가 좁으면 열을 조금씩 줄이고
            fixed.update(name=72, pct=84, qty=78, amt=70)
        if w < 400:  # 더 좁으면(1280px 창 등) 수량 칸을 빼고 금액만
            fixed["qty"] = 0
        price = w - sum(fixed.values())
        if price < 96:  # 좁으면 수량·금액을 줄인다
            cut = 96 - price
            fixed["qty"] -= cut * 0.5
            fixed["amt"] -= cut * 0.5
            price = 96
        xs, x = {}, 0
        for k, cw in (("chk", fixed["chk"]), ("name", fixed["name"]), ("price", price), ("pct", fixed["pct"]),
                      ("qty", fixed["qty"]), ("amt", fixed["amt"])):
            xs[k] = (x, x + cw)
            x += cw
        return xs

    def draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 300)
        xs = self.cols(w)
        for k, t in (("name", "구분"), ("price", "가격"), ("pct", "현재가 대비"), ("qty", "수량"), ("amt", "금액")):
            x0, x1 = xs[k]
            if x1 - x0 < 10:
                continue
            self.create_text(x1 - 4 if k != "name" else x0 + 2, self.HEAD / 2, text=t, fill=T.MUTED,
                             font=T.F["kr_xs"], anchor="e" if k != "name" else "w")
        self.create_line(0, self.HEAD - 1, w, self.HEAD - 1, fill=T.DIVIDER)
        rh = self.eff_rh()
        two = rh >= 36
        for i, r in enumerate(self.rows):
            y0 = self.HEAD + i * rh
            ym = y0 + rh / 2
            bg = T.ROW_CURRENT if r["kind"] == "now" else T.ROW_SELECTED if r.get("uuid") in self.checked \
                else T.ROW_NEAR if r.get("near") else None
            if bg:
                self.create_rectangle(0, y0, w, y0 + rh, fill=bg, outline="")
            self.create_line(0, y0 + rh - 1, w, y0 + rh - 1, fill=T.DIVIDER_SOFT)
            if r.get("uuid"):  # 주문 행 체크박스
                cx = xs["chk"][0] + 9
                on = r["uuid"] in self.checked
                self.create_rectangle(cx - 6, ym - 6, cx + 6, ym + 6, outline=T.ACCENT if on else T.MUTED,
                                      fill=T.ACCENT if on else "")
                if on:
                    self.create_line(cx - 3, ym, cx - 1, ym + 3, cx + 4, ym - 3, fill=T.GROUND, width=2)
            color = r.get("color", T.TEXT)
            nx = xs["name"][0] + 2
            name_font = T.F["kr_b"] if r.get("bold") else T.F["kr"]
            if two and r.get("sub"):
                self.create_text(nx, ym - 8, text=r["name"], fill=color, font=name_font, anchor="w")
                self.create_text(nx, ym + 9, text=r["sub"], fill=T.MUTED, font=T.F["kr_xs"], anchor="w")
            else:  # 한 줄 모드: 가격 칸과 겹치지 않게 이름만
                self.create_text(nx, ym, text=r["name"], fill=color, font=name_font, anchor="w")
            self.create_text(xs["price"][1] - 4, ym, text=T.fmtp(r["price"]), fill=color if r["kind"] != "now" else T.TEXT,
                             font=T.F["num_cell_b"] if r.get("bold") else T.F["num_cell"], anchor="e")
            if r.get("pct") is not None:
                pct = r["pct"]
                x1 = xs["pct"][1] - 4
                txt = f"{pct:+.1f}%"
                tw = self.num_font().measure(txt)
                self.create_text(x1, ym, text=txt, fill=color, font=T.F["num"], anchor="e")
                bx1 = x1 - tw - 6
                blen = max(0, min(40, abs(pct) * 1.5, bx1 - xs["pct"][0] - 4))  # 칸 밖(가격)으로 넘지 않게
                bar = T.blend(color, bg or T.PANEL, 0.6) if color.startswith("#") else color
                self.create_rectangle(bx1 - blen, ym - 1.5, bx1, ym + 1.5, fill=bar, outline="")
            if r.get("qty") is not None and xs["qty"][1] - xs["qty"][0] > 10:
                self.create_text(xs["qty"][1] - 4, ym, text=T.fmtq(r["qty"]), fill=T.MUTED if not r.get("uuid") else T.TEXT,
                                 font=T.F["num_s"], anchor="e")
            if r.get("amt") is not None:
                self.create_text(xs["amt"][1] - 4, ym, text=T.fmtk(r["amt"]), fill=T.MUTED if not r.get("uuid") else T.TEXT,
                                 font=T.F["num_s"], anchor="e")

    def eff_rh(self):
        """남은 높이에 맞춘 실제 행 높이 (창이 작으면 줄여서 마지막 행까지 보이게, 최소 24)."""
        h = self.winfo_height()
        if h <= 1 or not self.rows:
            return self.rh
        return max(24, min(self.rh, (h - self.HEAD) / len(self.rows)))

    def click(self, e):
        i = int((e.y - self.HEAD) // self.eff_rh())
        if 0 <= i < len(self.rows) and self.rows[i].get("uuid"):
            u = self.rows[i]["uuid"]
            self.checked.symmetric_difference_update({u})
            self.draw()


class Candles(tk.Canvas):
    """캔들 차트 (업비트 비슷하게): 오른쪽 가격 눈금, 아래 시간, 거래대금 막대, 현재가 태그,
    마우스를 올리면 십자선 + 그 봉의 시가·고가·저가·종가·등락률. 양봉 UP, 음봉 DOWN."""
    AXIS_W, TIME_H = 86, 18

    def __init__(self, parent, height=150):
        super().__init__(parent, bg=T.GROUND, height=height, highlightthickness=1, highlightbackground=T.DIVIDER,
                         cursor="crosshair")
        self.data, self.lines, self.unit, self.geom = [], [], "", None
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Motion>", self.hover)
        self.bind("<Leave>", lambda e: self.delete("xh"))

    def set(self, candles, lines, unit):
        """candles: [(시가, 고가, 저가, 종가[, 시각, 거래대금])] 오래된 것부터. lines: [(라벨, 가격, 색, 실선여부)]"""
        self.data, self.lines, self.unit = candles, lines, unit
        self.draw()

    @staticmethod
    def nice_step(span, n=5):
        raw = span / max(n, 1)
        mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
        for m in (1, 2, 2.5, 5, 10):
            if raw <= m * mag:
                return m * mag
        return 10 * mag

    def tag(self, x, y, text, bg, fg=T.GROUND, anchor="w", font="num_xs", tags=()):
        tid = self.create_text(x + (4 if anchor == "w" else -4), y, text=text, fill=fg, font=T.F[font], anchor=anchor, tags=tags)
        x0, y0, x1, y1 = self.bbox(tid)
        rid = self.create_rectangle(x0 - 4, y0 - 1, x1 + 4, y1 + 1, fill=bg, outline="", tags=tags)
        self.tag_raise(tid, rid)

    def draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 160), max(self.winfo_height(), 80)
        if not self.data:
            self.create_text(w / 2, h / 2, text="불러오는 중…", fill=T.MUTED, font=T.F["kr_xs"])
            return
        px1 = w - self.AXIS_W  # 그림 영역 오른쪽 끝 (그 오른쪽은 가격 눈금)
        top, bot = 8, h - self.TIME_H - 2
        has_vol = len(self.data[0]) >= 6 and any(c[5] for c in self.data)
        vol_h = (bot - top) * 0.16 if has_vol else 0
        pbot = bot - vol_h - (4 if has_vol else 0)
        vals = [c[1] for c in self.data] + [c[2] for c in self.data] + [p for _, p, _, _ in self.lines if p]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.08 or hi * 0.01
        lo, hi = lo - pad, hi + pad
        y = lambda v: top + (hi - v) / (hi - lo) * (pbot - top)  # noqa: E731
        n = len(self.data)
        slot = (px1 - 8) / n
        self.geom = (4, slot, top, pbot, lo, hi, px1, bot)
        # 가격 눈금 (가로 보조선은 아주 옅게)
        step = self.nice_step(hi - lo)
        v = math.ceil(lo / step) * step
        grid = T.blend(T.TEXT, T.GROUND, 0.06)
        while v <= hi:
            yy = y(v)
            self.create_line(0, yy, px1, yy, fill=grid)
            self.create_text(px1 + 6, yy, text=T.fmtp(v), fill=T.MUTED, font=T.F["num_xs"], anchor="w")
            v += step
        self.create_line(px1, 0, px1, h, fill=T.DIVIDER)
        self.create_line(0, bot, w, bot, fill=T.DIVIDER)
        # 거래대금 막대
        if has_vol:
            vmax = max(c[5] for c in self.data) or 1
            for i, c in enumerate(self.data):
                cx = 4 + slot * (i + 0.5)
                bh = c[5] / vmax * vol_h
                col = T.blend(T.UP if c[3] >= c[0] else T.DOWN, T.GROUND, 0.35)
                self.create_rectangle(cx - max(slot * 0.32, 0.5), bot - bh, cx + max(slot * 0.32, 0.5), bot, fill=col, outline="")
        # 캔들
        for i, c in enumerate(self.data):
            o, hh, ll, cl = c[:4]
            cx = 4 + slot * (i + 0.5)
            col = T.UP if cl >= o else T.DOWN
            self.create_line(cx, y(hh), cx, y(ll), fill=col)
            bw = max(slot * 0.64, 1)
            y0, y1 = sorted((y(o), y(cl)))
            self.create_rectangle(cx - bw / 2, y0, cx + bw / 2, max(y1, y0 + 1), fill=col, outline=col)
        # 시간 눈금
        if len(self.data[0]) >= 5 and self.data[0][4]:
            k = max(1, round(n / 5))
            for i in range(k // 2, n, k):  # 양 끝은 잘리지 않게 안쪽부터
                t = self.data[i][4]
                txt = t[5:10] if self.unit.startswith("1일") else f"{t[5:10]} {t[11:13]}시"
                self.create_text(4 + slot * (i + 0.5), bot + self.TIME_H / 2 + 1, text=txt, fill=T.MUTED, font=T.F["num_xs"])
        # 기준선 (레벨·평단·현재가): 점선 + 오른쪽 눈금에 색 태그
        for label, price, color, solid in self.lines:
            if not price or not lo <= price <= hi:
                continue
            ly = y(price)
            self.create_line(0, ly, px1, ly, fill=color, dash=() if solid else (2, 3))
            tid = self.create_text(6, ly - 2, text=label, fill=color, font=T.F["kr_xs"], anchor="sw")
            x0, y0, x1, y1 = self.bbox(tid)
            rid = self.create_rectangle(x0 - 2, y0, x1 + 2, y1, fill=T.GROUND, outline="")
            self.tag_raise(tid, rid)
            self.tag(px1, ly, T.fmtp(price), color, fg=T.GROUND)
        self.create_text(w - 6, h - 3, text=self.unit, fill=T.MUTED, font=T.F["num_xs"], anchor="se")

    def hover(self, e):
        """십자선 + 가격 태그 + 그 봉 정보 (업비트처럼)."""
        self.delete("xh")
        if not self.data or not self.geom:
            return
        x0, slot, top, pbot, lo, hi, px1, bot = self.geom
        if e.x > px1 or e.y > bot:
            return
        i = min(len(self.data) - 1, max(0, int((e.x - x0) / slot)))
        c = self.data[i]
        cx = x0 + slot * (i + 0.5)
        col = T.blend(T.TEXT, T.GROUND, 0.5)
        self.create_line(cx, 0, cx, bot, fill=col, dash=(2, 2), tags="xh")
        self.create_line(0, e.y, px1, e.y, fill=col, dash=(2, 2), tags="xh")
        if top <= e.y <= pbot:
            price = hi - (e.y - top) / (pbot - top) * (hi - lo)
            self.tag(px1, e.y, T.fmtp(price), T.TEXT, fg=T.GROUND, tags="xh")
        if len(c) >= 5 and c[4]:
            t = c[4].replace("T", " ")
            self.tag(cx, bot + self.TIME_H / 2 + 1, t[5:16], T.TEXT, fg=T.GROUND, anchor="w", tags="xh")
        o, hh, ll, cl = c[:4]
        prev = self.data[i - 1][3] if i else o
        chg = (cl / prev - 1) * 100 if prev else 0
        colr = T.chg_color(chg)
        parts = [("시", o), ("고", hh), ("저", ll), ("종", cl)]
        x = 8
        yy = 12
        bg = self.create_rectangle(0, 0, 0, 0, fill=T.GROUND, outline="", tags="xh")
        first = x
        for name, v in parts:
            tid = self.create_text(x, yy, text=name, fill=T.MUTED, font=T.F["kr_xs"], anchor="w", tags="xh")
            x = self.bbox(tid)[2] + 3
            tid = self.create_text(x, yy, text=T.fmtp(v), fill=colr, font=T.F["num_s"], anchor="w", tags="xh")
            x = self.bbox(tid)[2] + 10
        tid = self.create_text(x, yy, text=f"{chg:+.2f}%", fill=colr, font=T.F["num_s"], anchor="w", tags="xh")
        x = self.bbox(tid)[2]
        if len(c) >= 6 and c[5]:
            tid = self.create_text(x + 10, yy, text=f"거래대금 {c[5] / 1e8:,.1f}억", fill=T.MUTED, font=T.F["kr_xs"], anchor="w", tags="xh")
            x = self.bbox(tid)[2]
        self.coords(bg, first - 4, yy - 9, x + 4, yy + 9)


class SummaryBar(tk.Frame):
    """하단 요약바 / 투자내역 요약 칸: 라벨(작게, MUTED) + 값(Condensed). 칸 사이 1px 세로선."""

    def __init__(self, parent, cells, big=False, height=60):
        super().__init__(parent, bg=T.PANEL, height=height, highlightthickness=1, highlightbackground=T.DIVIDER)
        self.vals = {}
        for i, (key, label) in enumerate(cells):
            if i:
                tk.Frame(self, bg=T.DIVIDER, width=1).pack(side="left", fill="y", pady=8)
            cell = tk.Frame(self, bg=T.PANEL)
            cell.pack(side="left", padx=16, pady=6)
            lab = tk.Label(cell, text=label, bg=T.PANEL, fg=T.MUTED, font=T.F["kr_xs"], anchor="w")
            lab.pack(anchor="w")
            row = tk.Frame(cell, bg=T.PANEL)
            row.pack(anchor="w")
            val = tk.Label(row, text="-", bg=T.PANEL, fg=T.TEXT, font=T.F["sum_val_l" if big else "sum_val"], anchor="w")
            val.pack(side="left")
            unit = tk.Label(row, text="", bg=T.PANEL, fg=T.MUTED, font=T.F["kr_s"], anchor="sw")
            unit.pack(side="left", padx=(2, 0), anchor="s", pady=(0, 3))
            self.vals[key] = (val, unit, lab)

    def set(self, key, text, unit="", color=T.TEXT, label=None):
        val, u, lab = self.vals[key]
        val.config(text=text, fg=color)
        u.config(text=unit)
        if label is not None:
            lab.config(text=label)


def _txt(c, x, y, text, fg, font, anchor):
    return c.create_text(x, y, text=text, fill=fg, font=T.F[font], anchor=anchor)


def draw_check(c, x, y, state):
    """12~14px 체크박스. state: True(켜짐 ACCENT 채움 + ✓) / False(빈 칸) / "some"(일부, –)."""
    s = 13
    x0, y0 = x, y - s / 2
    if state:
        c.create_rectangle(x0, y0, x0 + s, y0 + s, fill=T.ACCENT, outline=T.ACCENT)
        if state == "some":
            c.create_line(x0 + 3, y, x0 + s - 3, y, fill=T.GROUND, width=2)
        else:
            c.create_line(x0 + 3, y, x0 + 5.5, y + 3, x0 + s - 3, y - 3.5, fill=T.GROUND, width=2)
    else:
        c.create_rectangle(x0, y0, x0 + s, y0 + s, outline=T.MUTED)


def draw_tag(c, x, y, text, color, anchor="w", dash=False, fill="", fg=None, font="kr_xs"):
    """1px 테두리 태그. x는 anchor 기준 (w: 왼쪽, e: 오른쪽, center: 가운데)."""
    tw = T.measure(font, text) + 12
    x0 = x if anchor == "w" else x - tw if anchor == "e" else x - tw / 2
    c.create_rectangle(x0, y - 9, x0 + tw, y + 9, outline=color, fill=fill, dash=(2, 2) if dash else ())
    c.create_text(x0 + tw / 2, y, text=text, fill=fg or color, font=T.F[font])
    return tw


class Table(tk.Canvas):
    """캔버스 표 (Treeview 대신: 칸별 색·태그·체크박스·두 줄 칸·그룹 행·막대를 그릴 수 있다).

    cols: [{"key", "title", "w", "anchor"("w"/"e"/"center"), "grow"(남는 폭 비율)}]
    row: {"id", "cells": {key: 글자 | {"text","fg","font","sub","subfg","tag":(글자,색,점선),"draw":fn(c,x0,x1,y)}},
          "check": 체크 가능 여부, "dim": 흐리게(60%), "bg": 배경, "group": 그룹 제목(그룹 행), "right": 그룹 오른쪽 글자,
          "dash": 점선 테두리}
    fit=True면 행 수에 맞춰 높이를 바꾸고, 아니면 안에서 휠로 스크롤한다 (보이는 행만 그림).
    """
    HEAD = 32

    def __init__(self, parent, cols, rh=38, bg=T.PANEL, check=False, fit=False, empty=None, on_click=None,
                 on_check=None, selectable=False, min_rows=3, pad=16, head=True):
        super().__init__(parent, bg=bg, highlightthickness=0, height=self.HEAD + rh * min_rows)
        self.cols, self.rh, self.bgc, self.check, self.fit = cols, rh, bg, check, fit
        self.empty, self.on_click, self.on_check, self.selectable = empty, on_click, on_check, selectable
        self.min_rows, self.pad, self.head = min_rows, pad, head
        self.rows, self.checked, self.selected, self.offset = [], set(), None, 0
        self.btn_hits, self._xs = [], {}
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self.click)

    # ---- 데이터 ----
    def set_rows(self, rows):
        ids = {r.get("id") for r in rows if r.get("check")}
        self.checked &= ids
        if rows == self.rows and rows:
            return
        self.rows = rows
        if self.fit:
            h = self.content_h()
            if int(self.cget("height")) != h:
                self.config(height=h)
        self.draw()

    def row_h(self, r):
        if r.get("group") is not None:
            return 34
        if r.get("wrap") and self._xs:  # 펼친 행: 내용 줄 수만큼 높게
            x0, x1 = self._xs[r["wrap"]]
            width = max(x1 - x0 - 8, 40)
            v = r["cells"][r["wrap"]]
            text = v["text"] if isinstance(v, dict) else str(v)
            lines = sum(max(1, -(-T.measure("kr", part) // int(width))) for part in text.split("\n"))
            return max(self.rh, 14 + lines * 19 + (40 if r.get("button") else 0))
        return r.get("h", self.rh)

    def head_h(self):
        return self.HEAD if self.head else 0

    def content_h(self):
        body = sum(self.row_h(r) for r in self.rows) if self.rows else (110 if self.empty else self.rh)
        return self.head_h() + body + 1

    def checkable(self):
        return [r["id"] for r in self.rows if r.get("check")]

    def set_all(self, on):
        self.checked = set(self.checkable()) if on else set()
        self.draw()
        if self.on_check:
            self.on_check()

    # ---- 배치 ----
    def xs(self, w):
        fixed = sum(c["w"] for c in self.cols)
        grow = sum(c.get("grow", 0) for c in self.cols) or 1
        extra = max(0, w - 2 * self.pad - fixed)
        out, x = {}, self.pad
        for c in self.cols:
            cw = c["w"] + extra * c.get("grow", 0) / grow
            out[c["key"]] = (x, x + cw)
            x += cw
        return out

    def draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 40)
        xs = self._xs = self.xs(w)
        self.btn_hits = []
        if self.fit:  # 펼친 행 높이가 폭에 따라 바뀌므로 그릴 때마다 맞춘다
            need = self.content_h()
            if int(self.cget("height")) != need:
                self.config(height=need)
        hh = self.head_h()
        total = sum(self.row_h(r) for r in self.rows)
        self.offset = max(0, min(self.offset, total - (h - hh)))
        y = hh - self.offset
        for r in self.rows:
            rh = self.row_h(r)
            if y + rh >= hh and y < h:
                self.draw_row(r, xs, y, rh, w)
            y += rh
        if not self.rows and self.empty:
            lines = self.empty if isinstance(self.empty, (list, tuple)) else [self.empty]
            y0 = hh + 40 if self.fit else hh + (h - hh) / 2 - 20  # 스크롤 표는 가운데에
            for i, line in enumerate(lines):
                _txt(self, w / 2, y0 + i * 22, line, T.MUTED if i else T.TEXT, "kr" if i == 0 else "kr_s", "center")
        if self.head:
            self.create_rectangle(0, 0, w, hh, fill=self.bgc, outline="")
            for c in self.cols:
                x0, x1 = xs[c["key"]]
                if c["key"] == "chk" and self.check:
                    ids = self.checkable()
                    n = len(self.checked & set(ids))
                    draw_check(self, x0, hh / 2, bool(ids) and (True if n == len(ids) else "some" if n else False))
                    continue
                a = c.get("anchor", "w")
                x = x0 + 4 if a == "w" else x1 - 4 if a == "e" else (x0 + x1) / 2
                _txt(self, x, hh / 2, c.get("title", ""), T.MUTED, "kr_xs", a)
            self.create_line(0, hh - 1, w, hh - 1, fill=T.DIVIDER)
        if total > h - hh:  # 얇은 스크롤 막대
            frac = (h - hh) / total
            top = hh + (h - hh) * self.offset / total
            self.create_rectangle(w - 5, top, w - 2, top + (h - hh) * frac, fill=T.DIVIDER, outline="")

    def draw_row(self, r, xs, y, rh, w):
        cy = y + (self.rh / 2 if r.get("wrap") else rh / 2)
        if r.get("group") is not None:
            self.create_rectangle(0, y, w, y + rh, fill=T.blend(T.TEXT, self.bgc, 0.04), outline="")
            x = self.pad
            _txt(self, x, cy, r["group"], T.TEXT, "sym_s", "w")
            x += T.measure("sym_s", r["group"]) + 12
            _txt(self, x, cy, r.get("sub", ""), T.MUTED, "kr_xs", "w")
            if r.get("right"):
                _txt(self, w - self.pad, cy, r["right"], T.MUTED, "kr_xs", "e")
            self.create_line(0, y + rh - 1, w, y + rh - 1, fill=T.DIVIDER_SOFT)
            return
        bg = r.get("bg")
        if self.selectable and self.selected is not None and r.get("id") == self.selected:
            bg = T.ROW_SELECTED
        if bg:
            self.create_rectangle(0, y, w, y + rh, fill=bg, outline="")
        if r.get("dash"):
            self.create_rectangle(2, y + 2, w - 2, y + rh - 2, outline=T.UP, dash=(3, 3))
        dim = r.get("dim")
        base = bg or self.bgc
        col = (lambda c: T.blend(c, base, 0.6) if dim and c and c.startswith("#") else c)  # noqa: E731
        for c in self.cols:
            key = c["key"]
            x0, x1 = xs[key]
            if key == "chk":
                if self.check and r.get("check"):
                    draw_check(self, x0, cy, r["id"] in self.checked)
                continue
            v = r["cells"].get(key)
            if v is None:
                continue
            if not isinstance(v, dict):
                v = {"text": str(v)}
            if v.get("draw"):
                v["draw"](self, x0 + 4, x1 - 4, cy)
                continue
            a = c.get("anchor", "w")
            if v.get("tag"):
                t, tc, dash = (list(v["tag"]) + [False])[:3]
                tx = x0 + 4 if a == "w" else x1 - 4 if a == "e" else (x0 + x1) / 2
                draw_tag(self, tx, cy, t, col(tc), anchor=a, dash=dash)
                continue
            font = v.get("font") or ("num" if a == "e" else "kr")
            x = x0 + 4 if a == "w" else x1 - 4 if a == "e" else (x0 + x1) / 2
            if r.get("wrap") == key:
                self.create_text(x0 + 4, cy - 9, text=v.get("text", ""), fill=col(v.get("fg", T.TEXT)), font=T.F[font],
                                 anchor="nw", width=x1 - x0 - 8)
                if r.get("button"):
                    bt, cb = r["button"]
                    bw = T.measure("kr_btn", bt) + 24
                    by = y + rh - 40
                    self.create_rectangle(x0 + 4, by, x0 + 4 + bw, by + 28, fill=T.ACCENT, outline=T.ACCENT)
                    self.create_text(x0 + 4 + bw / 2, by + 14, text=bt, fill=T.GROUND, font=T.F["kr_btn"])
                    self.btn_hits.append((x0 + 4, by, x0 + 4 + bw, by + 28, cb))
                continue
            text = T.fit(v.get("text", ""), font, x1 - x0 - 8)
            sub = v.get("sub")
            if sub:
                _txt(self, x, cy - 8, text, col(v.get("fg", T.TEXT)), font, a)
                _txt(self, x, cy + 9, T.fit(sub, "kr_xs", x1 - x0 - 8), col(v.get("subfg", T.MUTED)), "kr_xs", a)
            elif v.get("after"):  # 같은 줄 뒤에 작은 보조 글자 (예: "1차 매도  20%")
                _txt(self, x, cy, text, col(v.get("fg", T.TEXT)), font, "w")
                _txt(self, x + T.measure(font, text) + 6, cy + 1, v["after"], col(T.MUTED), "kr_xs", "w")
            else:
                _txt(self, x, cy, text, col(v.get("fg", T.TEXT)), font, a)
        self.create_line(0, y + rh - 1, w, y + rh - 1, fill=T.DIVIDER_SOFT)

    # ---- 입력 ----
    def row_at(self, y):
        yy = self.head_h() - self.offset
        for r in self.rows:
            rh = self.row_h(r)
            if yy <= y < yy + rh:
                return r
            yy += rh
        return None

    def click(self, e):
        for x0, y0, x1, y1, cb in self.btn_hits:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                cb()
                return
        w = max(self.winfo_width(), 200)
        xs = self.xs(w)
        in_chk = "chk" in xs and xs["chk"][0] - 6 <= e.x <= xs["chk"][1] + 4
        if e.y < self.head_h():
            if in_chk and self.check:
                ids = self.checkable()
                self.set_all(len(self.checked & set(ids)) < len(ids))
            return
        r = self.row_at(e.y)
        if not r or r.get("group") is not None:
            return
        if self.check and r.get("check") and (in_chk or not self.on_click):
            self.checked.symmetric_difference_update({r["id"]})
            self.draw()
            if self.on_check:
                self.on_check()
            return
        if self.selectable:
            self.selected = r.get("id")
            self.draw()
        if self.on_click:
            self.on_click(r.get("id"))

    def on_wheel(self, steps):
        """휠 한 칸 = 3줄. 이 표가 스크롤할 게 없으면 False (바깥 페이지가 스크롤)."""
        if self.fit or sum(self.row_h(r) for r in self.rows) <= self.winfo_height() - self.head_h():
            return False
        self.offset = max(0, self.offset + steps * 36)
        self.draw()
        return True


class StatCells(tk.Frame):
    """요약 칸 (투자내역·자동매매·주문): 같은 폭 칸, 라벨(11px MUTED) + 값(Condensed 큰 글자) + 아래 보조 줄."""

    def __init__(self, parent, cells, big=True, bg=T.PANEL):
        super().__init__(parent, bg=bg, highlightthickness=1, highlightbackground=T.DIVIDER)
        self.vals = {}
        for i, (key, label) in enumerate(cells):
            self.columnconfigure(i * 2, weight=1, uniform="cell")
            if i:
                tk.Frame(self, bg=T.DIVIDER, width=1).grid(row=0, column=i * 2 - 1, sticky="ns")
            cell = tk.Frame(self, bg=bg)
            cell.grid(row=0, column=i * 2, sticky="nsew", padx=18, pady=(12, 10))
            lab = tk.Label(cell, text=label, bg=bg, fg=T.MUTED, font=T.F["kr_xs"], anchor="w")
            lab.pack(anchor="w")
            row = tk.Frame(cell, bg=bg)
            row.pack(anchor="w")
            val = tk.Label(row, text="-", bg=bg, fg=T.TEXT, font=T.F["sum_val_l" if big else "sum_val"], anchor="w")
            val.pack(side="left")
            unit = tk.Label(row, text="", bg=bg, fg=T.TEXT, font=T.F["sum_val_l" if big else "sum_val"], anchor="w")
            unit.pack(side="left")
            extra = tk.Label(row, text="", bg=bg, fg=T.MUTED, font=T.F["num_s"], anchor="sw")
            extra.pack(side="left", padx=(8, 0), anchor="s", pady=(0, 6))
            sub = tk.Label(cell, text="", bg=bg, fg=T.MUTED, font=T.F["kr_xs"], anchor="w")
            sub.pack(anchor="w")
            self.vals[key] = (val, unit, sub, lab, extra)

    def set(self, key, text, unit="", color=T.TEXT, sub="", extra="", extra_color=None, label=None):
        val, u, s, lab, ex = self.vals[key]
        val.config(text=text, fg=color)
        u.config(text=unit, fg=color)
        s.config(text=sub)
        ex.config(text=extra, fg=extra_color or color)
        if label is not None:
            lab.config(text=label)


class CoinList(tk.Canvas):
    """현황 1b 왼쪽 목록. groups: [(제목, 링크 글자|None, [item])].
    item: {"id", "lines": [(왼쪽 [(글자,색,글꼴)], 오른쪽 [(글자,색,글꼴)])], "dim", "h"}"""

    def __init__(self, parent, on_select=None, on_link=None):
        super().__init__(parent, bg=T.PANEL, highlightthickness=0, width=280)
        self.groups, self.selected, self.offset = [], None, 0
        self.on_select, self.on_link = on_select, on_link
        self.hits = []
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self.click)

    def set(self, groups, selected):
        if groups == self.groups and selected == self.selected:
            return
        self.groups, self.selected = groups, selected
        self.draw()

    def on_wheel(self, steps):
        self.offset = max(0, self.offset + steps * 30)
        self.draw()
        return True

    def draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 100), max(self.winfo_height(), 100)
        total = sum(30 + sum(it.get("h", 90) for it in items) + 8 for _, _, items in self.groups)
        self.offset = min(self.offset, max(0, total - h))
        y = -self.offset
        self.hits = []
        for gi, (title, link, items) in enumerate(self.groups):
            if gi:
                self.create_line(0, y, w, y, fill=T.DIVIDER)
                y += 8
            _txt(self, 16, y + 16, title, T.MUTED, "kr_xs", "w")
            if link:
                tid = _txt(self, w - 16, y + 16, link, T.ACCENT, "kr_xs", "e")
                self.hits.append((y, y + 30, ("link", title), self.bbox(tid)))
            y += 30
            for it in items:
                ih = it.get("h", 90)
                sel = it["id"] == self.selected
                if sel:
                    self.create_rectangle(0, y, w, y + ih, fill=T.ROW_SELECTED, outline="")
                    self.create_rectangle(0, y, 3, y + ih, fill=T.ACCENT, outline="")
                base = T.ROW_SELECTED if sel else T.PANEL
                col = (lambda c: T.blend(c, base, 0.6) if it.get("dim") else c)  # noqa: E731
                n = len(it["lines"])
                step = (ih - 20) / max(n, 1)
                for li, (left, right) in enumerate(it["lines"]):
                    ly = y + 10 + step * (li + 0.5)
                    x = 18
                    for text, fg, font in left:
                        _txt(self, x, ly, text, col(fg), font, "w")
                        x += T.measure(font, text) + 6
                    x = w - 16
                    for text, fg, font in reversed(right):
                        _txt(self, x, ly, text, col(fg), font, "e")
                        x -= T.measure(font, text) + 4
                self.hits.append((y, y + ih, ("item", it["id"]), None))
                y += ih

    def click(self, e):
        for y0, y1, (kind, val), box in self.hits:
            if kind == "link" and box and box[0] - 4 <= e.x <= box[2] + 4 and box[1] - 4 <= e.y <= box[3] + 4:
                if self.on_link:
                    self.on_link(val)
                return
            if kind == "item" and y0 <= e.y < y1:
                if self.on_select:
                    self.on_select(val)
                return


class Ruler(tk.Canvas):
    """현황 1b 가격 눈금자: 레벨을 실제 가격 비율 위치에 가로줄로 (이름 120 | 선 | 가격 150 | 대비 80).
    rows: [{"name","sub","price","pct","color","kind"(sell/buy/now/stop/outside),"near"}]"""

    def __init__(self, parent):
        super().__init__(parent, bg=T.GROUND, highlightthickness=1, highlightbackground=T.DIVIDER)
        self.rows = []
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, rows):
        if rows == self.rows:
            return
        self.rows = rows
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 200), max(self.winfo_height(), 120)
        rows = [r for r in self.rows if r.get("price")]
        if not rows:
            _txt(self, w / 2, h / 2, "레벨 계산 중…", T.MUTED, "kr_s", "center")
            return
        prices = [r["price"] for r in rows]
        hi, lo = max(prices) * 1.03, min(prices) * 0.97
        top, bot = 22, h - 22
        pos = sorted(((top + (hi - r["price"]) / (hi - lo) * (bot - top), r) for r in rows), key=lambda t: t[0])
        gap = min(24, (bot - top) / max(len(pos) - 1, 1))  # 글자가 겹치지 않게 최소 간격
        ys = [p for p, _ in pos]
        for i in range(1, len(ys)):
            ys[i] = max(ys[i], ys[i - 1] + gap)
        over = ys[-1] - bot if ys else 0
        if over > 0:
            for i in range(len(ys) - 1, -1, -1):
                lim = bot if i == len(ys) - 1 else ys[i + 1] - gap
                ys[i] = min(ys[i], lim)
        placed = [(y, r) for y, (_, r) in zip(ys, pos)]
        xn, xp1, xpc = 16, w - 16 - 80 - 12, w - 16
        line0, line1 = xn + 150, xp1 - 150 - 12
        sell1 = next((y for y, r in placed if r["kind"] == "sell" and r.get("first")), None)
        buy1 = next((y for y, r in placed if r["kind"] == "buy" and r.get("first")), None)
        if sell1 is not None and buy1 is not None:  # 관망 구간 (1차 매도 ~ 1차 매수)
            self.create_rectangle(1, sell1, w - 1, buy1, fill=T.blend(T.ACCENT, T.GROUND, 0.07), outline="")
        for y, r in placed:
            kind, color = r["kind"], r.get("color", T.TEXT)
            if r.get("near") and kind != "now":
                self.create_rectangle(1, y - gap / 2 + 1, w - 1, y + gap / 2 - 1, fill=T.ROW_NEAR, outline="")
            if kind == "now":
                self.create_rectangle(1, y - 18, w - 1, y + 18, fill=T.ROW_CURRENT, outline="")
                _txt(self, xn, y, r["name"], T.TEXT, "kr_b", "w")
                self.create_line(line0, y, line1, y, fill=T.TEXT, width=2)
                _txt(self, xp1, y, T.fmtp(r["price"]), T.TEXT, "num_l", "e")
                continue
            x = xn
            _txt(self, x, y, r["name"], color, "kr", "w")
            if r.get("sub"):
                _txt(self, x + T.measure("kr", r["name"]) + 5, y + 1, r["sub"], T.MUTED, "kr_xxs", "w")
            dash = (3, 3) if kind in ("stop", "outside") else ()
            self.create_line(line0, y, line1, y, fill=T.blend(color, T.GROUND, 0.45), dash=dash)
            _txt(self, xp1, y, T.fmtp(r["price"]), T.TEXT if kind != "outside" else T.MUTED, "num_cell", "e")
            if r.get("pct") is not None:
                _txt(self, xpc, y, f"{r['pct']:+.1f}%", color, "num", "e")


class Toggle(tk.Canvas):
    """34×18 스위치. 켜짐 ACCENT, 꺼짐 UP."""

    def __init__(self, parent, value=False, command=None, bg=T.PANEL):
        super().__init__(parent, width=34, height=18, bg=bg, highlightthickness=0, cursor="hand2")
        self.value, self.command = value, command
        self.bind("<Button-1>", lambda e: self.command and self.command(not self.value))
        self.draw()

    def set(self, v):
        self.value = v
        self.draw()

    def draw(self):
        self.delete("all")
        col = T.ACCENT if self.value else T.UP
        self.create_rectangle(0, 0, 33, 17, fill=col, outline=col)
        x = 18 if self.value else 2
        self.create_rectangle(x, 2, x + 13, 15, fill=T.TEXT, outline="")


class Segmented(tk.Frame):
    """세그먼트 필터 (1px DIVIDER 테두리, 선택 칸 ACCENT)."""

    def __init__(self, parent, options, value, command, bg=T.PANEL):
        super().__init__(parent, bg=bg, highlightthickness=1, highlightbackground=T.DIVIDER)
        self.labels, self.command = {}, command
        for name in options:
            s = tk.Label(self, text=name, font=T.F["kr_s"], padx=12, pady=4, cursor="hand2")
            s.pack(side="left")
            s.bind("<Button-1>", lambda e, n=name: self.pick(n))
            self.labels[name] = s
        self.set(value)

    def set(self, value):
        self.value = value
        for n, s in self.labels.items():
            s.config(bg=T.ACCENT if n == value else T.PANEL, fg=T.GROUND if n == value else T.TEXT)

    def pick(self, n):
        self.set(n)
        self.command(n)


def scroll_page(parent, bg=T.GROUND):
    """세로 스크롤 본문. (바깥 프레임, 안쪽 body) 반환. 휠은 포인터가 안에 있을 때만."""
    outer = tk.Frame(parent, bg=bg)
    canvas = tk.Canvas(outer, bg=bg, highlightthickness=0)
    body = tk.Frame(canvas, bg=bg)
    win = canvas.create_window(0, 0, window=body, anchor="nw")
    bar = tk.Canvas(outer, width=6, bg=bg, highlightthickness=0)

    def sync(*_):
        canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), max(body.winfo_reqheight(), canvas.winfo_height())))
        draw_bar()

    def draw_bar(*_):
        bar.delete("all")
        a, b = canvas.yview()
        if b - a < 0.999:
            hh = bar.winfo_height()
            bar.create_rectangle(1, a * hh, 5, b * hh, fill=T.DIVIDER, outline="")

    def yview(*args):
        canvas.yview(*args)
        draw_bar()

    body.bind("<Configure>", sync)
    canvas.bind("<Configure>", lambda e: (canvas.itemconfigure(win, width=e.width), sync()))
    canvas.configure(yscrollcommand=lambda a, b: draw_bar())

    def on_wheel(steps):
        if canvas.yview() == (0.0, 1.0):
            return False
        yview("scroll", steps, "units")
        return True

    outer.on_wheel = on_wheel
    bar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    outer.canvas = canvas
    return outer, body


def install_wheel(root):
    """마우스 휠을 한 곳에서 받아, 포인터 아래 위젯부터 바깥으로 올라가며 on_wheel이 있는 곳에 넘긴다
    (표 안에서 굴리면 표가, 표 끝이면 바깥 페이지가 스크롤)."""
    def handle(steps, e):
        w = root.winfo_containing(e.x_root, e.y_root)
        while w is not None:
            fn = getattr(w, "on_wheel", None)
            if fn and fn(steps):
                return
            w = getattr(w, "master", None)
    root.bind_all("<MouseWheel>", lambda e: handle(-1 if e.delta > 0 else 1, e))
    root.bind_all("<Button-4>", lambda e: handle(-1, e))
    root.bind_all("<Button-5>", lambda e: handle(1, e))
