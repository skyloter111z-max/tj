"""업비트 실시간 시세(웹소켓) 수신. 표준 라이브러리만 사용.

TickerStream(coins).start() → 가격이 바뀔 때마다 self.data[coin] = (현재가, 전일 대비 %, 전일 대비 금액) 갱신.
끊기면 알아서 다시 연결한다 (2초 → 최대 30초 간격). healthy()가 False면 쓰는 쪽이 REST로 대신 받는다.
HTTPS_PROXY 환경변수가 있으면 그 프록시로 CONNECT 해서 연결한다.
"""
import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.parse
import uuid

HOST, PORT, PATH = "api.upbit.com", 443, "/websocket/v1"


class TickerStream(threading.Thread):
    def __init__(self, coins):
        super().__init__(daemon=True)
        self.coins = sorted(set(coins))
        self.data, self.lock = {}, threading.Lock()
        self.dirty = False
        self.connected = False
        self.last_msg = 0.0
        self.stop_flag = threading.Event()
        self.sock = None
        self.error = ""

    # ---- 쓰는 쪽 ----
    def healthy(self, max_quiet=20):
        """연결돼 있고 최근 max_quiet초 안에 시세가 왔으면 True."""
        return self.connected and time.time() - self.last_msg < max_quiet

    def take(self):
        """바뀐 게 있으면 전체 시세 사본, 없으면 None."""
        with self.lock:
            if not self.dirty:
                return None
            self.dirty = False
            return dict(self.data)

    def stop(self):
        self.stop_flag.set()
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    # ---- 연결 ----
    def _open(self):
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy:
            u = urllib.parse.urlparse(proxy if "://" in proxy else "http://" + proxy)
            raw = socket.create_connection((u.hostname, u.port or 80), timeout=10)
            auth = ""
            if u.username:
                cred = base64.b64encode(f"{urllib.parse.unquote(u.username)}:{urllib.parse.unquote(u.password or '')}".encode()).decode()
                auth = f"Proxy-Authorization: Basic {cred}\r\n"
            raw.sendall(f"CONNECT {HOST}:{PORT} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\n{auth}\r\n".encode())
            head = self._read_head(raw)
            if b" 200" not in head.split(b"\r\n", 1)[0]:
                raw.close()
                raise OSError(f"프록시 연결 실패: {head[:80]!r}")
        else:
            raw = socket.create_connection((HOST, PORT), timeout=10)
        ctx = ssl.create_default_context()
        s = ctx.wrap_socket(raw, server_hostname=HOST)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET {PATH} HTTP/1.1\r\nHost: {HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = self._read_head(s)
        if b" 101" not in head.split(b"\r\n", 1)[0]:
            s.close()
            raise OSError(f"웹소켓 연결 거절: {head[:80]!r}")
        return s

    @staticmethod
    def _read_head(s):
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(1)
            if not chunk:
                raise OSError("연결이 닫힘")
            buf += chunk
            if len(buf) > 8192:
                raise OSError("응답 머리가 너무 김")
        return buf

    def _send(self, opcode, payload=b""):
        mask = os.urandom(4)
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(head + mask + body)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise OSError("연결이 닫힘")
            buf += chunk
        return buf

    def _recv_frame(self):
        b0, b1 = self._recv_exact(2)
        fin, opcode = b0 & 0x80, b0 & 0x0F
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._recv_exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if b1 & 0x80 else None
        data = self._recv_exact(n) if n else b""
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return fin, opcode, data

    def _on_message(self, raw):
        try:
            m = json.loads(raw)
        except ValueError:
            return
        code = m.get("code") or m.get("cd") or ""
        if not code.startswith("KRW-") or "trade_price" not in m:
            return
        with self.lock:
            self.data[code[4:]] = (m["trade_price"], m.get("signed_change_rate", 0) * 100, m.get("signed_change_price", 0))
            self.dirty = True
        self.last_msg = time.time()

    def run(self):
        wait = 2
        while not self.stop_flag.is_set():
            try:
                self.sock = self._open()
                sub = [{"ticket": str(uuid.uuid4())}, {"type": "ticker", "codes": [f"KRW-{c}" for c in self.coins]}]
                self._send(0x1, json.dumps(sub).encode())
                self.sock.settimeout(5)
                self.connected, wait, last_ping = True, 2, time.time()
                self.last_msg = time.time()
                parts = b""
                while not self.stop_flag.is_set():
                    if time.time() - last_ping > 30:  # 업비트는 2분 동안 아무것도 없으면 끊는다
                        self._send(0x9)
                        last_ping = time.time()
                    try:
                        fin, op, data = self._recv_frame()
                    except socket.timeout:
                        continue
                    if op == 0x8:
                        raise OSError("서버가 연결을 닫음")
                    if op == 0x9:
                        self._send(0xA, data)
                        continue
                    if op in (0x1, 0x2, 0x0):
                        parts += data
                        if fin:
                            self._on_message(parts)
                            parts = b""
            except Exception as e:  # 네트워크·프록시·업비트 점검 → 잠시 뒤 다시 연결
                self.error = str(e)
            finally:
                self.connected = False
                try:
                    if self.sock:
                        self.sock.close()
                except OSError:
                    pass
            self.stop_flag.wait(wait)
            wait = min(wait * 2, 30)
