import asyncio
import re
from datetime import date, datetime, timedelta

import numpy as np

from app.config import Settings
from app.crawlers.attachments import body_only
from app.crawlers.kstartup import CONTEST_RE
from app.models import Notice, UserProfile
from app.schemas import BriefField, NoticeStructured, ScheduleItem
from app.services.brief import build_brief

CATEGORY_LABELS: dict[str, str] = {
    "학사": "수강신청, 수강정정, 졸업요건, 등록금 납부, 학점, 휴학, 복학, 학사일정 안내",
    "장학": "장학금, 국가장학금, 학자금 대출, 생활비 지원 신청 안내",
    "취업": "취업, 채용, 인턴십, 현장실습, 진로 특강 모집 안내",
    "행사": "축제, 특강, 캠프, 설명회, 비교과 프로그램 참가 안내",
    "경진대회": "공모전, 경진대회, 해커톤, 아이디어 대회 참가자 모집 안내",
    "자격증": "자격증 시험 원서접수, 필기·실기 시험일, 합격자 발표 일정 안내",
    "연구실": "학부연구생 선발, 지도교수 연구실 배정, 대학원 진학 안내",
    "안전": "안전교육 이수, 연구실 안전점검, 재난 대응 등 안전 관련 의무 안내",
    "기타": "전산 계정, 이메일, 클라우드, 와이파이, 시설 이용, 행정 절차 등 일반 안내",
}
VALID_CATEGORIES: tuple[str, ...] = tuple(CATEGORY_LABELS)

# "연구실"과 "안전"은 범위가 좁아 임베딩만으로는 오탐이 잦다(모집·점검 성격의 공지를 모두 끌어당김).
# 두 카테고리는 아래 STRONG_KEYWORD_RULES의 확정 단서로만 도달하게 하고, 유사도 후보에서는 뺀다.
EMBEDDING_CATEGORIES: tuple[str, ...] = ("학사", "장학", "취업", "행사", "기타")

# 임베딩 유사도가 이 값에 못 미치면 특정 카테고리로 단정하지 않고 "기타"로 둔다.
MIN_CATEGORY_SIMILARITY = 0.32

# 오탐이 거의 없는 강한 단서는 임베딩보다 먼저 적용한다.
STRONG_KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("장학", ("장학금", "국가장학금", "학자금", "장학생")),
    ("자격증", ("원서접수", "필기시험", "실기시험", "자격증", "토익", "TOEIC", "텝스", "오픽", "OPIc", "ADSP", "SQLD", "한국사능력검정")),
    ("경진대회", ("공모전", "경진대회", "해커톤")),
    ("취업", ("채용", "취업", "인턴십", "현장실습")),
    ("안전", ("안전교육", "연구실 안전", "안전점검")),
    ("연구실", ("학부연구생", "연구실 인턴")),
    ("학사", ("수강신청", "수강정정", "졸업요건", "등록금 납부", "추가등록", "분할납부", "등록금")),
]

# 이 힌트로 들어온 공지(공모전 모음·시험 일정 소스)는 분류기를 거치지 않고 힌트를 그대로 쓴다.
# 학교 게시판 힌트(학사·장학·학과…)에는 쓰지 않으므로 학교 공지 분류에는 영향이 없다.
SOURCE_LOCKED_CATEGORIES = frozenset({"경진대회", "자격증"})

# 이 분야의 확정 키워드는 본문이 아니라 제목에서만 찾는다.
TITLE_ONLY_CATEGORIES = frozenset({"자격증"})

KEYWORD_DICTIONARY: tuple[str, ...] = (
    "수강신청", "수강정정", "졸업", "등록금", "휴학", "복학", "학점",
    "장학금", "국가장학금", "학자금", "취업", "채용", "인턴", "현장실습",
    "공모전", "경진대회", "특강", "캠프", "설명회", "학부연구생", "연구실",
    "안전교육", "모집", "신청", "접수", "제출",
)

