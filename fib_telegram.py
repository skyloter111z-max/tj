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


def env(name):
    """환경변수. 프로그램이 setx보다 먼저 켜진 창(탐색기·트레이)에서 실행되면 새 값이 안 보이므로,
    없으면 윈도우 사용자 환경변수(레지스트리 HKCU\\Environment)에서 직접 읽는다."""
    v = os.environ.get(name, "").strip()
    if v or os.name != "nt":
        return v
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0]).strip()
    except OSError:
        return ""


def why(e):
    """오류를 사람이 알아볼 말로 (토큰이 섞인 주소는 절대 넣지 않는다)."""
    if isinstance(e, urllib.error.HTTPError):
        return {401: "토큰이 틀림 (BotFather 토큰 다시 확인)", 404: "토큰이 틀림 (BotFather 토큰 다시 확인)",
                409: "같은 봇을 다른 곳에서도 켜 둠 (FibTrader 두 개?)"}.get(e.code, f"텔레그램 오류 {e.code}")
    if isinstance(e, urllib.error.URLError):
        return "텔레그램 서버에 연결 안 됨 (인터넷·방화벽·백신 확인)"
    return type(e).__name__


class Telegram:
    def __init__(self, on_command, token=None, chat_id=None):
        self.token = token if token is not None else env("TELEGRAM_BOT_TOKEN")
        chat = chat_id if chat_id is not None else env("TELEGRAM_CHAT_ID")
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
            except Exception as e:  # noqa: BLE001 — 어떤 오류든 봇 스레드가 죽지 않게. 오류 글에 주소(토큰 포함)가 섞이지 않게 종류만 남긴다
                self.status = f"보내기 실패: {why(e)}"
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
                self.status = "연결됨" if self.chat else "연결됨 · 채팅 번호 없음 (봇에게 아무 말이나 보내면 번호를 답해 줌)"
            except Exception as e:  # noqa: BLE001 — 네트워크가 끊겨도 다시 시도 (봇 스레드가 죽지 않게)
                self.status = f"연결 실패: {why(e)} · 다시 시도 중"
                self.stop_event.wait(10)
                continue
            for u in updates:
                self.offset = u["update_id"] + 1
                try:
                    self.handle(u.get("message") or {})
                except Exception:  # noqa: BLE001 — 이상한 메시지 하나 때문에 봇이 멈추지 않게
                    pass

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


def self_test():
    """C:\\fib\\tg_test.bat 로 실행: 토큰·봇·채팅 번호를 하나씩 확인한다 (토큰 값은 절대 화면에 안 보임)."""
    t = Telegram(lambda cmd: None)
    print("1) 토큰(TELEGRAM_BOT_TOKEN):", "있음" if t.token else "없음 → setx TELEGRAM_BOT_TOKEN \"BotFather가 준 토큰\" 입력 후 다시")
    if not t.token:
        return
    if ":" not in t.token:
        tk_ = t.token
        hints = [f"글자 수 {len(tk_)}자 (정상은 45자 안팎)"]
        if any(ord(ch) > 127 for ch in tk_):
            hints.append("한글 등 영어가 아닌 글자가 들어 있음 → '토큰'이라는 글자를 그대로 넣었을 수 있음")
        if any(ch in tk_ for ch in "\"'<>"):
            hints.append("따옴표나 < > 기호가 들어 있음")
        if " " in tk_:
            hints.append("중간에 띄어쓰기가 있음")
        print("   토큰 모양이 이상합니다. BotFather 토큰은 '숫자:영문' 모양입니다 (예: 1234567890:AAH…).")
        print("   · " + "\n   · ".join(hints))
    try:
        me = t.call("getMe", {}, timeout=15)
        print(f"2) 봇 연결: 성공 → @{me.get('username')} ({me.get('first_name')})  ← 텔레그램에서 이 봇과 대화하세요")
    except Exception as e:  # noqa: BLE001
        print("2) 봇 연결: 실패 →", why(e))
        return
    print("3) 채팅 번호(TELEGRAM_CHAT_ID):", t.chat or "없음")
    try:
        ups = t.call("getUpdates", {"timeout": 0}, timeout=15)
        chats = {}
        for u in ups:
            ch = (u.get("message") or {}).get("chat") or {}
            if ch.get("id"):
                chats[str(ch["id"])] = ch.get("first_name") or ch.get("title") or ""
        if chats:
            for cid, name in chats.items():
                print(f"   최근 봇에게 말 건 채팅: {cid} ({name})" + ("  ← 설정된 번호와 같음" if cid == t.chat else ""))
            if not t.chat:
                cid = next(iter(chats))
                print(f"   → 명령 프롬프트에 입력:  setx TELEGRAM_CHAT_ID {cid}   그다음 FibTrader를 트레이에서 종료 후 다시 켜기")
        elif not t.chat:
            print("   아직 봇에게 온 메시지가 없습니다. 텔레그램에서 위 봇에게 '안녕'을 보낸 뒤 이 창을 다시 실행하세요.")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("   (FibTrader가 켜져 있어 메시지는 FibTrader가 받는 중 → 정상. 번호 확인이 필요하면 FibTrader를 끄고 다시 실행)")
        else:
            print("   메시지 확인 실패 →", why(e))
    except Exception as e:  # noqa: BLE001
        print("   메시지 확인 실패 →", why(e))
    if t.chat:
        try:
            t.call("sendMessage", {"chat_id": t.chat, "text": "FibTrader 텔레그램 테스트: 이 메시지가 보이면 알림 연결 성공입니다."}, timeout=15)
            print("4) 테스트 메시지 보내기: 성공 → 휴대폰 텔레그램을 확인하세요")
        except Exception as e:  # noqa: BLE001
            print("4) 테스트 메시지 보내기: 실패 →", why(e), "(채팅 번호가 틀렸거나, 봇에게 먼저 말을 안 걸었음)")


if __name__ == "__main__":
    self_test()
