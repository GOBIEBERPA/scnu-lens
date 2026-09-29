"""공공데이터포털의 '한국장학재단_학자금지원정보(대학생)'에서 지금 모집 중이거나 곧 모집하는 교외 장학금을 가져온다.

전국 지자체·민간 장학재단·공공기관의 장학 상품(약 1,900건)이 매달 새 파일로 올라온다. 작년 모집분도
섞여 있어 모집종료일이 지나지 않았고 한 달 안에 모집을 시작하는 것만 남긴다.
거주지 조건(지역 연고)이 있는 장학금은 숨기지 않고 제목에 "(지역 연고)"를 붙인다. 순천대 학생도
보호자 주소지가 그 지역이면 신청할 수 있기 때문이다.
파일데이터 자동 변환 API라 주소 끝 uddi가 매달 바뀌어, dataq처럼 명세(OAS)에서 최신 경로를 찾는다.
"""

import hashlib
import re
from datetime import date, timedelta

import httpx

from app.config import get_settings
from app.crawlers.base import BaseCrawler, CrawledNotice
from app.crawlers.dataq import API_BASE, SPEC_URL

NAMESPACE = "15028252/v1"
DATASET_URL = "https://www.data.go.kr/data/15028252/fileData.do"
PAGE_SIZE = 1000
MAX_PAGES = 4
# 모집 시작이 이보다 먼 장학금은 아직 보여주지 않는다(목록이 먼 일정으로 채워지지 않게).
UPCOMING_DAYS = 30
# 전문대·원격대 전용 상품은 뺀다. 대학구분이 비어 있거나 '제한없음'이면 남긴다.
UNIVERSITY_OK = re.compile(r"4년제|제한\s*없음|해당\s*없음|전체|대학교")
NONE_WORDS = re.compile(r"^\s*[○ㅇ\-]?\s*(해당\s*없음|없음|제한\s*없음|-)?\s*$")
BULLET = re.compile(r"\s*[○ㅇ●◦•]\s*")


def newest_path(spec: dict) -> str | None:
    """입력: OAS 명세, 출력: 요약 끝 날짜가 가장 최근인 파일 경로.

    요약이 "…정보_20230220", "…정보(대학생)_20260910"처럼 이름이 중간에 바뀌어 글자 순으로 고르면
    옛 파일이 뽑힌다. 그래서 끝의 YYYYMMDD만 비교한다.
    """
    dated = []
    for path, body in spec.get("paths", {}).items():
        match = re.search(r"(\d{8})\s*$", str(body.get("get", {}).get("summary", "")))
        if match:
            dated.append((match.group(1), path))
    return max(dated)[1] if dated else None


def _clean(value: object, limit: int = 220) -> str:
    """입력: API 칸 값, 출력: '○' 항목을 ' · '로 이은 한 줄(길면 줄임). 해당없음이면 빈 문자열."""
    text = str(value or "").strip()
    if NONE_WORDS.match(text):
        return ""
    parts = [part.strip() for part in BULLET.split(text) if part.strip()]
    joined = " · ".join(parts)
    return joined if len(joined) <= limit else joined[: limit - 1] + "…"


def _grades(value: object) -> str:
    """입력: '대학2학기대학3학기…' 같은 학년구분, 출력: 읽기 쉬운 요약."""
    text = str(value or "")
    if not text or "제한없음" in text:
        return "학년 제한 없음"
    terms = sorted({int(n) for n in re.findall(r"대학(\d+)학기", text)})
    parts = []
    if "신입생" in text:
        parts.append("신입생")
    if terms:
        span = f"{terms[0]}~{terms[-1]}학기" if len(terms) > 1 else f"{terms[0]}학기"
        parts.append(span + (" 이상" if "이상" in text else ""))
    return ", ".join(parts) or text[:40]


def is_current(row: dict, today: date) -> bool:
    """입력: API 행·오늘, 출력: 마감 전이고 한 달 안에 모집을 시작하는 대학생 장학금인지 여부."""
    start, end = str(row.get("모집시작일") or "")[:10], str(row.get("모집종료일") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) or end < today.isoformat():
        return False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) and start > (today + timedelta(days=UPCOMING_DAYS)).isoformat():
        return False
    kind = str(row.get("상품구분") or "")
    school = str(row.get("대학구분") or "")
    return "장학" in kind and (not school or bool(UNIVERSITY_OK.search(school)))


