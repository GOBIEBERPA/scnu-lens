"""공지 본문을 정해진 칸(대상·기간·신청방법·문의·주관 등)에 채워 넣는 추출 하네스.

자유 요약문 대신 칸을 고정해 두면 화면이 늘 같은 모양으로 깔끔하고, LLM을 쓰더라도
"빈칸 하나를 원문에서 찾아라"처럼 작고 검증 가능한 일만 맡길 수 있다.

칸마다 여러 추출 방법을 순서대로 시도하고(루프), 각 결과를 검증해 통과한 첫 값을 쓴다.
끝까지 못 찾으면 값을 지어내지 않고 '제공 여부 미확인'으로 남긴다.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

# 못 찾은 칸 표시. 세부 내용이 첨부파일에만 있는 공지가 많아, 학생이 할 일(원문 확인)을 알려준다.
UNKNOWN = "원문 페이지 자료 확인 필요"
# 칸 값은 라벨 한 줄(+이어진 줄)에서 오므로 대부분 짧다. 중간에서 자르면 정보가 망가지므로 넉넉히 둔다.
MAX_VALUE_LENGTH = 160


@dataclass(frozen=True)
class FieldSpec:
    """칸 하나의 정의: 이름, 본문에서 쓰이는 라벨 동의어, 항상 보여줄지 여부."""

    name: str
    labels: tuple[str, ...]
    always_show: bool


# 실제 순천대 공지 본문에서 '라벨: 값'으로 쓰인 항목을 세어 고른 칸과 동의어.
FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("대상", ("신청대상", "지원대상", "모집대상", "교육대상", "참가대상", "응시대상", "대상자", "대상"), True),
    FieldSpec(
        "기간",
        ("신청기간", "접수기간", "모집기간", "원서접수", "등록기간", "납부기간", "활동기간", "교육기간", "운영기간", "기간"),
        True,
    ),
    FieldSpec("신청방법", ("신청방법", "접수방법", "제출방법", "지원방법", "참가방법", "이용방법"), True),
    FieldSpec("문의", ("문의처", "문의사항", "문의", "연락처", "담당자"), True),
    FieldSpec("주관", ("주최", "주관", "시행기관", "담당부서", "운영기관"), True),
    FieldSpec("일시", ("행사일시", "교육일시", "일시"), False),
    FieldSpec("장소", ("행사장소", "교육장소", "장소"), False),
    FieldSpec("지원내용", ("지원내용", "지원혜택", "참여혜택", "지원금액", "혜택"), False),
    FieldSpec("제출서류", ("제출서류", "구비서류", "필요서류"), False),
)

# 줄 머리의 번호·기호(1. / 가. / □ / ○ / - 등)를 떼고 '라벨 :' 형태를 잡는다.
LABEL_LINE = re.compile(
    r"^\s*(?:\d+[.)]|[가-하][.)]|[□■○●◦•▶▷※\-·*])?\s*([가-힣][가-힣\s·/()]{0,14}?)\s*[:：]\s*(.*)$"
)
# 새 항목의 시작. '1.'·'가.' 같은 번호는 뒤에 글자가 올 때만 인정한다.
# 그래야 '2026. 8. 3.'처럼 날짜로 시작하는 이어진 줄을 새 항목으로 오인하지 않는다.
NEW_ITEM = re.compile(r"^\s*(?:\d{1,2}[.)]\s*(?=[가-힣A-Za-z])|[가-하][.)]\s*|[□■○●◦•▶▷])")
DATE = r"(?:20\d{2}\s*[.\-/년]\s*)?\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*일?\.?\s*(?:\([^)]{1,4}\))?"
DATE_RANGE = re.compile(rf"({DATE})\s*[~∼～\-]\s*({DATE})")
PHONE = re.compile(r"0\d{1,2}\s*[-)]\s*\d{3,4}\s*-\s*\d{4}")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
HOW_ACTION = ("신청", "접수", "제출", "지원")
HOW_CHANNEL = ("홈페이지", "시스템", "향림통", "이메일", "e-mail", "방문", "링크", "QR", "구글폼", "온라인", "우편", "사무실")


@dataclass
class BriefItem:
    """칸 하나의 결과: 값, 원문에서 찾았는지, 어떤 방법으로 찾았는지."""

    label: str
    value: str
    found: bool
    method: str | None


def _clean(text: str) -> str:
    """입력: 추출한 원문 조각, 출력: 공백을 정리하고 길이를 제한한 값."""
    text = re.sub(r"\s+", " ", text).strip(" /,·-")
    return text if len(text) <= MAX_VALUE_LENGTH else text[: MAX_VALUE_LENGTH - 1].rstrip() + "…"


def _label_matches(label: str, synonyms: tuple[str, ...]) -> bool:
    """입력: 본문 라벨(공백 제거)·동의어, 출력: 같은 칸으로 볼지 여부."""
    for synonym in synonyms:
        if label == synonym:
            return True
        # '필기원서접수', '신청기간및방법'처럼 앞뒤가 붙은 라벨도 받되, 두 글자 동의어는 정확히만 받는다.
        if len(synonym) >= 3 and (label.startswith(synonym) or label.endswith(synonym)):
            return True
    return False


def _from_labels(lines: list[str], spec: FieldSpec) -> str | None:
    """입력: 본문 줄 목록·칸 정의, 출력: '라벨: 값'에서 찾은 값; 값이 다음 줄로 넘어가면 이어 붙인다."""
    for index, line in enumerate(lines):
        match = LABEL_LINE.match(line)
        if not match or not _label_matches(re.sub(r"\s+", "", match.group(1)), spec.labels):
            continue
        value = match.group(2).strip()
        # "신청기간: ~" 다음 줄에 날짜가 오거나, "(재무과" 뒤 전화번호가 다음 줄로 넘어간 식으로
        # 끊겨 있으면 다음 줄들을 이어 붙인다.
        follow = index + 1
        while (
            (len(value) < 6 or value.endswith(("~", "∼", ":")) or value.count("(") > value.count(")"))
            and follow < len(lines)
            and follow <= index + 2
        ):
            nxt = lines[follow].strip()
            if not nxt or LABEL_LINE.match(nxt) or NEW_ITEM.match(nxt):
                break
            value = f"{value} {nxt}"
            follow += 1
        return value
    return None


PERIOD_HINT = ("신청", "접수", "모집", "지원")


def _period_from_pattern(lines: list[str], deadline: str | None) -> str | None:
    """입력: 본문 줄 목록·마감일, 출력: 신청·접수 줄의 날짜 범위, 없으면 확인된 마감일.

    본문에는 분할납부 차수·행사 일정처럼 신청기간이 아닌 날짜 범위도 섞여 있으므로,
    아무 범위나 집지 않고 신청·접수를 말하는 줄에 있는 범위만 받는다.
    """
    for line in lines:
        if any(hint in line for hint in PERIOD_HINT):
            match = DATE_RANGE.search(line)
            if match:
                return f"{match.group(1)} ~ {match.group(2)}"
    return f"~ {deadline} (마감일만 확인)" if deadline else None


# "신청방법: 담당자 메일(…)로 제출"처럼 메일이 있어도 문의처가 아니라 제출처인 줄의 라벨.
NOT_CONTACT_LABEL = re.compile(r"방법|제출|신청|접수|보고서|서류|조사|링크|주소")
# 한글 파일에서 온 글머리 기호: 사용자 정의 영역(U+E000~U+F8FF)과 반각 원(￮).
ODD_MARKS = re.compile("[-￮]")
# 줄 머리 번호·기호(마. / 6. / ○ / - 등)
LEAD_MARK = re.compile(r"^\s*(?:\d{1,2}[.)]|[가-하][.)]|[□■○●◦•▶▷※\-·*])\s*")


def _contact_from_pattern(lines: list[str]) -> str | None:
    """입력: 본문 줄 목록, 출력: 전화번호나 이메일이 있는 줄(머리 번호는 뗀다).

    '신청방법'·'접수방법'·'결과보고서' 같은 라벨이 붙은 줄의 메일은 제출처라 문의로 보지 않는다.
    """
    for line in lines:
        if not (PHONE.search(line) or EMAIL.search(line)):
            continue
        label = LABEL_LINE.match(line)
        if label and NOT_CONTACT_LABEL.search(label.group(1)) and "문의" not in label.group(1):
            continue
        return LEAD_MARK.sub("", line).strip()
    return None


PARTICLES = ("을 ", "를 ", "이 ", "가 ", "은 ", "는 ", "에 ", "의 ", "로 ", "과 ", "와 ", "으로 ")


def _joined(raw_text: str) -> str:
    """입력: 줄이 잘게 끊긴 본문, 출력: 한 줄로 이은 본문; 조사로 시작하는 줄은 앞 단어에 붙인다."""
    parts: list[str] = []
    for line in (l.strip() for l in raw_text.splitlines()):
        if not line:
            continue
        if parts and line.startswith(PARTICLES):
            parts[-1] += line
        else:
            parts.append(line)
    return " ".join(parts)


def _sentences(raw_text: str) -> list[str]:
    """입력: 본문, 출력: 문장 목록. 날짜의 '.'에서 자르지 않도록 '다.'·'요.'·'니다' 뒤에서만 자른다."""
    return [s.strip() for s in re.split(r"(?<=[다요]\.)\s+|(?<=니다)\s+", _joined(raw_text)) if s.strip()]


def _looks_like_prose(sentence: str) -> bool:
    """입력: 문장 후보, 출력: 번호·날짜·표 조각이 아니라 읽을 수 있는 문장인지 여부."""
    # '1.(화) 10:00 ~'·'8. 3.' 같은 번호·날짜 조각은 버리되, '2026학년도…'처럼 연도로 시작하는 문장은 받는다.
    if re.match(r"^(?:\d{1,2}[.)]|\d+\s*\.\s*\d|[(~∼\-])", sentence):
        return False
    return len(re.findall(r"[가-힣]", sentence)) >= 8


def _how_from_sentences(raw_text: str) -> str | None:
    """입력: 본문, 출력: 신청 행동과 신청 경로가 함께 나오는 짧은 문장; 확실하지 않으면 None.

    틀린 값을 보여주는 것보다 '미확인'이 낫기 때문에 기준을 좁게 잡는다.
    """
    for sentence in _sentences(raw_text):
        if not _looks_like_prose(sentence) or len(sentence) > 70 or "문의" in sentence:
            continue
        if any(a in sentence for a in HOW_ACTION) and any(c in sentence for c in HOW_CHANNEL):
            return sentence
    return None


def _split_period(value: str) -> tuple[str, str | None]:
    """입력: 기간 칸 값, 출력: (기간, 뒤에 붙은 설명). '~ 8. 3.(월) / 사무실 제출'처럼 한 줄에 방법이 같이 오는 경우."""
    head, sep, tail = value.partition(" / ")
    if sep and re.search(r"\d", head):
        return head.strip(), tail.strip() or None
    return value, None


def _valid(label: str, value: str | None) -> bool:
    """입력: 칸 이름·후보 값, 출력: 화면에 올려도 되는 값인지 여부."""
    if not value:
        return False
    compact = re.sub(r"[\s~∼:/·\-.,()]", "", value)
    if len(compact) < 2:
        return False
    if label in ("기간", "일시"):
        return bool(re.search(r"\d", value))
    if label == "문의":
        return bool(PHONE.search(value) or EMAIL.search(value) or re.search(r"(과|팀|센터|실|처|원|단)\b", value))
    return True


def build_brief(
    title: str,
    raw_text: str,
    source: str,
    deadline: str | None,
    targets: list[str],
) -> list[BriefItem]:
    """입력: 공지 원문과 이미 추출한 마감일·대상, 출력: 칸 순서대로 채운 결과 목록.

    칸마다 [라벨 → 패턴 → 보조 정보] 순으로 시도하고, 검증을 통과한 첫 값을 쓴다.
    """
    # 한글 파일의 글머리 기호는 사용자 정의 영역 문자( 등)나 '￮'로 들어와 라벨 인식을 막고 화면에 네모로 보인다.
    raw_text = ODD_MARKS.sub("", raw_text)
    lines = [line for line in raw_text.splitlines() if line.strip()]
    # '화학교육과 공지' → '화학교육과'. '순천대 학사공지'처럼 붙어 있는 이름은 그대로 둔다.
    board = re.sub(r"\s+공지$", "", source or "").strip()
    # 앞 칸에서 떼어낸 조각을 뒤 칸이 이어받는다(예: 기간 줄 뒤에 붙은 신청방법).
    carried: dict[str, str] = {}
    fallbacks: dict[str, list[tuple[str, Callable[[], str | None]]]] = {
        "기간": [("pattern", lambda: _period_from_pattern(lines, deadline))],
        "문의": [("pattern", lambda: _contact_from_pattern(lines))],
        "신청방법": [("carried", lambda: carried.get("신청방법")), ("pattern", lambda: _how_from_sentences(raw_text))],
        "대상": [("targets", lambda: ", ".join(targets) if targets else None)],
        "주관": [("board", lambda: f"{board} (게시판 기준)" if board else None)],
    }
    items: list[BriefItem] = []
    for spec in FIELDS:
        attempts: list[tuple[str, Callable[[], str | None]]] = [
            ("label", lambda spec=spec: _from_labels(lines, spec)),
            *fallbacks.get(spec.name, []),
        ]
        chosen: BriefItem | None = None
        for method, attempt in attempts:
            value = attempt()
            if spec.name == "기간" and value:
                value, tail = _split_period(value)
                if tail and any(action in tail for action in HOW_ACTION):
                    carried["신청방법"] = tail
            if _valid(spec.name, value):
                chosen = BriefItem(spec.name, _clean(value or ""), True, method)
                break
        if chosen:
            items.append(chosen)
        elif spec.always_show:
            items.append(BriefItem(spec.name, UNKNOWN, False, None))
    return items


def missing_fields(items: list[BriefItem]) -> list[str]:
    """입력: 칸 결과 목록, 출력: 아직 못 찾은 칸 이름(항상 표시하는 칸 기준)."""
    return [item.label for item in items if not item.found]
