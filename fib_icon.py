"""TJ 트레이딩 아이콘: 어두운 바탕 + 오르는 캔들 3개 + 큰 TJ 글자. 트레이·창·바탕화면 아이콘에 같이 쓴다.

글꼴 없이 도형으로 그려서 어느 PC에서나 똑같이 보인다. 크게 그린 뒤 줄여서 작은 크기(16px)에서도 매끈하게.
"""
from PIL import Image, ImageDraw

BG = (18, 28, 38)          # GROUND
EDGE = (89, 128, 166)      # ACCENT
ALERT = (240, 113, 106)    # UP (빨강)
UP = (240, 113, 106)
DOWN = (148, 188, 227)
TEXT = (255, 255, 255)


def make(size=64, alert=False):
    k = 8 * size / 64  # 64칸 기준 좌표 → 8배로 그린 뒤 줄임
    big = int(64 * k)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = lambda *v: [round(x * k) for x in v]  # noqa: E731
    d.rounded_rectangle(s(1, 1, 63, 63), radius=round(12 * k), fill=BG, outline=ALERT if alert else EDGE, width=round(3 * k))
    # 오르는 캔들 3개 (오른쪽 위): 파랑(하락) → 빨강 → 빨강
    for x, wick, body, col in ((38, (17, 33), (21, 29), DOWN), (47, (11, 27), (14, 23), UP), (56, (4, 20), (7, 16), UP)):
        d.rectangle(s(x - 0.8, wick[0], x + 0.8, wick[1]), fill=col)
        d.rectangle(s(x - 3, body[0], x + 3, body[1]), fill=col)
    # T
    d.rectangle(s(6, 31, 29, 37), fill=TEXT)
    d.rectangle(s(14.5, 31, 20.5, 58), fill=TEXT)
    # J
    d.rectangle(s(32, 31, 47, 37), fill=TEXT)
    d.rectangle(s(40, 31, 46, 52), fill=TEXT)
    d.rounded_rectangle(s(30, 47, 46, 58), radius=round(5 * k), fill=TEXT)
    d.rectangle(s(36, 47, 40, 52), fill=BG)  # J 갈고리 안쪽
    d.rectangle(s(30, 44, 36, 51), fill=TEXT)
    if alert:  # 알림: 왼쪽 위 빨간 점
        d.ellipse(s(4, 4, 19, 19), fill=ALERT, outline=BG, width=round(2 * k))
    return img.resize((size, size), Image.LANCZOS)


def save_ico(path):
    """바탕화면 바로가기용 .ico (여러 크기 한 파일)."""
    make(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def save_png(path, size=64):
    make(size).save(path)