# 날짜 **뒤에** 붙는 단서("10.8.(목)까지", "9.30 마감"). 이 단서는 앞쪽을 본다.
# "신청기간: 9.21 ~ 10.8"처럼 날짜가 **앞에** 오는 라벨은 APPLY_LABEL_RE로 뒤쪽을 본다.
# 예전에는 라벨도 앞쪽을 봐서, 바로 윗줄 "운영기간: ~ '27.1.7"을 마감으로 잡았다.
DEADLINE_CUES: tuple[str, ...] = ("까지", "마감")

# 연도까지 포함한 완전한 날짜. "2026.5.14", "2026-05-14", "2026년 5월 14일"
FULL_DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?")
# 두 자리 연도. "’26. 10. 8.", "'27.1.7"
SHORT_YEAR_DATE_RE = re.compile(r"[’'‘`]\s?(\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})")
# 연도가 빠진 날짜. "9월 30일"
MONTH_DAY_KR_RE = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")
# 연도가 빠진 축약 날짜. "5.14", "9. 9.(수)" — 뒤에 숫자가 더 붙으면(=연도.월.일 일부) 제외한다.
MONTH_DAY_DOT_RE = re.compile(r"(?<![\d.\-/])(\d{1,2})\s*[./]\s*(\d{1,2})(?!\s*[\d/\-])(?!\.\s*\d)")

DEPARTMENT_RE = re.compile(r"[가-힣]{2,10}(?:학과|교육과|학부|전공)")
# "복수전공"처럼 학과 이름이 아닌 제도 용어는 대상 학과에서 제외한다.
NON_DEPARTMENT_TERMS = frozenset(
    {"복수전공", "부전공", "연계전공", "심화전공", "세부전공", "주전공", "다중전공", "융합전공", "동일전공"}
)
STUDENT_TARGET_RE = re.compile(r"(?:재학생|신입생|편입생|졸업예정자|휴학생|대학원생|[1-4]\s*학년)")


# _structure_notice_sync에 소스 분야를 넘기지 않았음을 뜻하는 표시(None은 "고정 분야 없음"이라 따로 둔다).
READ_FROM_NOTICE = object()


def source_locked_category(notice: Notice) -> str | None:
    """입력: 공지, 출력: 수집 소스가 분야를 정하는 경우(공모전 모음·시험 일정) 그 분야, 아니면 None.

    공지의 현재 분류가 아니라 소스의 분야 힌트를 봐야, 학교 공지가 한 번 '경진대회'로 분류됐다고
    다음 분류 때 그대로 굳어 버리는 일이 없다.
    """
    source = notice.crawler_source
    # K-Startup 공고는 학교 공지용 분류기가 '창업 아카데미'를 장학·학사로 잘못 보므로 제목으로 정한다.
    if source is not None and source.parser_type == "contest_kstartup":
        return "경진대회" if CONTEST_RE.search(notice.title) else "행사"
    hint = source.category_hint if source is not None else None
    return hint if hint in SOURCE_LOCKED_CATEGORIES else None


