"""FibTrader 화면 부품: 상단 탭바, 시세 티커, 레벨 사다리 표, 캔들 차트, 요약 칸.

모두 tk.Canvas/Frame으로 그린다. 가격이 바뀌면 텍스트만 다시 그리고 위젯은 새로 만들지 않는다.
"""
import tkinter as tk
import tkinter.font as tkfont

import fibtrader_theme as T


class Tabs(tk.Frame):
    """상단바 안에 들어가는 탭 + 본문 전환. ttk.Notebook 대신 (탭을 상단바 한 줄에 넣기 위해)."""

    def __init__(self, parent, bar):
        super().__init__(parent, bg=T.GROUND)
        self.bar, self.pages, self.labels, self.current = bar, [], [], None
        self.on_change = None

    def add(self, frame, text):
        idx = len(self.pages)
        holder = tk.Frame(self.bar, bg=T.PANEL)
        holder.pack(side="left")
        lab = tk.Label(holder, text=text.strip(), bg=T.PANEL, fg=T.MUTED, font=T.F["kr"], padx=16, cursor="hand2")
        lab.pack(fill="y", expand=True, ipady=9)
        line = tk.Frame(holder, bg=T.PANEL, height=2)
        line.pack(fill="x", side="bottom")
        lab.bind("<Button-1>", lambda e: self.select(idx))
        self.pages.append(frame)
        self.labels.append((lab, line))
        if self.current is None:
            self.select(0)

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
        self.groups, self.prev, self.flash = [], {}, {}
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, groups):
        """groups: [(그룹 이름, [(코인, 가격, 등락률%)])]"""
        for _, items in groups:
            for coin, price, _ in items:
                old = self.prev.get(coin)
                if old is not None and price != old:
                    self.flash[coin] = (T.UP if price > old else T.DOWN)
                    self.after(500, lambda c=coin: (self.flash.pop(c, None), self.draw()))
                self.prev[coin] = price
        self.groups = groups
        self.draw()

    def draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 200)
        f_lab, f_sym, f_num = (tkfont.Font(font=T.F[k]) for k in ("kr_xs", "num_b", "num"))
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
            x += f_lab.measure(gname) + 10
            for i, (coin, price, ch) in enumerate(items):
                ptxt, ctxt = T.fmtp(price), f"{T.arrow(ch)}{abs(ch):.2f}%"
                width = f_sym.measure(coin) + 6 + f_num.measure(ptxt) + 6 + f_num.measure(ctxt) + 18
                if x + width > w - 10 and x > 120:
                    x, line = 18 + f_lab.measure(gname) + 10, line + 1
                cy = y + line * self.LINE
                if coin in self.flash:
                    self.create_rectangle(x - 4, cy - 12, x + width - 12, cy + 12,
                                          fill=T.blend(self.flash[coin], T.GROUND, 0.25), outline="")
                self.create_text(x, cy, text=coin, fill=T.TEXT, font=T.F["num_b"], anchor="w")
                x += f_sym.measure(coin) + 6
                self.create_text(x, cy, text=ptxt, fill=T.TEXT, font=T.F["num"], anchor="w")
                x += f_num.measure(ptxt) + 6
                self.create_text(x, cy, text=ctxt, fill=T.chg_color(ch), font=T.F["num"], anchor="w")
                x += f_num.measure(ctxt) + 8
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
        self.rows = rows
        if rh:
            self.rh = rh
        live = {r["uuid"] for r in rows if r.get("uuid")}
        self.checked &= live  # 사라진 주문은 선택 해제
        h = self.HEAD + len(rows) * self.rh
        if int(self.cget("height")) != h:
            self.config(height=h)
        self.draw()

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
                tw = tkfont.Font(font=T.F["num"]).measure(txt)
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
    """캔들 차트 (스펙 6장). 양봉 UP, 음봉 DOWN, 몸통 64%, 꼬리 1px, 점선 기준선 + 라벨."""

    def __init__(self, parent, height=150):
        super().__init__(parent, bg=T.GROUND, height=height, highlightthickness=1, highlightbackground=T.DIVIDER)
        self.data, self.lines, self.unit = [], [], ""
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, candles, lines, unit):
        """candles: [(시가, 고가, 저가, 종가)] 오래된 것부터. lines: [(라벨, 가격, 색, 실선여부)]"""
        self.data, self.lines, self.unit = candles, lines, unit
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = max(self.winfo_width(), 100), max(self.winfo_height(), 60)
        if not self.data:
            self.create_text(w / 2, h / 2, text="불러오는 중…", fill=T.MUTED, font=T.F["kr_xs"])
            return
        vals = [c[1] for c in self.data] + [c[2] for c in self.data] + [p for _, p, _, _ in self.lines if p]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.08 or hi * 0.01
        lo, hi = lo - pad, hi + pad
        top, bot = 6, h - 16
        y = lambda v: top + (hi - v) / (hi - lo) * (bot - top)  # noqa: E731
        n = len(self.data)
        slot = (w - 8) / n
        for i, (o, hh, ll, c) in enumerate(self.data):
            cx = 4 + slot * (i + 0.5)
            col = T.UP if c >= o else T.DOWN
            self.create_line(cx, y(hh), cx, y(ll), fill=col)
            bw = max(slot * 0.64, 1)
            y0, y1 = sorted((y(o), y(c)))
            self.create_rectangle(cx - bw / 2, y0, cx + bw / 2, max(y1, y0 + 1), fill=col, outline=col)
        for label, price, color, solid in self.lines:
            if not price:
                continue
            ly = y(price)
            self.create_line(0, ly, w, ly, fill=color, dash=() if solid else (2, 3))
            tid = self.create_text(6, ly - 2, text=f"{label} {T.fmtp(price)}", fill=color, font=T.F["kr_xs"], anchor="sw")
            x0, y0, x1, y1 = self.bbox(tid)
            rid = self.create_rectangle(x0 - 2, y0, x1 + 2, y1, fill=T.GROUND, outline="")
            self.tag_raise(tid, rid)
        self.create_text(w - 6, h - 3, text=self.unit, fill=T.MUTED, font=T.F["num_xs"], anchor="se")


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
