"""해커톤 발표 자료(SCNU-Lens-발표.pptx)를 만든다. 구글 드라이브에 올리면 구글 슬라이드로 열린다."""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent
SHOT = ROOT / "screenshots"
PUB = ROOT.parent / "frontend" / "public"
OUT = ROOT / "SCNU-Lens-발표.pptx"

BLUE = RGBColor(0x00, 0x58, 0xB2)
NAVY = RGBColor(0x0B, 0x25, 0x45)
SKY = RGBColor(0xCF, 0xE4, 0xFB)
SOFT = RGBColor(0xEE, 0xF4, 0xFB)
INK = RGBColor(0x1F, 0x1D, 0x1A)
MUTED = RGBColor(0x6B, 0x68, 0x62)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ORANGE = RGBColor(0xC8, 0x4B, 0x31)
FRAME = RGBColor(0x26, 0x2A, 0x33)
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


def circle(slide, x, y, d, color, label, size=18, fg=WHITE):
    c = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    c.fill.solid()
    c.fill.fore_color.rgb = color
    c.line.fill.background()
    c.shadow.inherit = False
    text(slide, x, y, d, d, label, size=size, color=fg, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def browser(slide, image, x, y, w):
    """노트북 화면처럼: 위쪽 주소창 + 화면 캡처(16:10)."""
    bar = 0.3
    h = w * 1350 / 2160
    rect(slide, x - 0.06, y - 0.06, w + 0.12, h + bar + 0.12, FRAME, radius=0.03, shadow=True)
    for i, c in enumerate((RGBColor(0xFF, 0x5F, 0x57), RGBColor(0xFE, 0xBC, 0x2E), RGBColor(0x28, 0xC8, 0x40))):
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.12 + i * 0.18), Inches(y + 0.09), Inches(0.11), Inches(0.11))
        dot.fill.solid(); dot.fill.fore_color.rgb = c; dot.line.fill.background(); dot.shadow.inherit = False
    rect(slide, x + 0.75, y + 0.05, w - 1.0, 0.2, RGBColor(0x3A, 0x3F, 0x4A), radius=0.5)
    text(slide, x + 0.9, y + 0.05, w - 1.3, 0.2, "scnuaram.vercel.app", size=9, color=RGBColor(0xC9, 0xCE, 0xD6), anchor=MSO_ANCHOR.MIDDLE)
    slide.shapes.add_picture(str(image), Inches(x), Inches(y + bar), Inches(w), Inches(h))
    return h + bar


def phone(slide, image, x, y, h):
    """휴대폰 모양: 검은 테두리 안에 캡처(1170x2532)."""
    w = h * 1170 / 2532
    pad = 0.09
    rect(slide, x - pad, y - pad, w + pad * 2, h + pad * 2, RGBColor(0x11, 0x11, 0x14), radius=0.09, shadow=True)
    slide.shapes.add_picture(str(image), Inches(x), Inches(y), Inches(w), Inches(h))
    return w


def title(slide, head, sub=None, dark=False):
    text(slide, 0.6, 0.45, 12.1, 0.7, head, size=32, bold=True, color=WHITE if dark else INK)
    if sub:
        text(slide, 0.6, 1.12, 12.1, 0.45, sub, size=16, color=SKY if dark else MUTED)


def callouts(slide, x, y, w, items):
    """번호 원 + 굵은 한 줄 + 설명."""
    for i, (head, body) in enumerate(items):
        top = y + i * 1.55
        circle(slide, x, top, 0.42, BLUE, str(i + 1), size=15)
        text(slide, x + 0.55, top - 0.02, w - 0.55, 0.45, head, size=15, bold=True)
        text(slide, x + 0.55, top + 0.42, w - 0.55, 1.0, body, size=12, color=MUTED)