def row_notice(row: dict) -> CrawledNotice:
    """입력: API 행, 출력: 상세 카드 칸(대상·기간·지원내용·제출서류·주관)이 채워지는 모양의 공지."""
    org, name = _clean(row.get("운영기관명"), 60), _clean(row.get("상품명"), 80)
    start, end = str(row.get("모집시작일") or "")[:10], str(row.get("모집종료일") or "")[:10]
    region = _clean(row.get("지역거주여부 상세내용"))
    site = str(row.get("홈페이지 주소") or "").strip()
    if site and not site.startswith("http"):
        site = f"https://{site}"
    targets = [_grades(row.get("학년구분"))]
    for label, key in (("성적", "성적기준 상세내용"), ("소득", "소득기준 상세내용"), ("자격", "특정자격 상세내용")):
        value = _clean(row.get(key), 140)
        if value:
            targets.append(f"{label}: {value}")
    lines = [
        # 마감일 추출 규칙이 "까지"를 먼저 보므로 마감 줄을 맨 앞에 둔다(시험 일정 공지와 같은 모양).
        f"접수 마감: {end}까지",
        f"접수 시작: {start}" if start else None,
        f"모집기간: {start} ~ {end}" if start else f"모집기간: ~ {end}",
        f"※ 지역 연고 장학금: {region}" if region else None,
        f"지원대상: {' / '.join(targets)}",
        f"지원내용: {_clean(row.get('지원내역 상세내용'))}" if _clean(row.get("지원내역 상세내용")) else None,
        f"선발인원: {_clean(row.get('선발인원 상세내용'), 80)}" if _clean(row.get("선발인원 상세내용")) else None,
        f"선발방법: {_clean(row.get('선발방법 상세내용'))}" if _clean(row.get("선발방법 상세내용")) else None,
        f"제출서류: {_clean(row.get('제출서류 상세내용'))}" if _clean(row.get("제출서류 상세내용")) else None,
        f"추천: {_clean(row.get('추천필요여부 상세내용'), 100)}" if _clean(row.get("추천필요여부 상세내용")) else None,
        f"자격제한: {_clean(row.get('자격제한 상세내용'))}" if _clean(row.get("자격제한 상세내용")) else None,
        f"신청방법: 운영기관 홈페이지에서 신청 ({site})" if site else "신청방법: 운영기관 공고 확인",
        f"운영기관: {org} ({_clean(row.get('운영기관구분'), 30) or '기관'})",
        "출처: 한국장학재단 학자금지원정보(공공데이터포털)",
    ]
    digest = hashlib.sha1(f"{org}|{name}|{end}".encode()).hexdigest()[:16]
    return CrawledNotice(
        external_id=f"kosaf-{digest}",
        title=f"[{org}] {name}" + (" (지역 연고)" if region else ""),
        url=site or DATASET_URL,
        raw_text="\n".join(line for line in lines if line),
        # 게시일은 비워 둔다. 모집 시작일을 넣으면 "오래된 공지"로 보고 목록에서 내린다(시험 일정과 같은 방식).
        published_at=None,
    )


class KosafScholarshipCrawler(BaseCrawler):
    """한국장학재단 학자금지원정보 중 지금 신청할 수 있거나 곧 열리는 대학생 장학금."""

    # 한 번에 수십 건이 열려 있어 기본 상한(소스당 몇 건)보다 크게 잡는다.
    limit_override = 120

    async def crawl(self) -> list[CrawledNotice]:
        """입력 없음, 출력: 마감이 빠른 순 장학금 공지; 키가 없거나 실패하면 빈 목록."""
        key = get_settings().data_go_kr_key
        if not key:
            return []
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            try:
                path = newest_path((await client.get(SPEC_URL, params={"namespace": NAMESPACE})).json())
            except Exception:
                path = None
            if not path:
                return []
            rows = await self._fetch(client, key, path)
        today = date.today()
        current = sorted((row for row in rows if is_current(row, today)), key=lambda row: str(row.get("모집종료일")))
        notices: dict[str, CrawledNotice] = {}
        for row in current:
            notice = row_notice(row)
            notices.setdefault(notice.external_id, notice)
        return list(notices.values())[: self.limit]

    async def _fetch(self, client: httpx.AsyncClient, key: str, path: str) -> list[dict]:
        """입력: 클라이언트·인증키·API 경로, 출력: 모든 페이지의 행."""
        rows: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            try:
                response = await client.get(f"{API_BASE}{path}", params={"serviceKey": key, "page": page, "perPage": PAGE_SIZE})
                response.raise_for_status()
                payload = response.json()
            except Exception:
                break
            data = payload.get("data") or []
            rows.extend(data)
            if not data or len(rows) >= int(payload.get("totalCount") or 0):
                break
        return rows