class LocalNoticeClassifier:
    """API 호출 없이 경량 임베딩 모델과 정규식만으로 공지를 분류·추출한다."""

    _model = None
    _label_matrix: np.ndarray | None = None
    _load_attempted = False

    def __init__(self, settings: Settings) -> None:
        """입력: 앱 설정, 출력 없음; 임베딩 모델을 로드한다."""
        self.settings = settings
        type(self)._ensure_model()

    @classmethod
    def _ensure_model(cls) -> None:
        """입력 없음, 출력 없음; fastembed 모델 로딩에 실패하면 키워드 규칙으로만 동작한다."""
        if cls._load_attempted:
            return
        cls._load_attempted = True
        try:
            from fastembed import TextEmbedding

            model = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
            vectors = list(model.embed([CATEGORY_LABELS[name] for name in EMBEDDING_CATEGORIES]))
            cls._model = model
            cls._label_matrix = np.array(vectors)
        except Exception:
            cls._model = None
            cls._label_matrix = None

    async def structure_notice(self, notice: Notice) -> NoticeStructured:
        """입력: 원문 공지, 출력: 임베딩 분류와 규칙 추출로 만든 구조화 결과."""
        # 소스 정보는 DB에서 늦게 불러오므로, 세션이 있는 이 스레드에서 미리 읽어 넘긴다.
        source_category = source_locked_category(notice)
        return await asyncio.to_thread(self._structure_notice_sync, notice, source_category)

    def _structure_notice_sync(self, notice: Notice, source_category: object = READ_FROM_NOTICE) -> NoticeStructured:
        """입력: 원문 공지·(미리 읽은) 소스 고정 분야, 출력: 카테고리·마감일·대상·키워드와 정해진 칸을 채운 구조화 결과.

        소스 고정 분야를 넘기지 않으면 여기서 읽는다(스크립트·테스트처럼 같은 스레드에서 부를 때).
        """
        if source_category is READ_FROM_NOTICE:
            source_category = source_locked_category(notice)
        text = f"{notice.title} {notice.raw_text}"
        published = notice.published_at.date() if notice.published_at else None
        structured = NoticeStructured(
            title=notice.title,
            category=source_category or self._classify_category(text, notice.category, notice.title),
            summary=self._shorten(notice.raw_text, 240),
            # 첨부에는 서류 제출기한 같은 부차적인 날짜도 많아, 본문에 마감이 있으면 본문을 따른다.
            deadline=extract_deadline(f"{notice.title} {body_only(notice.raw_text)}", published)
            or extract_deadline(text, published),
            target_departments=self._extract_departments(text),
            target_students=self._extract_students(text),
            keywords=[word for word in KEYWORD_DICTIONARY if word in text][:8],
            action_required=self._infer_action(text),
            contact=None,
        )
        open_at, close_at = extract_window(notice.raw_text)
        if not open_at:  # 학교 공지는 "신청기간: A ~ B" 모양이라 여기서 시작일을 찾는다
            open_at = extract_apply_start(f"{notice.title} {body_only(notice.raw_text)}", published, structured.deadline) \
                or extract_apply_start(text, published, structured.deadline)
        return structured.model_copy(
            update={
                "brief": self._brief(notice, structured),
                "schedule": extract_schedule(notice.raw_text),
                "open_at": open_at,
                "close_at": close_at,
            }
        )

    @staticmethod
    def _brief(notice: Notice, structured: NoticeStructured) -> list[BriefField]:
        """입력: 공지·구조화 결과·LLM이 찾은 값, 출력: 정해진 칸 순서대로 채운 상세 정보."""
        items = build_brief(
            notice.title,
            notice.raw_text,
            notice.source,
            structured.deadline,
            structured.target_students + structured.target_departments,
        )
        return [BriefField(label=i.label, value=i.value, found=i.found, method=i.method) for i in items]

    def _classify_category(self, text: str, hint: str, title: str | None = None) -> str:
        """입력: 제목+본문·소스 힌트·제목, 출력: 강한 키워드 우선, 그다음 임베딩 유사도로 고른 카테고리."""
        strong = self._strong_keyword_category(text, title)
        if strong:
            return strong
        if self._model is not None and self._label_matrix is not None:
            try:
                vector = np.array(next(self._model.embed([text[:2000]])))
                norms = np.linalg.norm(self._label_matrix, axis=1) * np.linalg.norm(vector) + 1e-8
                scores = (self._label_matrix @ vector) / norms
                best = int(scores.argmax())
                if float(scores[best]) >= MIN_CATEGORY_SIMILARITY:
                    return EMBEDDING_CATEGORIES[best]
                return "기타"
            except Exception:
                pass
        return hint if hint in VALID_CATEGORIES else "기타"

    @staticmethod
    def _strong_keyword_category(text: str, title: str | None = None) -> str | None:
        """입력: 제목+본문·제목, 출력: 오탐이 드문 확정 키워드로 고른 카테고리 또는 None.

        제목을 먼저 본다. "추가등록 안내" 본문에 학자금·장학생이 지나가듯 나와도 공지의 성격은 제목이 정한다.
        """
        if title:
            for category, keywords in STRONG_KEYWORD_RULES:
                if any(keyword in title for keyword in keywords):
                    return category
        for category, keywords in STRONG_KEYWORD_RULES:
            # '자격증' 같은 말은 학사 공지 본문에도 지나가듯 나오므로 제목에 있을 때만 확정한다.
            haystack = title if category in TITLE_ONLY_CATEGORIES and title is not None else text
            if any(keyword in haystack for keyword in keywords):
                return category
        return None

    @staticmethod
    def _extract_departments(text: str) -> list[str]:
        """입력: 제목+본문, 출력: 본문에 등장한 학과·학부·전공 이름 목록."""
        found = dict.fromkeys(
            match.strip() for match in DEPARTMENT_RE.findall(text) if match.strip() not in NON_DEPARTMENT_TERMS
        )
        return list(found)[:8]

    @staticmethod
    def _extract_students(text: str) -> list[str]:
        """입력: 제목+본문, 출력: 재학생·학년 등 공지가 지목한 대상 표현 목록."""
        found = dict.fromkeys(" ".join(match.split()) for match in STUDENT_TARGET_RE.findall(text))
        return list(found)[:6]

    @staticmethod
    def _infer_action(text: str) -> str | None:
        """입력: 제목+본문, 출력: 학생이 해야 할 행동 안내 문구 또는 None."""
        if any(word in text for word in ("신청", "접수", "모집")):
            return "원문에서 신청 방법과 기간을 확인하세요."
        if any(word in text for word in ("제출", "이수", "납부")):
            return "원문에서 제출·이수 요건을 확인하세요."
        return None

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        """입력: 긴 본문·글자 수, 출력: 공백 정규화 후 문장 경계를 존중한 요약용 발췌."""
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        shortened = normalized[:limit].rsplit(" ", 1)[0]
        return f"{shortened}…"


