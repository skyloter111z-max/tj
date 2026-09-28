"""텔레그램 조회 전용 봇: 휴대폰으로 알림을 받고 현황만 본다. 주문·설정 변경 명령은 일부러 없다.

- 토큰은 PC 환경변수 TELEGRAM_BOT_TOKEN, 주인 채팅 번호는 TELEGRAM_CHAT_ID (파일·깃허브에 절대 안 적음).
- 주인 채팅이 아닌 곳에서 온 메시지는 무시한다. 주인 번호를 아직 안 넣었으면, 말을 건 채팅에 그 채팅 번호만 알려 준다.
- 표준 라이브러리만 사용. 네트워크 오류는 조용히 다시 시도 (프로그램 매매에는 영향 없음).
"""
import datetime
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

KST = datetime.timezone(datetime.timedelta(hours=9))
LIMIT = 3900  # 텔레그램 한 메시지 최대 4096자 → 여유 두고 나눔

HELP = ("FibTrader 조회 전용 봇입니다 (주문·설정 변경은 안 됩니다).\n"
        "/status 또는 현황 : 피보나치·자동매매 현황\n"
        "/today 또는 오늘 : 오늘 자동매매 익절·매수\n"
        "/help : 이 안내\n"
        "매매·체결·오류 알림은 자동으로 옵니다. 매일 09시에 어제 요약을 보냅니다.")


class Telegram:
    def __init__(self, on_command, token=None, chat_id=None):
        self.token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        self.chat = str(chat) if chat else ""
        self.enabled = bool(self.token)
        self.on_command = on_command  # (명령 이름) → 엔진에 요청 (엔진 스레드에서 글을 만들어 send로 보냄)
        self.out = queue.Queue()
        self.stop_event = threading.Event()
        self.offset = None
        self.last_daily = datetime.datetime.now(KST).strftime("%Y-%m-%d") if datetime.datetime.now(KST).hour >= 10 else ""
        self.status = "꺼짐 (토큰 없음)" if not self.enabled else "연결 중"

    # ---- 텔레그램 API ----
    def call(self, method, params, timeout=40):
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/{method}", data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
        if not body.get("ok"):
            raise RuntimeError(body.get("description", "텔레그램 오류"))
        return body["result"]

    # ---- 보내기 (묶어서) ----
    def send(self, text, chat=None):
        """보낼 글을 줄에 넣는다. chat 없으면 주인 채팅으로 (주인 번호 없으면 버림)."""
        chat = chat or self.chat
        if self.enabled and chat and text:
            self.out.put((str(chat), text))

    def notify(self, title, msg):
        self.send(f"🔔 {title}\n{msg}".strip())

    def _sender(self):
        while not self.stop_event.is_set():
            try:
                first = self.out.get(timeout=1)
            except queue.Empty:
                continue
            time.sleep(3)  # 같은 순간에 생긴 알림은 한 메시지로
            items = [first]
            while not self.out.empty() and len(items) < 30:
                items.append(self.out.get_nowait())
            by_chat = {}
            for chat, text in items:
                by_chat.setdefault(chat, []).append(text)
            for chat, texts in by_chat.items():
                buf = ""
                for t in texts:
                    if buf and len(buf) + len(t) + 2 > LIMIT:
                        self._post(chat, buf)
                        buf = ""
                    buf = f"{buf}\n\n{t}" if buf else t
                    while len(buf) > LIMIT:
                        self._post(chat, buf[:LIMIT])
                        buf = buf[LIMIT:]
                if buf:
                    self._post(chat, buf)

    def _post(self, chat, text):
        for i in range(3):
            try:
                self.call("sendMessage", {"chat_id": chat, "text": text, "disable_web_page_preview": "true"}, timeout=20)
                self.status = "연결됨"
                return
            except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
                # 오류 글에 주소(토큰 포함)가 섞이지 않게 종류만 남긴다
                self.status = f"보내기 실패 ({type(e).__name__})"
                time.sleep(2 * (i + 1))

    # ---- 받기 (명령) ----
    def _poller(self):
        while not self.stop_event.is_set():
            now = datetime.datetime.now(KST)
            if now.hour == 9 and self.last_daily != now.strftime("%Y-%m-%d"):
                self.last_daily = now.strftime("%Y-%m-%d")
                if self.chat:
                    self.on_command("daily")
            try:
                params = {"timeout": 25, "allowed_updates": json.dumps(["message"])}
                if self.offset is not None:
                    params["offset"] = self.offset
                updates = self.call("getUpdates", params, timeout=35)
                self.status = "연결됨"
            except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
                self.status = f"연결 실패 ({type(e).__name__}) · 다시 시도"
                self.stop_event.wait(10)
                continue
            for u in updates:
                self.offset = u["update_id"] + 1
                self.handle(u.get("message") or {})

    def handle(self, m):
        chat = str((m.get("chat") or {}).get("id", ""))
        text = (m.get("text") or "").strip()
        if not chat or not text:
            return
        if not self.chat:  # 처음 설정: 주인 번호를 알려 준다 (현황은 절대 안 보냄)
            self.send(f"이 채팅 번호: {chat}\nPC 환경변수 TELEGRAM_CHAT_ID에 이 번호를 넣고 FibTrader를 다시 켜면 이 채팅으로만 알림·현황을 보냅니다.", chat)
            return
        if chat != self.chat:
            return  # 주인 채팅이 아니면 무시 (답도 안 함)
        cmd = text.split()[0].split("@")[0].lower()
        if cmd in ("/status", "현황", "/현황", "상태"):
            self.on_command("status")
        elif cmd in ("/today", "오늘", "/오늘"):
            self.on_command("today")
        else:
            self.send(HELP)

    def start(self):
        if not self.enabled:
            return
        for fn in (self._sender, self._poller):
            threading.Thread(target=fn, daemon=True).start()
        if self.chat:
            self.send("FibTrader가 켜졌습니다. /status 로 현황을 볼 수 있습니다.")

    def stop(self):
        self.stop_event.set()
