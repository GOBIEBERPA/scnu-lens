"""작품 등록용 소개 이미지 5장(1600x1000)을 만든다: 왼쪽 큰 문구, 오른쪽 휴대폰+웹 화면."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
SHOT = ROOT / "screenshots"
OUT = ROOT / "promo"
OUT.mkdir(exist_ok=True)
W, H = 1600, 1000
BOLD = "C:/Windows/Fonts/malgunbd.ttf"
REG = "C:/Windows/Fonts/malgun.ttf"
WHITE = (255, 255, 255)
SKY = (110, 180, 255)
ACCENT = (61, 220, 151)
YELLOW = (250, 199, 58)
DIM = (196, 204, 220)


def font(path, size):
    return ImageFont.truetype(path, size)


def background() -> Image.Image:
    img = Image.new("RGB", (W, H), (17, 24, 39))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse((700, -300, 1900, 900), fill=(28, 52, 96))
    d.ellipse((-400, 500, 700, 1400), fill=(22, 34, 60))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.blend(img, glow, 0.85)


def rounded(im: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius, fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask)
    return out


def shadow(base: Image.Image, box, radius, blur=28, alpha=150):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle((x0, y0 + 18, x1, y1 + 18), radius, fill=(0, 0, 0, alpha))
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def desktop(base, path, x, y, w, crop_top=0.0):
    shot = Image.open(path).convert("RGB")
    if crop_top:
        shot = shot.crop((0, int(shot.height * crop_top), shot.width, shot.height))
    h = int(shot.height * w / shot.width)
    shot = shot.resize((w, h), Image.LANCZOS)
    frame = Image.new("RGBA", (w + 16, h + 16), (44, 52, 70, 255))
    frame = rounded(frame, 22)
    shadow(base, (x, y, x + w + 16, y + h + 16), 22)
    base.alpha_composite(frame, (x, y))
    base.alpha_composite(rounded(shot, 14), (x + 8, y + 8))


def phone(base, path, x, y, h):
    shot = Image.open(path).convert("RGB")
    w = int(shot.width * h / shot.height)
    shot = shot.resize((w, h), Image.LANCZOS)
    pad = 12
    body = rounded(Image.new("RGBA", (w + pad * 2, h + pad * 2), (8, 8, 12, 255)), 46)
    shadow(base, (x, y, x + w + pad * 2, y + h + pad * 2), 46, blur=34, alpha=190)
    base.alpha_composite(body, (x, y))
    base.alpha_composite(rounded(shot, 36), (x + pad, y + pad))
    return w + pad * 2


def pill(base, text, right, y, size=46):
    f = font(BOLD, size)
    d = ImageDraw.Draw(base)
    tw = d.textlength(text, font=f)
    x1 = right
    x0 = x1 - tw - 70
    shadow(base, (x0, y, x1, y + size + 42), 40, blur=18, alpha=120)
    d.rounded_rectangle((x0, y, x1, y + size + 42), radius=(size + 42) // 2, fill=YELLOW)
    d.text((x0 + 35, y + 17), text, font=f, fill=(34, 30, 20))


def headline(d, lines, x, y, size=90):
    """lines: [[(조각, 강조여부), ...], ...]"""
    f = font(BOLD, size)
    for i, parts in enumerate(lines):
        cx = x
        for part, hot in parts:
            d.text((cx, y + i * int(size * 1.16)), part, font=f, fill=ACCENT if hot else WHITE)
            cx += d.textlength(part, font=f)


def card(name, label, lines, sub, draw_right, caption=None, badge=None):
    img = background().convert("RGBA")
    d = ImageDraw.Draw(img)
    d.text((90, 112), label, font=font(BOLD, 34), fill=SKY)
    headline(d, lines, 86, 175)
    for i, line in enumerate(sub):
        d.text((92, 440 + i * 52), line, font=font(REG, 31), fill=DIM)
    draw_right(img)
    if badge:
        pill(img, badge, 1480, 700)
    if caption:
        f = font(REG, 32)
        d = ImageDraw.Draw(img)
        d.text((1480 - d.textlength(caption, font=f), 800), caption, font=f, fill=DIM)
    # 왼쪽 아래 앱 표시
    logo = Image.open(ROOT.parent / "frontend" / "public" / "icon-192.png").convert("RGBA").resize((56, 56), Image.LANCZOS)
    img.alpha_composite(rounded(logo, 12), (92, 872))
    d = ImageDraw.Draw(img)
    d.text((164, 878), "SCNU Lens", font=font(BOLD, 30), fill=WHITE)
    d.text((340, 882), "scnuaram.vercel.app", font=font(REG, 26), fill=DIM)
    img.convert("RGB").save(OUT / name, quality=92)
    print("saved", name)


# 1. 대표(썸네일)
def right1(img):
    desktop(img, SHOT / "desktop" / "2-for-me.png", 1010, 180, 500)
    phone(img, SHOT / "2-for-me.png", 780, 120, 620)
    d = ImageDraw.Draw(img)
    for i, (num, lab) in enumerate((("109", "학교 게시판"), ("70", "학과"), ("0원", "AI 비용"))):
        x = 1110 + i * 165
        d.text((x, 590), num, font=font(BOLD, 56), fill=ACCENT)
        d.text((x, 662), lab, font=font(REG, 26), fill=DIM)


card("1-scnu-lens.png", "순천대 AI 통합 알리미",
     [[("흩어진 공지를", False)], [("한곳에서", True)]],
     ["학교 게시판 109곳과", "공모전·자격증을 매시간 모아", "나에게 맞는 것만", "마감 전에 알려드려요"],
     right1)


# 2. 30초 설정
def right2(img):
    desktop(img, SHOT / "desktop" / "1-onboarding.png", 1010, 180, 500)
    phone(img, SHOT / "1-onboarding.png", 780, 120, 620)


card("2-onboarding.png", "30초 설정",
     [[("‘컴공’", True), ("만 쳐도", False)], [("내 학과를", False)]],
     ["줄임말·초성으로 찾고,", "목록에서만 골라서", "오타로 추천이 깨지지 않아요"],
     right2, caption="학과·관심사·알림을 한 화면에서", badge="컴공 → 컴퓨터공학전공")


# 3. 나에게
def right3(img):
    desktop(img, SHOT / "desktop" / "2-for-me.png", 1010, 180, 500)
    phone(img, SHOT / "2-for-me.png", 780, 120, 620)
    # 추천 이유 줄을 확대해서 보여준다
    shot = Image.open(SHOT / "2-for-me.png").convert("RGB")
    zoom = shot.crop((30, 395, 1140, 700)).resize((480, 132), Image.LANCZOS)
    box = Image.new("RGBA", (500, 152), (255, 255, 255, 255))
    box = rounded(box, 20)
    shadow(img, (1010, 540, 1510, 692), 20)
    img.alpha_composite(box, (1010, 540))
    img.alpha_composite(rounded(zoom, 12), (1020, 550))


card("3-for-me.png", "나에게",
     [[("왜", True), (" 추천했는지", False)], [("알려줘요", False)]],
     ["내 학과 게시판 공지를 먼저,", "관심 키워드와 겹치는 이유까지", "문장으로 보여줘요"],
     right3, caption="결과 발표·스친 단어는 추천 안 함")


# 4. 정리 카드
def right4(img):
    desktop(img, SHOT / "desktop" / "3-detail.png", 1010, 180, 500)
    phone(img, SHOT / "3-detail.png", 780, 120, 620)


card("4-detail.png", "정리 카드",
     [[("긴 공지를", False)], [("한 장", True), ("으로", False)]],
     ["본문·첨부(HWP·PDF)에서", "대상·기간·신청방법·문의만", "뽑아 표로 정리해요"],
     right4, caption="신청 링크는 바로 누르기", badge="D-26 · 알림 7·3·1일 전")


# 5. 캘린더·알림
def right5(img):
    desktop(img, SHOT / "desktop" / "4-calendar.png", 1010, 180, 500)
    phone(img, SHOT / "4-calendar.png", 780, 120, 620)


card("5-calendar.png", "캘린더 · 알림",
     [[("마감을", False)], [("놓치지 않게", True)]],
     ["마감일·시험일·발표일을 달력으로,", "마감 7·3·1일 전·접수 시각에", "휴대폰으로 알려줘요"],
     right5, caption="설치 없는 웹 푸시 · 밤에는 모아서 아침에", badge="오늘 마감")
