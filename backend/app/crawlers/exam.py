"""공공데이터포털의 국가자격 시험일정을 공지와 같은 형태로 가져온다.

별도 모델을 두지 않고 기존 Notice 파이프라인에 그대로 태운다. 그래야 마감 D-day,
개인화 매칭, 알림이 추가 작업 없이 똑같이 동작한다.
"""

from datetime import date, datetime

import httpx

from app.config import get_settings
from app.crawlers.base import BaseCrawler, CrawledNotice

API_URL = "https://apis.data.go.kr/B490007/qualExamSchd/getQualExamSchdList"

# 조회할 자격 구분. T=국가기술자격(기사·산업기사·기능사 등)
QUALIFICATION_KINDS = ("T",)

# API가 한 페이지에 50건까지만 허용한다(초과 시 resultCode 930).
PAGE_SIZE = 50
MAX_PAGES = 10

# API가 글 주소를 주지 않으므로 큐넷의 등급별 시험일정 페이지로 연결한다(페이지 제목으로 확인한 값).
# 긴 이름부터 비교해야 '산업기사'·'기능사'가 '기사'로 잡히지 않는다.
QNET_SCHEDULE_URL = "https://www.q-net.or.kr/crf021.do?id=crf02101&gSite=Q&gId=&scheType={code}"
GRADE_PAGES: tuple[tuple[str, str], ...] = (
    ("기능장", "02"),
    ("기술사", "01"),
    ("산업기사", "03"),
    ("기능사", "04"),
    ("기사", "03"),
)


def schedule_page(description: str) -> str:
    """입력: '국가기술자격 기사 (2026년도 제3회)' 같은 회차 설명, 출력: 해당 등급의 큐넷 시험일정 주소."""
    code = next((code for grade, code in GRADE_PAGES if grade in description), "05")
    return QNET_SCHEDULE_URL.format(code=code)


# 한 회차에 필기와 실기 일정이 따로 온다. 필드 접두어와 화면에 쓸 이름.
PHASES = (("doc", "필기"), ("prac", "실기"))


def _as_date(value: object) -> str | None:
    """입력: API의 YYYYMMDD 문자열, 출력: YYYY-MM-DD 또는 값이 없으면 None."""
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


class QnetExamCrawler(BaseCrawler):
    """큐넷 국가자격 시험일정을 회차·필기/실기 단위 공지로 변환한다."""

    async def crawl(self) -> list[CrawledNotice]:
        """입력 없음, 출력: 아직 끝나지 않은 시험 일정 목록; 키가 없으면 빈 목록."""
        settings = get_settings()
        if not settings.data_go_kr_key:
            return []
        rows: list[dict] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            for kind in QUALIFICATION_KINDS:
                rows.extend(await self._fetch(client, settings.data_go_kr_key, kind))
        today = date.today().isoformat()
        # 학생에게 쓸모 있는 건 아직 신청할 수 있는 회차다. API가 같은 행을 두 번 주기도 해서 ID로 중복을 뺀다.
        open_now: dict[str, tuple[CrawledNotice, str]] = {}
        for row in rows:
            for notice, registration_end in self._to_notices(row):
                if registration_end >= today:
                    open_now.setdefault(notice.external_id, (notice, registration_end))
        ordered = sorted(open_now.values(), key=lambda pair: pair[1])
        return [notice for notice, _ in ordered][: self.limit]

    async def _fetch(self, client: httpx.AsyncClient, key: str, kind: str) -> list[dict]:
        """입력: 클라이언트·인증키·자격구분, 출력: 모든 페이지의 일정 항목 목록."""
        collected: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            params = {
                "serviceKey": key,
                "dataFormat": "json",
                "implYy": date.today().year,
                "qualgbCd": kind,
                "numOfRows": PAGE_SIZE,
                "pageNo": page,
            }
            try:
                response = await client.get(API_URL, params=params)
                response.raise_for_status()
                payload = response.json()
            except Exception:
                break
            # 이 API는 오류도 HTTP 200으로 주고 header.resultCode로만 알린다.
            if payload.get("header", {}).get("resultCode") != "00":
                break
            body = payload.get("body", {})
            items = body.get("items", [])
            if isinstance(items, dict):
                items = items.get("item", [])
            items = items if isinstance(items, list) else [items]
            collected.extend(items)
            if not items or len(collected) >= int(body.get("totalCount") or 0):
                break
        return collected

    @staticmethod
    def _to_notices(row: dict) -> list[tuple[CrawledNotice, str]]:
        """입력: API 항목 하나, 출력: 필기·실기별 (공지, 접수 마감일) 목록."""
        name = str(row.get("description") or "").strip()
        if not name:
            return []
        # "국가기술자격 기능사 (2026년도 제107회)" → "국가기술자격 기능사 제107회"
        short = name.replace("(", "").replace(")", "")
        for noise in (f"{row.get('implYy', '')}년도 ",):
            short = short.replace(noise, "")
        results: list[tuple[CrawledNotice, str]] = []
        for prefix, label in PHASES:
            start = _as_date(row.get(f"{prefix}RegStartDt"))
            end = _as_date(row.get(f"{prefix}RegEndDt"))
            exam_start = _as_date(row.get(f"{prefix}ExamStartDt"))
            exam_end = _as_date(row.get(f"{prefix}ExamEndDt"))
            result_day = _as_date(row.get(f"{prefix}PassDt"))
            if not end:
                continue
            exam = exam_start if not exam_end or exam_end == exam_start else f"{exam_start} ~ {exam_end}"
            body = "\n".join(
                line
                for line in (
                    f"{label} 원서접수: {start} ~ {end}" if start and start != end else f"{label} 원서접수: {end}",
                    f"{label} 시험일: {exam}" if exam_start else None,
                    f"합격발표: {result_day}" if result_day else None,
                    f"접수는 {end}까지입니다.",
                    "접수방법: 큐넷(www.q-net.or.kr) 온라인 원서접수",
                    "시행기관: 한국산업인력공단",
                    "출처: 한국산업인력공단 국가자격 시험일정(공공데이터포털)",
                )
                if line
            )
            # 같은 회차·단계에 추가접수가 따로 열리기도 해서 접수 마감일까지 ID에 넣는다.
            external_id = f"qnet-{row.get('implYy')}-{row.get('qualgbCd')}-{row.get('implSeq')}-{prefix}-{end}"
            notice = CrawledNotice(
                external_id=external_id,
                title=f"{short} {label} 원서접수",
                url=schedule_page(name),
                raw_text=body,
                published_at=None,
            )
            results.append((notice, end))
        return results
