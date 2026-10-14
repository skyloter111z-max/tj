"""fib_watch.py를 명령 프롬프트 창 없이 작업표시줄 트레이 아이콘으로 실행한다.

처음 한 번:  pip install pystray pillow
실행:       fib_tray.pyw 더블클릭 (또는 pythonw fib_tray.pyw)
트레이 아이콘에 마우스를 올리면 현재가, 오른쪽 클릭하면 레벨 보기·로그 열기·종료.
알림은 fib_watch.py와 같다 (소리 + 맨 위 팝업 + 트레이 풍선).
"""
import ctypes
import datetime
import os
import sys
import threading

import pystray
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
LOG = os.path.join(HERE, "fib_watch.log")
sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)  # pythonw엔 콘솔이 없음

import fib_watch  # noqa: E402

stop = threading.Event()
latest = {"prices": {}, "levels": {}}


def make_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    d.text((22, 18), "F", fill="white")
    return img


ICON_OK, ICON_ALERT = make_icon((37, 99, 235)), make_icon((220, 38, 38))


def alert(title, msg):
    fib_watch.notify(title, msg)  # 소리 + 팝업 + 로그
    icon.icon = ICON_ALERT
    try:
        icon.notify(msg, title)
    except Exception:
        pass


def on_tick(prices, levels):
    latest["prices"], latest["levels"] = prices, levels
    stamp = datetime.datetime.now().strftime("%H:%M")
    icon.title = f"fib 감시 {stamp}\n" + "\n".join(f"{c} {p:,.0f}" for c, p in prices.items())[:120]


def show_levels(_icon=None, _item=None):
    icon.icon = ICON_OK
    lines = []
    for coin, items in latest["levels"].items():
        p = latest["prices"].get(coin)
        lines.append(f"[{coin}] 현재가 {p:,.0f}" if p else f"[{coin}]")
        for name, lvl in items:
            lines.append(f"   {name}: {lvl:,.0f}" + (f"  ({(lvl / p - 1) * 100:+.1f}%)" if p else ""))
    threading.Thread(target=ctypes.windll.user32.MessageBoxW,
                     args=(0, "\n".join(lines) or "아직 불러오는 중", "피보나치 레벨", 0x40040), daemon=True).start()


def open_log(_icon=None, _item=None):
    os.startfile(LOG)


def quit_app(_icon=None, _item=None):
    stop.set()
    icon.stop()


icon = pystray.Icon("fib_watch", ICON_OK, "fib 감시 시작 중",
                    menu=pystray.Menu(pystray.MenuItem("레벨·현재가 보기", show_levels, default=True),
                                      pystray.MenuItem("로그 열기", open_log),
                                      pystray.MenuItem("종료", quit_app)))

threading.Thread(target=fib_watch.watch, kwargs={"alert": alert, "on_tick": on_tick, "stop": stop},
                 daemon=True).start()
icon.run()