# ---------------------------------------------------------------- 1. 표지
s = prs.slides.add_slide(BLANK)
bg(s, NAVY)
s.shapes.add_picture(str(PUB / "icon-512.png"), Inches(0.75), Inches(1.35), Inches(1.15), Inches(1.15))
text(s, 0.75, 2.75, 7.2, 1.0, "SCNU Lens", size=60, bold=True, color=WHITE)
text(s, 0.78, 3.8, 7.2, 0.6, "순천대 AI 통합 알리미", size=26, bold=True, color=SKY)
text(s, 0.78, 4.6, 7.0, 1.1, ["흩어진 학교 공지 100여 곳과 공모전·자격증 일정을 모아", "나에게 해당되는 것만, 마감 전에 알려드려요"], size=17, color=WHITE, spacing=4)
text(s, 0.78, 6.35, 7.0, 0.4, [[("scnuaram.vercel.app", {"bold": True, "color": WHITE}), ("   ·   2026 SCNU OSS·AI 해커톤 · 기초 트랙 · 이휴단", {"color": SKY})]], size=13)
phone(s, SHOT / "2-for-me.png", 9.35, 0.7, 6.1)
s.notes_slide.notes_text_frame.text = (
    "안녕하세요, 순천대 AI 통합 알리미 SCNU Lens를 만든 이휴단입니다. "
    "학교 공지를 하나로 모아서, 나에게 해당되는 것만 마감 전에 알려주는 모바일 웹앱입니다.")

# ---------------------------------------------------------------- 2. 문제
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "공지는 많은데, 내 것은 안 보입니다", "순천대 학생이 공지를 확인하는 지금의 방법")
cards = [
    ("100+", "게시판이 흩어져 있다", "학사·장학 본부 게시판, 학과·부속기관 게시판 100곳 넘게, 공모전·자격증은 또 다른 사이트"),
    ("중복·첨부", "정보가 묻혀 있다", "같은 공지가 여러 게시판에 중복. 마감일·신청 방법은 본문과 HWP·PDF 첨부 속에"),
    ("마감", "그래서 놓친다", "\"이게 나에게 해당되나?\" \"언제까지지?\"를 바로 알 수 없어 장학·취업·공모전 기회를 지나친다"),
]
for i, (big, head, body) in enumerate(cards):
    x = 0.6 + i * 4.1
    rect(s, x, 2.0, 3.8, 3.9, SOFT, radius=0.06)
    text(s, x + 0.35, 2.35, 3.2, 1.0, big, size=44 if i < 2 else 48, bold=True, color=ORANGE if i == 2 else BLUE)
    text(s, x + 0.35, 3.55, 3.2, 0.5, head, size=20, bold=True)
    text(s, x + 0.35, 4.2, 3.15, 2.2, body, size=14, color=MUTED)
s.notes_slide.notes_text_frame.text = (
    "순천대 공지는 학사, 장학, 그리고 학과 게시판까지 100곳 넘게 흩어져 있습니다. "
    "같은 공지가 여러 번 올라오고, 정작 마감일과 신청 방법은 첨부파일 속에 있죠. "
    "그래서 나에게 해당되는지, 언제까지인지 모르고 기회를 놓칩니다.")

# ---------------------------------------------------------------- 3. 해결 흐름
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "모으고, 정리하고, 골라서, 알려줍니다", "사람이 할 일은 처음 30초 설정뿐")
steps = [
    ("수집", "매시간 자동", "학교 게시판 109곳\n+ 큐넷·데이터자격검정·K-Startup API"),
    ("AI 정리", "서버 안 AI 모델", "분야 분류, 대상·기간·신청방법·문의를\n정리 카드로, 중복 공지는 하나로"),
    ("나에게", "추천 + 이유", "학과·관심사로 점수를 매기고\n\"왜 나에게 해당되는지\" 문장으로"),
    ("알림", "마감 전", "마감 7·3·1일 전, 접수 시각에\n웹 푸시와 알림함으로"),
]
for i, (head, tag, body) in enumerate(steps):
    x = 0.6 + i * 3.15
    rect(s, x, 2.1, 2.8, 4.3, SOFT, radius=0.06)
    circle(s, x + 0.3, 2.45, 0.7, BLUE, str(i + 1), size=22)
    text(s, x + 0.3, 3.4, 2.3, 0.5, head, size=22, bold=True)
    text(s, x + 0.3, 3.95, 2.3, 0.4, tag, size=13, bold=True, color=BLUE)
    text(s, x + 0.3, 4.5, 2.35, 1.8, body, size=13, color=MUTED)
    if i < 3:
        arrow = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x + 2.83), Inches(4.05), Inches(0.28), Inches(0.35))
        arrow.fill.solid(); arrow.fill.fore_color.rgb = SKY; arrow.line.fill.background(); arrow.shadow.inherit = False