# 행사 날짜를 적는 라벨. "일시: 10월 8일"은 마감이 아니라 참석하는 날이다.
EVENT_LABEL_RE = re.compile(
    r"일\s*시|일\s*자|행사\s*일|교육\s*일|특강\s*일|시상|발표|개최|장\s*소|대회\s*기간|운영\s*기간|교육\s*기간|근무\s*기간|임\s*용\s*일"
)
# 신청 쪽 라벨. 이 라벨 바로 뒤의 날짜만 마감 후보로 본다.
APPLY_LABEL_RE = re.compile(r"(?:신청|접수|모집|제출|마감|응모|설문|조사)\s*(?:기간|기한|일정|일)?")
# "신청 시작: 9월 23일 오후 3시~"는 여는 날이지 마감이 아니다.
START_WORD_RE = re.compile(r"시작|오픈|개시")
# 신청 라벨 끝에서 첫 날짜까지 허용하는 거리. 멀면 다른 문장의 날짜다.
LABEL_TO_DATE_GAP = 15


def extract_deadline(text: str, published: date | None) -> str | None:
    """입력: 공지 전문·게시일, 출력: ISO(YYYY-MM-DD) 마감일 또는 None.

    "2026학년도 2학기"의 `26-2` 같은 학기 표기를 날짜로 오인하지 않도록,
    마감 단서("~까지", "마감" 등) 주변을 먼저 살피고, 없으면 신청·접수 라벨 바로 뒤 날짜만 받는다.
    행사 '일시' 라벨이 붙은 날짜는 건너뛴다(특강·시상식 날짜를 마감으로 알리던 문제).
    원문은 HTML 태그마다 줄이 끊겨 있어 공백을 하나로 합친 뒤 본다.
    """
    flat = " ".join(text.split())
    for cue in DEADLINE_CUES:
        for cue_match in re.finditer(re.escape(cue), flat):
            window = flat[max(0, cue_match.start() - 40) : cue_match.start() + len(cue)]
            dates = _dates_in(window, published)
            if dates and not _event_labeled(window[: dates[-1][0]]):
                return dates[-1][1]
    for label in APPLY_LABEL_RE.finditer(flat):
        segment = flat[label.end() : label.end() + 60]
        cut = EVENT_LABEL_RE.search(segment)
        dates = _dates_in(segment[: cut.start()] if cut else segment, published)
        if not dates or dates[0][0] > LABEL_TO_DATE_GAP:
            continue
        if START_WORD_RE.search(segment[: dates[0][0]]):
            continue
        # "접수기간: 9.14 ~ 9.29"처럼 범위면 뒤쪽 날짜가 마감이다.
        return dates[-1][1]
    return None


