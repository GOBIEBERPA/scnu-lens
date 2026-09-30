"""공공데이터포털의 '한국장학재단_학자금지원정보(대학생)'에서 지금 모집 중이거나 곧 모집하는 교외 장학금을 가져온다.

전국 지자체·민간 장학재단·공공기관의 장학 상품(약 1,900건)이 매달 새 파일로 올라온다. 작년 모집분도
섞여 있어 모집종료일이 지나지 않았고 한 달 안에 모집을 시작하는 것만 남긴다.
거주지 조건(지역 연고)이 있는 장학금은 가져오지 않는다. 이 앱은 학교 공지 모음이지 지역 장학금 알리미가 아니라서,
누구나 신청할 수 있는 전국 대상 장학금만 교외 소식으로 보여준다.
파일데이터 자동 변환 API라 주소 끝 uddi가 매달 바뀌어, dataq처럼 명세(OAS)에서 최신 경로를 찾는다.
"""

import asyncio
import hashlib
import re
from datetime import date, timedelta
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.crawlers.base import BaseCrawler, CrawledNotice
from app.crawlers.dataq import API_BASE, SPEC_URL

NAMESPACE = "15028252/v1"
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


def regional(row: dict) -> bool:
    """입력: API 행, 출력: 거주지(지역 연고) 조건이 있는 장학금인지 여부."""
    return bool(_clean(row.get("지역거주여부 상세내용"))) or "지역연고" in str(row.get("학자금유형구분") or "").replace(" ", "")


def homepage(value: object, org: str) -> str:
    """입력: '홈페이지 주소' 칸·운영기관명, 출력: 열리는 주소.

    원본에 "http//…"(콜론 빠짐), "…/scholar.dopg=…"(? 빠짐), "해당없음" 같은 값이 섞여 있어 고친다.
    주소가 없으면 기관 이름으로 검색하는 링크를 준다(데이터셋 페이지보다 학생에게 쓸모 있다).
    """
    url = str(value or "").strip().split()[0] if str(value or "").strip() else ""
    url = re.sub(r"^(https?)//", r"\1://", url, flags=re.IGNORECASE)
    url = re.sub(r"\.(do|jsp|asp|aspx|php)(?=[A-Za-z_]+=)", r".\1?", url)
    if url and not re.match(r"^https?://", url, re.IGNORECASE):
        url = f"https://{url}"
    if not re.match(r"^https?://[A-Za-z0-9.-]+\.[A-Za-z]{2,}", url):
        return search_link(org)
    host = re.sub(r"^https?://(www\.)?", "", url, flags=re.IGNORECASE).split("/")[0].lower()
    return MOVED_SITES.get(host, url)


def search_link(org: str) -> str:
    """입력: 운영기관명, 출력: '기관명 장학금' 네이버 검색 주소."""
    return f"https://search.naver.com/search.naver?query={quote(org + ' 장학금')}"


# 기관이 이름·도메인을 바꿨는데 원본 데이터에 옛 주소가 남아 있는 경우(옛 주소는 열리지 않음).
MOVED_SITES = {
    # 한국야쿠르트 사회복지재단 → hy사회복지재단(2026-09 확인, 옛 kyswf.or.kr은 인증서 오류)
    "kyswf.or.kr": "https://www.ybz.or.kr/support/scholarship-apply1",
}


async def dead_link(client: httpx.AsyncClient, url: str) -> bool:
    """입력: 클라이언트·주소, 출력: 확실히 깨진 주소인지(인증서 오류·없는 도메인·4xx/5xx).

    서버가 해외(오라클 오사카)라 한국 사이트가 응답을 늦게 주거나 막는 경우가 있어,
    시간 초과는 깨진 것으로 보지 않는다(학생 휴대폰에서는 열린다).
    """
    try:
        response = await client.get(url, follow_redirects=True, timeout=httpx.Timeout(10.0, connect=6.0))
        return response.status_code >= 400 and response.status_code not in (401, 403, 405, 429)
    except httpx.TimeoutException:
        return False
    except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.UnsupportedProtocol, httpx.InvalidURL):
        return True
    except httpx.HTTPError:
        return False


def is_current(row: dict, today: date) -> bool:
    """입력: API 행·오늘, 출력: 마감 전이고 한 달 안에 모집을 시작하는 전국 대상 대학생 장학금인지 여부."""
    if regional(row):
        return False
    start, end = str(row.get("모집시작일") or "")[:10], str(row.get("모집종료일") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) or end < today.isoformat():
        return False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) and start > (today + timedelta(days=UPCOMING_DAYS)).isoformat():
        return False
    kind = str(row.get("상품구분") or "")
    school = str(row.get("대학구분") or "")
    return "장학" in kind and (not school or bool(UNIVERSITY_OK.search(school)))


def row_notice(row: dict, dead: set[str] = frozenset()) -> CrawledNotice:
    """입력: API 행·깨진 것으로 확인된 주소들, 출력: 상세 카드 칸(대상·기간·지원내용·제출서류·주관)이 채워지는 모양의 공지."""
    org, name = _clean(row.get("운영기관명"), 60), _clean(row.get("상품명"), 80)
    start, end = str(row.get("모집시작일") or "")[:10], str(row.get("모집종료일") or "")[:10]
    site = homepage(row.get("홈페이지 주소"), org)
    if site in dead:
        site = search_link(org)
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
        f"지원대상: {' / '.join(targets)}",
        f"지원내용: {_clean(row.get('지원내역 상세내용'))}" if _clean(row.get("지원내역 상세내용")) else None,
        f"선발인원: {_clean(row.get('선발인원 상세내용'), 80)}" if _clean(row.get("선발인원 상세내용")) else None,
        f"선발방법: {_clean(row.get('선발방법 상세내용'))}" if _clean(row.get("선발방법 상세내용")) else None,
        f"제출서류: {_clean(row.get('제출서류 상세내용'))}" if _clean(row.get("제출서류 상세내용")) else None,
        f"추천: {_clean(row.get('추천필요여부 상세내용'), 100)}" if _clean(row.get("추천필요여부 상세내용")) else None,
        f"자격제한: {_clean(row.get('자격제한 상세내용'))}" if _clean(row.get("자격제한 상세내용")) else None,
        f"신청방법: 운영기관 홈페이지에서 신청 ({site})" if "search.naver.com" not in site
        else "신청방법: 운영기관 공고 확인 (홈페이지 확인되지 않음)",
        f"운영기관: {org} ({_clean(row.get('운영기관구분'), 30) or '기관'})",
        "출처: 한국장학재단 학자금지원정보(공공데이터포털)",
    ]
    digest = hashlib.sha1(f"{org}|{name}|{end}".encode()).hexdigest()[:16]
    return CrawledNotice(
        external_id=f"kosaf-{digest}",
        title=f"[{org}] {name}",
        url=site,
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
            # 원본의 홈페이지가 깨져 있으면(인증서 오류·없는 도메인 등) 기관 이름 검색 링크로 바꾼다.
            sites = {homepage(row.get("홈페이지 주소"), _clean(row.get("운영기관명"), 60)) for row in current}
            checked = await asyncio.gather(*(dead_link(client, site) for site in sites if "search.naver.com" not in site))
            dead = {site for site, broken in zip([s for s in sites if "search.naver.com" not in s], checked) if broken}
        notices: dict[str, CrawledNotice] = {}
        for row in current:
            notice = row_notice(row, dead)
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