s.notes_slide.notes_text_frame.text = (
    "SCNU Lens는 네 단계로 동작합니다. 학교 게시판 109곳과 공공데이터 API를 매시간 모으고, "
    "서버 안의 AI 모델로 분류하고 정리 카드를 만듭니다. 그리고 학과와 관심사로 골라 이유와 함께 보여주고, 마감 전에 알려줍니다.")


# ---------------------------------------------------------------- 4~6. 시연 (웹 + 휴대폰)
def demo(head, sub, web_img, phone_img, items, notes):
    s = prs.slides.add_slide(BLANK)
    bg(s, WHITE)
    title(s, head, sub)
    browser(s, web_img, 0.65, 1.95, 6.6)
    phone(s, phone_img, 7.75, 1.85, 5.2)
    callouts(s, 10.45, 2.05, 2.5, items)
    s.notes_slide.notes_text_frame.text = notes


demo("① 30초 설정 — 학과는 고르기만", "웹과 휴대폰에서 똑같이 동작합니다",
     SHOT / "desktop" / "1-onboarding.png", SHOT / "1-onboarding.png",
     [("줄임말·초성 검색", "'컴공' → 컴퓨터공학전공\n'ㄱㅎ' → 간호학과"),
      ("목록에서만 선택", "오타로 학과 매칭이\n깨지지 않게"),
      ("알림도 한 번에", "휴대폰 알림을 켜면\n마감 전에 알려줌")],
     "처음 접속하면 30초 설정이 뜹니다. 학과는 70개 목록에서만 고르게 해서 오타로 매칭이 깨지지 않게 했고, "
     "학생들이 쓰는 '컴공' 같은 줄임말이나 초성으로도 찾을 수 있습니다.")
demo("② 나에게 — 왜 추천했는지 알려줍니다", "식품공학전공 · 관심사 '장학금, 취업'으로 설정한 화면",
     SHOT / "desktop" / "2-for-me.png", SHOT / "2-for-me.png",
     [("추천 이유 표시","\"관심 키워드 '장학금, 취업'과\n관련된 공지예요\""),
      ("내 학과 게시판 우선", "109곳 중 내 과 소식을\n가장 먼저"),
      ("헛추천은 거른다", "결과·수상자 발표, 본문에\n한 번 스친 단어는 제외")],
     "나에게 탭입니다. 공지마다 왜 추천했는지 파란 문장으로 보여줍니다. 내 학과 게시판 공지가 가장 먼저 오고, "
     "이미 끝난 결과 발표나 본문에 한 번 스친 단어로는 추천하지 않도록 다듬었습니다.")
demo("③ 정리 카드와 캘린더", "본문·첨부파일에서 필요한 칸만 뽑아 보여줍니다",
     SHOT / "desktop" / "4-calendar.png", SHOT / "3-detail.png",
     [("정리 카드", "대상·기간·신청방법·문의를\n표로, 링크는 바로 누르기"),
      ("마감 알림 예정", "7·3·1일 전 알림 시각을\n미리 보여줌"),
      ("캘린더", "마감일·시험일·발표일\nD-3 마감 / 오늘 마감")],
     "공지를 누르면 대상, 기간, 신청방법, 문의가 정리된 카드가 열리고, 언제 알림이 갈지도 미리 보여줍니다. "
     "캘린더에서는 이번 달 마감일과 시험일을 한눈에 볼 수 있습니다.")