def extract_apply_start(text: str, published: date | None, deadline: str | None) -> str | None:
    """입력: 공지 전문·게시일·마감일, 출력: 신청기간의 시작일(ISO) 또는 None.

    "신청기간: 10.12 ~ 10.16"처럼 신청 라벨 뒤 범위의 앞 날짜다. 마감일과 같은 범위일 때만 받는다
    (다른 문장의 날짜를 시작일로 착각하지 않게). 이게 있어야 "접수 전"과 "접수중"을 나눌 수 있다.
    """
    flat = " ".join(text.split())
    for label in APPLY_LABEL_RE.finditer(flat):
        segment = flat[label.end() : label.end() + 60]
        cut = EVENT_LABEL_RE.search(segment)
        dates = _dates_in(segment[: cut.start()] if cut else segment, published)
        if len(dates) < 2 or dates[0][0] > LABEL_TO_DATE_GAP or START_WORD_RE.search(segment[: dates[0][0]]):
            continue
        # "필기 원서접수: A ~ B 필기 시험일: C ~ D"처럼 뒤에 다른 일정이 붙어도, 마감일이 이 조각 안에 있으면 A가 시작이다.
        start, days = dates[0][1], [day for _, day in dates]
        if deadline is None:
            if start < days[1]:
                return start
        elif deadline in days[1:] and start < deadline:
            return start
    return None


# "시험일: 2026-10-11", "필기 시험일: …", "성적발표: …", "합격자발표: …"처럼 줄 맨 앞에 라벨이 있는 일정.
# 시험 일정 크롤러가 이 모양으로 적고, 학교 공지는 이런 줄이 드물어 오탐이 적다.
SCHEDULE_LINE_RE = re.compile(r"^\s*((?:필기|실기)\s*)?(시험일|성적\s*발표|합격\s*발표|합격자\s*발표|결과\s*발표)\s*[:：]\s*(.+)$")


# "접수 시작: 2026-09-14 10:00", "접수 마감: 2026-10-19 10:00까지" — 시험·공모전 크롤러가 이 모양으로 적는다.
WINDOW_LINE_RE = re.compile(r"^\s*접수\s*(시작|마감)\s*[:：]\s*(20\d{2}-\d{2}-\d{2})(?:\s+(\d{1,2}):(\d{2}))?")


def extract_window(text: str) -> tuple[str | None, str | None]:
    """입력: 공지 본문, 출력: (접수 시작, 접수 마감). 시각이 있으면 "YYYY-MM-DDTHH:MM", 없으면 날짜만.

    학교 공지는 이런 줄이 없어 (None, None)이 되고, 마감 알림은 마감일(deadline)로만 건다.
    """
    found: dict[str, str] = {}
    for line in body_only(text).splitlines():
        match = WINDOW_LINE_RE.match(line)
        if not match or match.group(1) in found:
            continue
        day, hour, minute = match.group(2), match.group(3), match.group(4)
        found[match.group(1)] = f"{day}T{int(hour):02d}:{minute}" if hour else day
    return found.get("시작"), found.get("마감")


