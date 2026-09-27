"""해커톤 발표 자료(SCNU-Lens-발표.pptx, 7장)를 만든다. 구글 드라이브에 올리면 구글 슬라이드로 열린다."""
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent
SHOT = ROOT / "screenshots"
PUB = ROOT.parent / "frontend" / "public"
OUT = ROOT / "SCNU-Lens-발표.pptx"
TMP = ROOT / ".deck-tmp"
TMP.mkdir(exist_ok=True)
SITE = "https://scnuaram.vercel.app"

BLUE = RGBColor(0x00, 0x58, 0xB2)
NAVY = RGBColor(0x0B, 0x25, 0x45)
SKY = RGBColor(0xA9, 0xCB, 0xF2)
SOFT = RGBColor(0xEE, 0xF4, 0xFB)
PAGE = RGBColor(0xF6, 0xF8, 0xFB)
INK = RGBColor(0x1F, 0x23, 0x2B)
MUTED = RGBColor(0x66, 0x6E, 0x7A)
LINE = RGBColor(0xDD, 0xE3, 0xEA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RED = RGBColor(0xD1, 0x43, 0x3A)
REDSOFT = RGBColor(0xFD, 0xEC, 0xEA)
GREEN = RGBColor(0x1E, 0x9E, 0x6A)
GREENSOFT = RGBColor(0xE6, 0xF6, 0xEE)
GRAY = RGBColor(0xB8, 0xC1, 0xCC)
FONT = "Malgun Gothic"

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def bg(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def text(slide, x, y, w, h, runs, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=None):
    """runs: 문자열, 또는 줄 목록(각 줄은 문자열이나 (문자열, {옵션}) 조각 목록)."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    lines = runs if isinstance(runs, list) else [runs]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        pieces = line if isinstance(line, list) else [line]
        for piece in pieces:
            content, opt = (piece, {}) if isinstance(piece, str) else piece
            r = p.add_run()
            r.text = content
            f = r.font
            f.size = Pt(opt.get("size", size))
            f.bold = opt.get("bold", bold)
            f.color.rgb = opt.get("color", color)
            f.name = FONT
            rpr = r._r.get_or_add_rPr()
            for tag in ("a:ea", "a:cs"):
                el = rpr.find(qn(tag))
                if el is None:
                    el = rpr.makeelement(qn(tag), {})
                    rpr.append(el)
                el.set("typeface", FONT)
    return box


def rect(slide, x, y, w, h, color, radius=None, line=None, shadow=False):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                                   Inches(x), Inches(y), Inches(w), Inches(h))
    if radius:
        shape.adjustments[0] = radius
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    if line:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    if not shadow:
        shape.shadow.inherit = False
    return shape


def circle(slide, x, y, d, color, label, size=16, fg=WHITE):
    c = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    c.fill.solid()
    c.fill.fore_color.rgb = color
    c.line.fill.background()
    c.shadow.inherit = False
    text(slide, x, y, d, d, label, size=size, color=fg, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def arrow(slide, x, y, w=0.36, h=0.4, color=GRAY):
    a = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    a.fill.solid()
    a.fill.fore_color.rgb = color
    a.line.fill.background()
    a.shadow.inherit = False


def phone(slide, image, x, y, h):
    """휴대폰 모양: 검은 테두리 안에 캡처(1170x2532)."""
    w = h * 1170 / 2532
    pad = 0.08
    rect(slide, x - pad, y - pad, w + pad * 2, h + pad * 2, RGBColor(0x11, 0x11, 0x14), radius=0.08, shadow=True)
    slide.shapes.add_picture(str(image), Inches(x), Inches(y), Inches(w), Inches(h))
    return w


def browser(slide, image, x, y, w):
    """노트북 화면처럼: 위쪽 주소창 + 화면 캡처."""
    bar = 0.3
    im = Image.open(image)
    h = w * im.height / im.width
    rect(slide, x - 0.06, y - 0.06, w + 0.12, h + bar + 0.12, RGBColor(0x26, 0x2A, 0x33), radius=0.03, shadow=True)
    for i, c in enumerate((RGBColor(0xFF, 0x5F, 0x57), RGBColor(0xFE, 0xBC, 0x2E), RGBColor(0x28, 0xC8, 0x40))):
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.12 + i * 0.18), Inches(y + 0.09), Inches(0.11), Inches(0.11))
        dot.fill.solid(); dot.fill.fore_color.rgb = c; dot.line.fill.background(); dot.shadow.inherit = False
    rect(slide, x + 0.75, y + 0.05, w - 1.0, 0.2, RGBColor(0x3A, 0x3F, 0x4A), radius=0.5)
    text(slide, x + 0.9, y + 0.05, w - 1.3, 0.2, "scnuaram.vercel.app", size=9, color=RGBColor(0xC9, 0xCE, 0xD6), anchor=MSO_ANCHOR.MIDDLE)
    slide.shapes.add_picture(str(image), Inches(x), Inches(y + bar), Inches(w), Inches(h))
    return h + bar


def crop(src, box, name):
    path = TMP / name
    Image.open(src).crop(box).save(path)
    return path


def title(slide, head):
    text(slide, 0.65, 0.5, 12.0, 0.8, head, size=30, bold=True)


def page_no(slide, n):
    text(slide, 12.3, 7.0, 0.5, 0.3, str(n), size=10, color=MUTED, align=PP_ALIGN.RIGHT)


def notes(slide, body):
    slide.notes_slide.notes_text_frame.text = body


# ---------------------------------------------------------------- 1. 표지
s = prs.slides.add_slide(BLANK)
bg(s, NAVY)
text(s, 0.8, 1.55, 7.5, 0.4, "2026 SCNU OSS·AI 해커톤 · 기초 트랙", size=14, bold=True, color=SKY)
s.shapes.add_picture(str(PUB / "icon-512.png"), Inches(0.8), Inches(2.2), Inches(0.95), Inches(0.95))
text(s, 1.95, 2.18, 6.5, 1.0, "SCNU Lens", size=54, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.82, 3.55, 7.3, 1.3, ["흩어진 학교 공지를 한곳에 모아", "나에게 맞는 것만, 마감 전에 알려 주는 앱"],
     size=22, color=WHITE, spacing=6)
text(s, 0.82, 6.2, 7.3, 0.4, "이휴단  ·  scnuaram.vercel.app", size=13, color=SKY)
w = phone(s, SHOT / "2-for-me.png", 9.4, 0.75, 6.0)
notes(s, "안녕하세요, SCNU Lens를 만든 이휴단입니다. "
         "학교 곳곳에 흩어진 공지를 한곳에 모아서, 나에게 맞는 것만 마감 전에 알려 주는 앱입니다.")

# ---------------------------------------------------------------- 2. 문제
s = prs.slides.add_slide(BLANK)
bg(s, PAGE)
title(s, "학교 공지는 한곳에 모여 있지 않습니다")
# 왼쪽: 흩어진 게시판들
rect(s, 0.65, 1.6, 5.6, 4.6, WHITE, radius=0.05, line=LINE)
chips = [("학사공지", 0.95, 1.95), ("장학공지", 3.05, 2.05), ("취업지원센터", 4.1, 2.75),
         ("컴퓨터공학과", 1.1, 2.8), ("간호학과", 2.85, 3.5), ("식품공학과", 0.9, 3.75),
         ("큐넷 시험 일정", 3.55, 4.25), ("창업 지원 사업", 1.05, 4.7), ("국제교류", 3.2, 5.05),
         ("데이터자격검정", 0.95, 5.55), ("학생생활관", 3.9, 5.55)]
for label, x, y in chips:
    cw = 0.32 + len(label) * 0.19
    rect(s, x, y, cw, 0.42, SOFT, radius=0.5)
    text(s, x, y, cw, 0.42, label, size=12, color=BLUE, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.65, 6.35, 5.6, 0.4, [[("109곳", {"bold": True, "color": BLUE}), " 학교 게시판  +  공모전·자격증 사이트"]],
     size=15, align=PP_ALIGN.CENTER)
# 오른쪽: 그래서 생기는 일
pains = [
    ("어디서 봐야 할지 모름", "본부·학과·기관 게시판을\n하나씩 들어가 봐야 함", WHITE, BLUE),
    ("나에게 해당되는지 모름", "대상·마감일은 긴 본문과\nHWP·PDF 첨부 속에", WHITE, BLUE),
    ("마감이 지나서야 앎", "장학금·공모전·채용\n기회를 놓침", REDSOFT, RED),
]
for i, (head, body, fill, accent) in enumerate(pains):
    y = 1.6 + i * 1.6
    rect(s, 6.75, y, 5.95, 1.35, fill, radius=0.08, line=None if fill == REDSOFT else LINE)
    circle(s, 7.05, y + 0.4, 0.55, accent, str(i + 1), size=15)
    text(s, 7.85, y + 0.25, 4.7, 0.45, head, size=19, bold=True)
    text(s, 7.85, y + 0.72, 4.7, 0.6, body.replace("\n", " "), size=13, color=MUTED)
page_no(s, 2)
notes(s, "순천대 공지는 학사, 장학, 학과, 기관 게시판까지 109곳에 흩어져 있고, 공모전과 자격증 일정은 또 다른 사이트에 있습니다. "
         "게다가 나에게 해당되는지, 언제까지인지는 긴 본문과 첨부파일 속에 있어서, 결국 마감이 지나서야 알게 됩니다.")

# ---------------------------------------------------------------- 3. 해결 (앱 흐름)
s = prs.slides.add_slide(BLANK)
bg(s, PAGE)
title(s, "그래서, 나에게 맞는 공지만 골라 주는 앱을 만들었습니다")
steps = [
    ("1-onboarding.png", "30초 설정", "학과는 '컴공'처럼 줄여 써도 OK"),
    ("2-for-me.png", "나에게 맞는 공지", "왜 추천했는지 이유까지"),
    ("3-detail.png", "한 장으로 정리", "대상·기간·신청방법·문의"),
    ("4-calendar.png", "마감 전에 알림", "7·3·1일 전 휴대폰으로"),
]
ph = 4.15
pw = ph * 1170 / 2532
for i, (img, head, sub) in enumerate(steps):
    x = 0.95 + i * 3.1
    phone(s, SHOT / img, x + 0.3, 1.75, ph)
    circle(s, x - 0.05, 1.5, 0.5, BLUE, str(i + 1), size=15)
    text(s, x - 0.3, 6.1, pw + 1.2, 0.45, head, size=18, bold=True, align=PP_ALIGN.CENTER)
    text(s, x - 0.3, 6.55, pw + 1.2, 0.4, sub, size=12, color=MUTED, align=PP_ALIGN.CENTER)
    if i < 3:
        arrow(s, x + pw + 0.62, 3.65)
page_no(s, 3)
notes(s, "처음 들어오면 학과와 관심사를 30초 만에 고릅니다. 학과는 '컴공'처럼 줄여 써도 찾아 줍니다. "
         "그러면 나에게 맞는 공지를 이유와 함께 보여 주고, 누르면 대상·기간·신청방법이 한 장으로 정리돼 있습니다. "
         "마감 7일, 3일, 1일 전에는 휴대폰으로 알려 줍니다.")

# ---------------------------------------------------------------- 4. AI 정리
s = prs.slides.add_slide(BLANK)
bg(s, PAGE)
title(s, "AI는 이렇게 긴 공지를 정리합니다")
# 1) 원문
circle(s, 0.65, 1.55, 0.45, BLUE, "1", size=14)
text(s, 1.2, 1.58, 3.2, 0.4, "학교 공지 원문", size=16, bold=True)
rect(s, 0.65, 2.2, 3.55, 3.3, WHITE, radius=0.05, line=LINE)
for k, lw in enumerate((3.0, 2.7, 3.1, 2.2, 2.9, 3.0, 1.9, 2.8, 2.5)):
    rect(s, 0.9, 2.45 + k * 0.25, lw, 0.1, LINE, radius=0.5)
for k, ext in enumerate(("첨부.hwp", "안내.pdf")):
    rect(s, 0.9 + k * 1.45, 4.85, 1.3, 0.4, SOFT, radius=0.5)
    text(s, 0.9 + k * 1.45, 4.85, 1.3, 0.4, ext, size=11, bold=True, color=BLUE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
arrow(s, 4.35, 3.6)
# 2) AI 판단
circle(s, 4.9, 1.55, 0.45, BLUE, "2", size=14)
text(s, 5.45, 1.58, 3.0, 0.4, "AI가 읽고 판단", size=16, bold=True)
tags = [("분야", "장학 · 취업 · 공모전 · 자격증 …"), ("대상", "대학원생, 재학생, 신입생"),
        ("마감", "10. 23.(금)  →  D-26"), ("중복", "같은 공지는 하나로")]
for k, (tag, body) in enumerate(tags):
    y = 2.2 + k * 0.84
    rect(s, 4.9, y, 3.35, 0.68, WHITE, radius=0.12, line=LINE)
    text(s, 5.1, y, 0.7, 0.68, tag, size=12, bold=True, color=BLUE, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 5.8, y, 2.4, 0.68, body, size=12, anchor=MSO_ANCHOR.MIDDLE)
arrow(s, 8.4, 3.6)
# 3) 정리 카드
circle(s, 8.95, 1.55, 0.45, BLUE, "3", size=14)
text(s, 9.5, 1.58, 3.2, 0.4, "한 장으로 정리", size=16, bold=True)
card = crop(SHOT / "3-detail.png", (40, 380, 1130, 1760), "detail-card.png")
cw = 3.75
chh = cw * 1380 / 1090
rect(s, 8.95 - 0.05, 2.2 - 0.05, cw + 0.1, chh + 0.1, LINE, radius=0.03)
s.shapes.add_picture(str(card), Inches(8.95), Inches(2.2), Inches(cw), Inches(chh))
# 아래 강조
rect(s, 0.65, 5.85, 7.6, 1.0, WHITE, radius=0.12, line=LINE)
text(s, 0.95, 5.85, 1.5, 1.0, "0원", size=36, bold=True, color=BLUE, anchor=MSO_ANCHOR.MIDDLE)
text(s, 2.5, 5.95, 5.6, 0.8, [[("유료 AI 서비스 없이", {"bold": True})], "공개 AI 모델을 우리 서버 안에서 돌려요"],
     size=13, anchor=MSO_ANCHOR.MIDDLE, spacing=2)
page_no(s, 4)
notes(s, "AI가 공지 본문과 첨부파일을 읽고, 어떤 분야인지, 누가 대상인지, 언제 마감인지를 뽑아서 한 장의 카드로 정리합니다. "
         "여러 게시판에 같은 공지가 올라오면 하나로 합칩니다. 유료 AI 서비스 없이 공개된 AI 모델을 서버 안에서 돌리기 때문에 비용은 0원입니다.")

# ---------------------------------------------------------------- 5. 실제 운영
s = prs.slides.add_slide(BLANK)
bg(s, PAGE)
title(s, "지금 실제로 매시간 돌아가고 있습니다")
browser(s, crop(SHOT / "desktop" / "2-for-me.png", (480, 0, 1680, 800), "desktop-for-me.png"), 0.8, 1.65, 6.5)
stats = [("109곳", "학교 게시판을\n매시간 확인"), ("3종", "큐넷·데이터자격·\nK-Startup 공공 API"),
         ("70개", "학과 목록에서\n골라서 추천"), ("0원", "서버·AI\n운영 비용")]
for i, (big, label) in enumerate(stats):
    x = 8.2 + (i % 2) * 2.3
    y = 1.65 + (i // 2) * 2.35
    rect(s, x, y, 2.1, 2.1, WHITE, radius=0.08, line=LINE)
    text(s, x, y + 0.3, 2.1, 0.8, big, size=32, bold=True, color=BLUE, align=PP_ALIGN.CENTER)
    text(s, x + 0.1, y + 1.15, 1.9, 0.8, label, size=12, color=MUTED, align=PP_ALIGN.CENTER)
text(s, 0.7, 6.6, 12.0, 0.4, "휴대폰에서도, 컴퓨터에서도 같은 주소로 열립니다. 설치 없이 '홈 화면에 추가'하면 앱처럼 씁니다.",
     size=14, bold=True, align=PP_ALIGN.CENTER)
page_no(s, 5)
notes(s, "지금 이 순간에도 학교 게시판 109곳과 공공 API 3종을 매시간 확인하고 있습니다. "
         "컴퓨터에서도 휴대폰에서도 같은 주소로 열리고, 설치 없이 홈 화면에 추가하면 앱처럼 쓸 수 있습니다.")

# ---------------------------------------------------------------- 6. 앞으로
s = prs.slides.add_slide(BLANK)
bg(s, PAGE)
title(s, "학생들이 쓸수록 더 정확해집니다")
plans = [
    ("지금", "누구나 쓸 수 있는 웹앱", "매시간 수집, 추천, 마감 알림까지\n실제 주소에서 운영 중입니다.", WHITE, INK, LINE),
    ("다음", "학생 의견으로 다듬기", "지역 한정 공고 표시, 추천이 빗나간\n공지를 모아 규칙을 고칩니다.", SOFT, BLUE, None),
    ("나중에", "다른 학과·다른 학교로", "같은 게시판 시스템을 쓰는 곳이면\n주소만 추가해 넓힐 수 있습니다.", GREENSOFT, GREEN, None),
]
for i, (when, head, body, fill, accent, line) in enumerate(plans):
    x = 0.65 + i * 4.2
    rect(s, x, 2.2, 3.8, 2.9, fill, radius=0.06, line=line)
    text(s, x + 0.35, 2.5, 3.1, 0.4, when, size=14, bold=True, color=accent)
    text(s, x + 0.35, 3.0, 3.2, 0.6, head, size=20, bold=True)
    text(s, x + 0.35, 3.8, 3.2, 1.8, body, size=14, color=MUTED, spacing=2)
    if i < 2:
        arrow(s, x + 3.83, 3.45, w=0.32)
text(s, 0.65, 5.75, 12.0, 0.5, "학교 사이트를 바꿀 필요 없이, 이미 있는 게시판을 그대로 읽습니다.",
     size=18, bold=True, align=PP_ALIGN.CENTER)
page_no(s, 6)
notes(s, "지금은 누구나 쓸 수 있는 웹앱으로 운영 중입니다. 다음으로는 학생들의 의견을 받아, 예를 들어 지역 한정 공고를 표시하고 "
         "추천이 빗나간 공지를 모아 규칙을 고치려고 합니다. 학교 사이트를 바꿀 필요 없이 이미 있는 게시판을 읽기 때문에, "
         "같은 게시판 시스템을 쓰는 곳이라면 쉽게 넓힐 수 있습니다.")

# ---------------------------------------------------------------- 7. 마무리 + 시연
s = prs.slides.add_slide(BLANK)
bg(s, NAVY)
text(s, 0.8, 0.9, 6.0, 0.4, "감사합니다", size=16, bold=True, color=SKY)
text(s, 0.8, 1.6, 7.5, 1.9, ["휴대폰으로", "직접 써 보세요"], size=46, bold=True, color=WHITE)
text(s, 0.82, 3.75, 7.5, 0.9, ["카메라로 오른쪽 QR을 찍으면 바로 열립니다.", "학과를 고르면 30초 안에 나에게 맞는 공지가 보여요."],
     size=15, color=WHITE, spacing=4)
btn = rect(s, 0.82, 4.95, 3.3, 0.7, GREEN, radius=0.5)
btn.click_action.hyperlink.address = SITE
text(s, 0.82, 4.95, 3.3, 0.7, "▶  지금 시연해 볼게요", size=17, bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.82, 6.1, 1.2, 0.3, "바로 가기", size=12, bold=True, color=SKY)
text(s, 2.0, 6.1, 5.5, 0.3, "scnuaram.vercel.app", size=12, color=WHITE)
text(s, 0.82, 6.5, 1.2, 0.3, "소스 코드", size=12, bold=True, color=SKY)
text(s, 2.0, 6.5, 5.5, 0.3, "github.com/GOBIEBERPA/scnu-lens", size=12, color=WHITE)
rect(s, 8.9, 1.5, 3.6, 3.6, WHITE, radius=0.06)
qr = s.shapes.add_picture(str(ROOT / "qr-scnuaram.png"), Inches(9.1), Inches(1.7), Inches(3.2), Inches(3.2))
qr.click_action.hyperlink.address = SITE
text(s, 8.9, 5.3, 3.6, 0.4, "scnuaram.vercel.app", size=13, color=SKY, align=PP_ALIGN.CENTER)
notes(s, "화면의 QR을 찍으시면 바로 써 보실 수 있습니다. 지금 시연해 보겠습니다. (초록 버튼을 누르면 사이트가 열립니다) 감사합니다.")

prs.save(OUT)
print("saved", OUT)