# ---------------------------------------------------------------- 7. 차별점
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "다른 알리미와 다른 점")
points = [
    ("학과 게시판 109곳 자동 탐색", "학교 사이트가 같은 게시판 엔진을 쓴다는 점을 이용해 게시판 주소를 스스로 찾아 한 번에 수집"),
    ("AI 비용 0원, 외부 전송 없음", "유료 AI API 없이 오픈소스 경량 모델(MiniLM)을 서버에서 직접 실행. 공지 원문이 밖으로 나가지 않음"),
    ("\"왜 나에게?\"를 설명", "블랙박스 추천이 아니라 근거(내 학과 게시판, 관심 키워드)를 문장으로 제시"),
    ("실제로 써 보며 다듬은 규칙", "신청기간과 운영기간 구분, '신청 시작'은 마감 아님, 다른 지역 한정 공고 제외"),
]
for i, (head, body) in enumerate(points):
    x = 0.6 + (i % 2) * 6.15
    y = 1.7 + (i // 2) * 2.7
    rect(s, x, y, 5.85, 2.4, SOFT, radius=0.06)
    circle(s, x + 0.35, y + 0.4, 0.6, BLUE, str(i + 1), size=20)
    text(s, x + 1.2, y + 0.42, 4.4, 0.6, head, size=19, bold=True)
    text(s, x + 1.2, y + 1.1, 4.35, 1.2, body, size=14, color=MUTED)
s.notes_slide.notes_text_frame.text = (
    "차별점은 네 가지입니다. 학과 게시판 109곳을 자동으로 찾아 모으고, 유료 AI 없이 서버에서 직접 모델을 돌려 비용이 0원입니다. "
    "추천 이유를 설명하고, 실제로 써 보면서 신청기간과 운영기간을 구분하는 등 규칙을 다듬었습니다.")

# ---------------------------------------------------------------- 8. 기술·숫자
s = prs.slides.add_slide(BLANK)
bg(s, WHITE)
title(s, "어떻게 만들었나", "모두 오픈소스, 24시간 운영 중")
stack = [
    [("AI  ", {"bold": True, "color": BLUE}), "MiniLM 다국어 임베딩(fastembed·ONNX) + 규칙 추출"],
    [("백엔드  ", {"bold": True, "color": BLUE}), "Python · FastAPI · SQLite · APScheduler · BeautifulSoup"],
    [("화면  ", {"bold": True, "color": BLUE}), "Next.js · React · TypeScript · PWA(웹 푸시)"],
    [("데이터  ", {"bold": True, "color": BLUE}), "순천대 게시판 + 공공데이터포털 API 3종"],
    [("배포  ", {"bold": True, "color": BLUE}), "화면 Vercel, 수집·알림 Oracle Cloud + Caddy(https)"],
]
text(s, 0.6, 2.0, 6.4, 4.5, stack, size=16, spacing=16)
stats = [("109", "학교 게시판"), ("70", "학과 선택 목록"), ("126", "자동 테스트 통과"), ("0원", "AI 운영 비용")]
for i, (big, label) in enumerate(stats):
    x = 7.4 + (i % 2) * 2.85
    y = 1.9 + (i // 2) * 2.35
    rect(s, x, y, 2.6, 2.05, SOFT, radius=0.08)
    text(s, x, y + 0.3, 2.6, 0.9, big, size=44, bold=True, color=BLUE, align=PP_ALIGN.CENTER)
    text(s, x, y + 1.3, 2.6, 0.5, label, size=14, color=MUTED, align=PP_ALIGN.CENTER)
s.notes_slide.notes_text_frame.text = (
    "기술적으로는 오픈소스 MiniLM 모델과 FastAPI, Next.js로 만들었고, 화면은 Vercel, 수집과 알림은 Oracle Cloud에서 24시간 돌아가고 있습니다. "
    "자동 테스트 126개가 통과한 상태입니다.")

# ---------------------------------------------------------------- 9. 마무리
s = prs.slides.add_slide(BLANK)
bg(s, NAVY)
text(s, 0.75, 1.5, 8.0, 1.0, "지금 바로 써 보세요", size=44, bold=True, color=WHITE)
text(s, 0.78, 2.7, 8.0, 0.6, "scnuaram.vercel.app", size=30, bold=True, color=SKY)
text(s, 0.78, 3.6, 8.0, 1.6, ["휴대폰에서 열고 '홈 화면에 추가'하면 앱처럼 쓸 수 있어요",
                               "GitHub  github.com/GOBIEBERPA/scnu-lens"], size=17, color=WHITE, spacing=10)
text(s, 0.78, 6.3, 8.0, 0.4, "감사합니다 · SCNU Lens · 이휴단", size=14, color=SKY)
rect(s, 9.35, 1.55, 3.3, 3.3, WHITE, radius=0.06)
s.shapes.add_picture(str(ROOT / "qr-scnuaram.png"), Inches(9.55), Inches(1.75), Inches(2.9), Inches(2.9))
text(s, 9.35, 5.05, 3.3, 0.4, "QR로 바로 접속", size=14, color=SKY, align=PP_ALIGN.CENTER)
s.notes_slide.notes_text_frame.text = (
    "화면의 QR 코드나 scnuaram.vercel.app 으로 지금 바로 써 보실 수 있습니다. 감사합니다.")

prs.save(OUT)
print("saved", OUT)