def extract_schedule(text: str) -> list[ScheduleItem]:
    """입력: 공지 본문, 출력: 시험일·발표일 일정 목록(날짜 순, 중복 제거)."""
    items: dict[tuple[str, str], ScheduleItem] = {}
    for line in body_only(text).splitlines():
        match = SCHEDULE_LINE_RE.match(line)
        if not match:
            continue
        found = FULL_DATE_RE.search(match.group(3))
        iso = _to_iso(int(found.group(1)), int(found.group(2)), int(found.group(3))) if found else None
        if not iso:
            continue
        phase = (match.group(1) or "").strip()
        kind = "시험" if match.group(2) == "시험일" else re.sub(r"\s+", "", match.group(2))
        label = f"{phase} {kind}".strip()
        items[(iso, label)] = ScheduleItem(date=iso, label=label)
    return sorted(items.values(), key=lambda item: item.date)


def _event_labeled(before: str) -> bool:
    """입력: 날짜 앞 텍스트, 출력: 가장 가까운 라벨이 신청이 아니라 행사 일시·장소 라벨인지 여부."""
    events = list(EVENT_LABEL_RE.finditer(before))
    if not events:
        return False
    applies = list(APPLY_LABEL_RE.finditer(before))
    return not applies or applies[-1].start() < events[-1].start()


