"""공공데이터포털의 '한국데이터산업진흥원_데이터 자격검정 시험 정보'(ADsP·SQLD·빅데이터분석기사 등)를 공지로 만든다.

파일데이터를 공공데이터포털이 자동 변환한 API(api.odcloud.kr)라, 기관이 새 파일을 올리면 주소 끝의
uddi가 바뀐다. 그래서 매번 공식 명세(OAS)에서 가장 최근 파일의 경로를 찾아 쓴다.
공지 모양은 직접 입력 일정(manual.py)과 같게 만들어 마감 D-day·알림·캘린더가 그대로 동작한다.
"""

import re
from datetime import date

import httpx

from app.config import get_settings
from app.crawlers.base import BaseCrawler, CrawledNotice
from app.crawlers.manual import ExamSession, session_notice

SPEC_URL = "https://infuser.odcloud.kr/oas/docs"
NAMESPACE = "15062838/v1"
API_BASE = "https://api.odcloud.kr/api"
# 명세를 못 읽을 때 쓰는 2026-01-06 파일 경로.
FALLBACK_PATH = "/15062838/v1/uddi:203e0beb-5aa5-448d-a167-c6e3f0cf2f4d"
PAGE_SIZE = 500
MAX_PAGES = 5
EXAM_SITE = "https://www.dataq.or.kr/"


def latest_path(spec: dict) -> str:
    """입력: OAS 명세, 출력: 요약 끝 날짜(_YYYYMMDD)가 가장 최근인 파일의 API 경로."""
    # 글자 순이 아니라 끝의 날짜로 고른다. 기관이 파일 이름을 바꾸면 글자 순 최대가 옛 파일일 수 있다.
    paths = []
    for path, body in spec.get("paths", {}).items():
        match = re.search(r"(\d{8})\s*$", str(body.get("get", {}).get("summary", "")))
        if match:
            paths.append((match.group(1), path))
    return max(paths)[1] if paths else FALLBACK_PATH


def row_session(row: dict) -> ExamSession | None:
    """입력: API 행 하나, 출력: 시험 회차; 접수 기간이 없으면 None."""
    name = str(row.get("시험명") or "").strip()
    opens, closes = row.get("접수시작일"), row.get("접수마감일")
    if not name or not closes:
        return None
    round_no = row.get("회차")
    title = f"{name} 제{round_no}회" if round_no else name
    kind = str(row.get("시험유형") or "").strip()
    if kind and kind not in name:
        title = f"{title} {kind}"
    return ExamSession(
        key="dataq",
        title=title,
        org="한국데이터산업진흥원",
        url=EXAM_SITE,
        register=(str(opens or closes), str(closes)),
        exam_date=row.get("시험일"),
        result_date=row.get("합격자발표일"),
        result_label="합격자 발표",
    )


class DataqExamCrawler(BaseCrawler):
    """데이터 자격검정 회차 중 아직 접수할 수 있는 것만 공지로 돌려준다."""

    async def crawl(self) -> list[CrawledNotice]:
        """입력 없음, 출력: 접수 가능한 회차 공지(접수 마감 빠른 순); 키가 없거나 실패하면 빈 목록."""
        key = get_settings().data_go_kr_key
        if not key:
            return []
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            try:
                spec = (await client.get(SPEC_URL, params={"namespace": NAMESPACE})).json()
                path = latest_path(spec)
            except Exception:
                path = FALLBACK_PATH
            rows = await self._fetch(client, key, path)
        today = date.today()
        notices: dict[str, tuple[str, CrawledNotice]] = {}
        for row in rows:
            session = row_session(row)
            notice = session_notice(session, today) if session else None
            # 시험장이 여러 곳이던 옛 회차는 같은 회차가 여러 행으로 온다.
            if notice:
                notices.setdefault(notice.external_id, (session.register[1], notice))
        return [notice for _, notice in sorted(notices.values(), key=lambda pair: pair[0])][: self.limit]

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
