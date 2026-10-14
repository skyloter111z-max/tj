"""음성 알림: 짧은 효과음 + 윈도우 기본 한국어 음성(TTS)으로 한 줄 읽기. 표준 라이브러리만 사용.

윈도우의 PowerShell(System.Speech)을 한 번만 띄워 두고 한 줄씩 보낸다 → 매번 켜는 지연이 없고 순서대로 읽는다.
윈도우가 아니거나 음성이 없으면 조용히 아무것도 안 한다 (프로그램 동작에는 영향 없음).
"""
import base64
import queue
import subprocess
import sys
import threading
import time

NAMES = {"BTC": "비트코인", "ETH": "이더리움", "XRP": "리플", "TRX": "트론", "AVAX": "아발란체", "ADA": "에이다",
         "DOGE": "도지", "SOL": "솔라나", "LINK": "체인링크", "DOT": "폴카닷", "HBAR": "헤데라", "BCH": "비트코인캐시",
         "XLM": "스텔라", "NEAR": "니어", "SUI": "수이", "APT": "앱토스", "ETC": "이더리움클래식", "ATOM": "코스모스",
         "ARB": "아비트럼", "POL": "폴리곤", "ONDO": "온도", "UNI": "유니스왑", "AAVE": "에이브"}

DIGITS = "영일이삼사오육칠팔구"


def kname(coin):
    return NAMES.get(coin, " ".join(coin))


def _under_10000(n):
    out = ""
    for unit, word in ((1000, "천"), (100, "백"), (10, "십"), (1, "")):
        d = n // unit % 10
        if d:
            out += ("" if d == 1 and word else DIGITS[d]) + word
    return out


def num_kr(n):
    """정수를 한국어로: 15000 → 만오천, 530 → 오백삼십, 1234567 → 백이십삼만사천오백육십칠."""
    n = int(round(abs(n)))
    if n == 0:
        return "영"
    parts = []
    for unit, word in ((10 ** 8, "억"), (10 ** 4, "만"), (1, "")):
        v = n // unit % 10000
        if v:
            parts.append(("" if v == 1 and word == "만" else _under_10000(v)) + word)
    return "".join(parts)


def won(n):
    return f"{'마이너스 ' if n < 0 else ''}{num_kr(n)} 원"


# 효과음: (주파수 Hz, 길이 ms) 목록
SOUNDS = {"buy": [(880, 110)], "tp": [(880, 90), (1320, 170)], "sell": [(660, 140)], "err": [(440, 260), (440, 260)],
          "info": [(990, 80)]}

PS_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'ko-KR' } | Select-Object -First 1
      if ($v) { $s.SelectVoice($v.VoiceInfo.Name) } } catch {}
$s.Rate = 1
while ($true) {
  $l = [Console]::In.ReadLine()
  if ($l -eq $null) { break }
  $p = $l.Split('|')
  if ($p.Length -lt 2) { continue }
  foreach ($b in $p[0].Split(',')) { if ($b) { $f = $b.Split(':'); try { [Console]::Beep([int]$f[0], [int]$f[1]) } catch {} } }
  $t = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p[1]))
  if ($t) { try { $s.Speak($t) } catch {} }
}
"""


class Speaker(threading.Thread):
    """say(sound, text)를 받아 차례로 읽는다. 한꺼번에 많이 오면(5건 넘게) 종류별 건수로 묶는다."""

    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.proc = None
        self.enabled = sys.platform == "win32"

    def say(self, sound, text):
        if self.enabled:
            self.q.put((sound, text))

    def _line(self, sound, text):
        beeps = ",".join(f"{f}:{d}" for f, d in SOUNDS.get(sound, []))
        return f"{beeps}|{base64.b64encode(text.encode('utf-8')).decode()}\n"

    def _send(self, sound, text):
        for _ in range(2):
            try:
                if self.proc is None or self.proc.poll() is not None:
                    self.proc = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS_SCRIPT],
                                                 stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                 creationflags=0x08000000)  # 창 없이
                self.proc.stdin.write(self._line(sound, text).encode("ascii"))
                self.proc.stdin.flush()
                return
            except (OSError, ValueError):
                self.proc = None
        self.enabled = False  # 음성을 못 쓰는 PC → 조용히 끈다

    def run(self):
        while True:
            items = [self.q.get()]
            time.sleep(0.4)  # 같은 순간에 온 알림은 모아서
            while not self.q.empty():
                items.append(self.q.get_nowait())
            if len(items) > 5:
                count = {}
                for s, _ in items:
                    count[s] = count.get(s, 0) + 1
                word = {"buy": "매수", "tp": "익절", "sell": "매도", "err": "오류", "info": "알림"}
                text = ", ".join(f"{word.get(s, s)} {num_kr(n)}건" for s, n in count.items())
                items = [("err" if "err" in count else "tp" if "tp" in count else "buy", text)]
            for sound, text in items:
                self._send(sound, text)

    def stop(self):
        try:
            if self.proc:
                self.proc.stdin.close()
                self.proc.terminate()
        except OSError:
            pass