def _dates_in(segment: str, published: date | None) -> list[tuple[int, str]]:
    """입력: 텍스트 조각·게시일, 출력: (시작 위치, ISO 날짜) 목록을 등장 순서대로.

    연도 있는 날짜와 연도 없는 날짜를 함께 모아 위치로 정렬해야 "2026. 9. 14. ~ 9. 29."의 끝을 고를 수 있다.
    """
    found: list[tuple[int, int, str]] = []
    for match in FULL_DATE_RE.finditer(segment):
        iso = _to_iso(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if iso:
            found.append((match.start(), match.end(), iso))
    for match in SHORT_YEAR_DATE_RE.finditer(segment):
        iso = _to_iso(2000 + int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if iso:
            found.append((match.start(), match.end(), iso))
    for pattern in (MONTH_DAY_KR_RE, MONTH_DAY_DOT_RE):
        for match in pattern.finditer(segment):
            if any(start <= match.start() < end for start, end, _ in found):
                continue
            iso = _to_iso(None, int(match.group(1)), int(match.group(2)), published)
            if iso:
                found.append((match.start(), match.end(), iso))
    return [(start, iso) for start, _, iso in sorted(found)]


def _to_iso(year: int | None, month: int, day: int, published: date | None = None) -> str | None:
    """입력: 연·월·일(연도는 선택)·게시일, 출력: 검증된 ISO 날짜 문자열 또는 None."""
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    base = published or date.today()
    candidates = [year] if year else [base.year, base.year + 1]
    for candidate_year in candidates:
        try:
            resolved = date(candidate_year, month, day)
        except ValueError:
            continue
        # 연도가 없던 날짜가 게시일보다 크게 과거면 다음 해 마감으로 본다(연말→연초 공지).
        if year is None and resolved < base - timedelta(days=180):
            continue
        return resolved.isoformat()
    return None


# 시험일정 API는 종목(정보처리기사)이 아니라 등급(기사) 단위로 온다.
# 긴 등급부터 비교해야 '산업기사'가 '기사'로 잘못 잡히지 않는다.
EXAM_GRADES: tuple[str, ...] = ("기능장", "기술사", "산업기사", "기능사", "기사")


# 학생이 적는 관심사와 공지가 쓰는 말이 다른 경우를 잇는다. 키는 소문자로 적는다.
INTEREST_SYNONYMS: dict[str, tuple[str, ...]] = {
    "ai": ("인공지능", "머신러닝", "딥러닝", "생성형"),
    "인공지능": ("ai", "머신러닝", "딥러닝", "생성형"),
    "코딩": ("프로그래밍", "소프트웨어", "sw", "개발자"),
    "프로그래밍": ("코딩", "소프트웨어", "sw"),
    "취업": ("채용", "인턴", "현장실습", "일자리", "구직"),
    "인턴": ("인턴십", "현장실습"),
    "장학금": ("장학", "학자금"),
    "장학": ("장학금", "학자금"),
    "창업": ("스타트업", "예비창업"),
    "해외": ("교환학생", "어학연수", "해외파견"),
    "봉사": ("자원봉사", "봉사활동"),
    "토익": ("toeic",),
    "toeic": ("토익",),
    "공모전": ("경진대회", "해커톤"),
    "대학원": ("석사", "대학원생", "진학"),
}


def _contains_term(term: str, haystack: str) -> bool:
    """입력: 소문자 키워드·소문자 본문, 출력: 포함 여부.

    영문 약어는 단어 경계를 지켜야 한다. 그냥 포함 여부로 보면 "ai"가 "gmail"·"main" 안에서 잡힌다.
    """
    term = term.strip().lower()
    if not term:
        return False
    if term.isascii():
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", haystack) is not None
    return term in haystack


def _haystack(notice: Notice) -> str:
    """입력: 공지, 출력: 매칭 비교에 쓸 제목·본문·추출된 대상을 합친 소문자 문자열.

    구조화 결과를 JSON 그대로 붙이면 "label"·"value" 같은 키 이름까지 매칭되므로 값만 쓴다.
    """
    structured = notice.structured_json or {}
    targets = [*structured.get("target_departments", []), *structured.get("target_students", [])]
    return f"{notice.title} {notice.raw_text} {' '.join(targets)}".lower()


# 본문에만 나오는 관심사는 이 횟수 이상일 때만 인정한다.
# 채용공고 자격요건의 "생성형 AI 활용 능력" 한 줄로 'AI 관련 공지'가 되던 문제.
BODY_ONLY_MIN_HITS = 2

# 이미 끝난 일을 알리는 공지. 관심사로 추천하면 지원할 수 있는 기회처럼 보인다.
RESULT_TITLE_RE = re.compile(r"결과|수상자|수상작|합격자|선정자|당선작|명단|최종\s*선발")


def is_result_notice(notice: Notice) -> bool:
    """입력: 공지, 출력: 제목이 결과·수상자·합격자 발표 같은 '이미 정해진 일' 공지인지 여부."""
    return bool(RESULT_TITLE_RE.search(notice.title or ""))


def _term_hits(term: str, text: str) -> int:
    """입력: 키워드·소문자 본문, 출력: 등장 횟수(영문 약어는 단어 경계 기준)."""
    term = term.strip().lower()
    if not term:
        return 0
    if term.isascii():
        return len(re.findall(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text))
    return text.count(term)


def _matched_interests(user: UserProfile, notice: Notice) -> list[str]:
    """입력: 사용자·공지, 출력: 공지와 겹치는 관심 키워드 목록; 동의어·자격증 등급 매칭을 포함한다.

    제목·추출된 대상에 있으면 바로 인정하고, 본문에만 있으면 BODY_ONLY_MIN_HITS번 이상 나올 때만 인정한다.
    """
    structured = notice.structured_json or {}
    targets = [*structured.get("target_departments", []), *structured.get("target_students", [])]
    head = f"{notice.title} {' '.join(targets)}".lower()
    body = (notice.raw_text or "").lower()
    matched: list[str] = []
    for interest in user.interests:
        terms = (interest, *INTEREST_SYNONYMS.get(interest.strip().lower(), ()))
        in_head = any(_contains_term(term, head) for term in terms)
        # 합이 아니라 가장 많이 나온 한 단어로 센다. "생성형 AI" 한 구절이 'ai'·'생성형' 두 번으로 세어지지 않게.
        if in_head or max(_term_hits(term, body) for term in terms) >= BODY_ONLY_MIN_HITS:
            matched.append(interest)
            continue
        grade = next((g for g in EXAM_GRADES if interest.strip().endswith(g)), None)
        # "정보처리기사"에 관심 있으면 "국가기술자격 기사 제3회" 일정이 해당된다.
        if grade and notice.category == "자격증" and f" {grade} " in f" {notice.title} ":
            matched.append(interest)
    return matched


def _from_own_department_board(user: UserProfile, notice: Notice) -> bool:
    """입력: 사용자·공지, 출력: 사용자 학과 게시판에서 온 공지인지 여부.

    학과 게시판 공지는 본문에 학과명을 따로 쓰지 않는 경우가 많아, 출처로 판단해야 매칭된다.
    """
    core = department_core(user.department)
    return bool(core) and core in (notice.source or "")


def department_core(name: str | None) -> str:
    """입력: 학과 이름, 출력: '과·전공·학부'를 뗀 핵심 이름; 미설정이면 빈 문자열.

    학제 개편으로 게시판 이름은 "전자공학전공"인데 학생은 "전자공학과"라고 적는 경우가 많다.
    """
    name = (name or "").strip()
    if not name or name == "미설정":
        return ""
    core = re.sub(r"(?:과|전공|학부)$", "", name)
    # "간호학부"→"간호"처럼 너무 짧아지면 다른 말과 겹치므로 원래 이름을 쓴다.
    return core if len(core) >= 3 else name


def relevance_score(user: UserProfile, notice: Notice) -> float:
    """입력: 사용자·공지, 출력: 학과/관심사/선택 분야 일치에 따른 단순 설명 가능 점수."""
    score = 0.0
    if _from_own_department_board(user, notice):
        score += 3.0
    elif department_core(user.department) and _contains_term(department_core(user.department), _haystack(notice)):
        score += 3.0
    # 결과·수상자 발표는 내 학과 소식으로는 보여주되, 관심사·분야로 '기회'처럼 추천하지는 않는다.
    if not is_result_notice(notice):
        score += 2.0 * len(_matched_interests(user, notice))
        if notice.category in user.interests:
            score += 1.5
        # 마이페이지에서 분야를 직접 골랐다면 그 분야 공지는 받고 싶다는 뜻이다.
        if notice.category in (user.notify_categories or []):
            score += 1.5
    return score if user.interests or user.department != "미설정" or user.notify_categories else 1.0


def match_reason(user: UserProfile, notice: Notice) -> str:
    """입력: 사용자·공지, 출력: 겹치는 관심사/학과/선택 분야에 근거한 매칭 이유 문장."""
    matched = [] if is_result_notice(notice) else _matched_interests(user, notice)
    if matched:
        listed = ", ".join(matched[:3])
        return f"관심 키워드 ‘{listed}’{_with_particle(listed)} 관련된 공지예요."
    if _from_own_department_board(user, notice):
        return f"내 학과({user.department}) 게시판에 올라온 공지예요."
    if department_core(user.department) and _contains_term(department_core(user.department), _haystack(notice)):
        return f"{user.department} 학생을 대상으로 언급한 공지예요."
    if notice.category in (user.notify_categories or []) and not is_result_notice(notice):
        return f"알림 받기로 선택한 ‘{notice.category}’ 분야 공지예요."
    return "학사 일정이나 지원 기회를 놓치지 않도록 확인해 보세요."


def _with_particle(word: str) -> str:
    """입력: 앞 단어, 출력: 받침 유무에 맞는 조사 '과' 또는 '와'."""
    last = word.strip()[-1:] if word.strip() else ""
    if not last or not "가" <= last <= "힣":
        return "와"
    return "과" if (ord(last) - 0xAC00) % 28 else "와"


def days_until_deadline(notice: Notice, today: date | None = None) -> int | None:
    """입력: 구조화된 공지·기준일, 출력: 마감까지 남은 일수 또는 마감일이 없으면 None."""
    raw = (notice.structured_json or {}).get("deadline")
    if not isinstance(raw, str):
        return None
    try:
        deadline = datetime.fromisoformat(raw).date()
    except ValueError:
        return None
    return (deadline - (today or date.today())).days
