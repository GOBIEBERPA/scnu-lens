from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx

# 웹페이지를 읽어 오는(크롤링) 대상은 순천대 사이트뿐이다. 다른 기관 자료는 공식 발급 API로만 받는다.
ALLOWED_CRAWL_DOMAIN = "scnu.ac.kr"


class ForbiddenCrawlTarget(ValueError):
    """학교 밖 주소를 크롤링하려 할 때 발생한다."""


def ensure_school_url(url: str) -> None:
    """입력: 요청하려는 주소, 출력 없음; 순천대(scnu.ac.kr와 그 하위 도메인) https·http 주소가 아니면 예외를 낸다."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not (host == ALLOWED_CRAWL_DOMAIN or host.endswith(f".{ALLOWED_CRAWL_DOMAIN}")):
        raise ForbiddenCrawlTarget(f"학교 사이트가 아닌 주소는 수집하지 않습니다: {url}")


@dataclass(slots=True)
class CrawledNotice:
    """파서가 DB 계층으로 넘기는 정규화된 공지 원문."""

    external_id: str
    title: str
    url: str
    raw_text: str
    published_at: datetime | None


class BaseCrawler:
    """모든 사이트별 크롤러가 따르는 비동기 수집 인터페이스."""

    user_agent = "SCNU-Lens/1.0 (+student-notice-aggregator)"

    def __init__(self, source_url: str, limit: int = 10) -> None:
        """입력: 목록 URL·최대 건수, 출력 없음; 크롤러 실행 설정을 초기화한다."""
        self.source_url = source_url
        self.limit = limit
        # 이미 저장된 글의 ID. 매시간 수집해도 새 글의 상세 페이지만 요청하도록 파이프라인이 채운다.
        self.known_ids: set[str] = set()

    async def fetch_text(self, client: httpx.AsyncClient, url: str) -> str:
        """입력: HTTP 클라이언트·URL, 출력: 인코딩이 보정된 HTML 문자열; 학교 밖 주소(리다이렉트 포함)는 거부한다."""
        ensure_school_url(url)
        response = await client.get(url, follow_redirects=True)
        # 학교 주소로 요청했어도 다른 사이트로 넘겨지면 그 내용은 쓰지 않는다.
        ensure_school_url(str(response.url))
        response.raise_for_status()
        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.charset_encoding or "utf-8"
        return response.text

    async def crawl(self) -> list[CrawledNotice]:
        """입력 없음, 출력: 소스별 파싱이 끝난 공지 목록; 하위 클래스가 구현한다."""
        raise NotImplementedError
