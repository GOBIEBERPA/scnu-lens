import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser

from app.config import get_settings
from app.crawlers.attachments import attachment_links, fetch_attachment_text
from app.crawlers.base import BaseCrawler, CrawledNotice


async def with_attachments(client: httpx.AsyncClient, html: str, page_url: str, body: str) -> str:
    """입력: 클라이언트·상세 HTML·주소·본문, 출력: 읽을 수 있는 첨부 텍스트를 뒤에 붙인 본문."""
    attached = await fetch_attachment_text(client, attachment_links(html, page_url))
    return f"{body}\n\n{attached}" if attached else body

# 줄을 바꾸는 태그. 나머지(span, b, font …)는 문장 안에서 글자 모양만 바꾸므로 줄을 끊지 않는다.
BLOCK_TAGS = ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "section", "article")


def block_text(node: Tag) -> str:
    """입력: 본문 DOM 노드, 출력: 문단 단위로만 줄을 나눈 본문 텍스트.

    get_text("\\n")은 <span>마다 줄을 끊어 "2026년 / 9 / 월 / 22 / 일"처럼 흩어 놓는다.
    그러면 '접수기간' 뒤 날짜가 잘려 상세 칸에 "2026년 9"만 남으므로, 문단 태그에서만 줄을 바꾼다.
    """
    for br in node.find_all("br"):
        br.replace_with("\n")
    for block in node.find_all(BLOCK_TAGS):
        block.insert_before("\n")
        block.append("\n")
    for cell in node.find_all(["td", "th"]):
        cell.append(" ")
    lines = (" ".join(line.split()) for line in node.get_text("").splitlines())
    return "\n".join(line for line in lines if line)


DEFAULT_SOURCES = [
    {
        "key": "academic",
        "name": "순천대 학사공지",
        "url": "https://w1.scnu.ac.kr/SCNU/na/ntt/selectNttList.do?bbsId=1041&mi=1132",
        "parser_type": "academic",
        "category_hint": "학사",
    },
    {
        "key": "scholarship",
        "name": "순천대 장학공지",
        "url": "https://w1.scnu.ac.kr/SCNU/na/ntt/selectNttList.do?bbsId=4487&mi=8690",
        "parser_type": "scholarship",
        "category_hint": "장학",
    },
    {
        "key": "computer_education",
        "name": "컴퓨터교육과 공지",
        "url": "https://www.scnu.ac.kr/comedu/na/ntt/selectNttList.do?bbsId=2030&mi=3474",
        "parser_type": "department",
        "category_hint": "학과",
    },
    {
        "key": "qnet_exam",
        "name": "국가자격 시험일정(큐넷)",
        "url": "https://www.data.go.kr/data/15074408/openapi.do",
        "parser_type": "exam_qnet",
        "category_hint": "자격증",
    },
    {
        "key": "dataq_exam",
        "name": "데이터 자격검정 시험일정(ADsP·SQLD)",
        "url": "https://www.data.go.kr/data/15062838/fileData.do",
        "parser_type": "exam_dataq",
        "category_hint": "자격증",
    },
    {
        "key": "kstartup",
        "name": "K-Startup 창업 공고",
        "url": "https://www.data.go.kr/data/15125364/openapi.do",
        "parser_type": "contest_kstartup",
        # 경진대회·교육·행사가 섞여 있어 분야를 고정하지 않고 분류기에 맡긴다.
        "category_hint": "행사",
    },
    {
        "key": "kosaf_scholarship",
        "name": "교외 장학금(한국장학재단)",
        "url": "https://www.data.go.kr/data/15028252/fileData.do",
        "parser_type": "scholar_kosaf",
        "category_hint": "장학",
    },
    {
        "key": "exam_manual",
        "name": "직접 입력한 시험일정",
        "url": "app/crawlers/manual_exams.json",
        "parser_type": "exam_manual",
        "category_hint": "자격증",
    },
]


# scripts/discover_boards.py가 찾아 둔 학과·부속기관 '공지사항' 게시판 목록.
BOARDS_FILE = Path(__file__).with_name("scnu_boards.json")


def _discovered_sources() -> list[dict[str, str]]:
    """입력 없음, 출력: 자동 수집한 게시판을 소스 형식으로 바꾼 목록; 파일이 없으면 빈 목록."""
    if not BOARDS_FILE.exists():
        return []
    known_urls = {source["url"] for source in DEFAULT_SOURCES}
    sources = []
    for board in json.loads(BOARDS_FILE.read_text(encoding="utf-8")):
        if board["url"] in known_urls:
            continue
        sources.append(
            {
                "key": f"site_{board['slug']}",
                "name": f"{board['name']} 공지",
                "url": board["url"],
                "parser_type": "department",
                "category_hint": "학과",
            }
        )
    return sources


def default_sources() -> list[dict[str, str]]:
    """입력 없음, 출력: 기본 공식 소스와 자동 수집한 학과·기관 게시판 전체의 복사본."""
    return [source.copy() for source in DEFAULT_SOURCES] + _discovered_sources()


class ScnuBoardCrawler(BaseCrawler):
    """순천대 표준 ntt 게시판에서 목록과 상세 본문을 수집하는 공통 알고리즘."""

    category_hint = "기타"

    def parse_list(self, html: str, now: datetime | None = None) -> list[tuple[str, str, str, datetime | None]]:
        """입력: 목록 HTML·기준 시각, 출력: 최근 게시글의 (외부ID, 제목, 상세URL, 게시일) 목록.

        게시판이 많아도 학교 서버 부담이 크지 않도록, 목록에서 최근 N일 글만 골라
        그 글들의 상세 페이지만 요청한다. 게시일을 알 수 없는 글은 최근 글인지 확인할 수 없어 뺀다.
        상단 고정 공지는 오래된 글이 섞여 있으므로, 오래된 글이 나와도 멈추지 않고 끝까지 본다.
        """
        cutoff = (now or datetime.now()) - timedelta(days=get_settings().crawl_recent_days)
        soup = BeautifulSoup(html, "html.parser")
        found: list[tuple[str, str, str, datetime | None]] = []
        seen: set[str] = set()
        for anchor in soup.select('a[href*="selectNttInfo.do"]'):
            href = anchor.get("href")
            if not isinstance(href, str):
                continue
            url = urljoin(self.source_url, href)
            external_id = self._extract_external_id(url)
            title = " ".join(anchor.get_text(" ", strip=True).replace("공지", "", 1).split())
            if not external_id or not title or external_id in seen:
                continue
            seen.add(external_id)
            posted = self._extract_row_date(anchor)
            if posted is None or posted < cutoff:
                continue
            found.append((external_id, title, url, posted))
            if len(found) >= self.limit:
                break
        return found

    def parse_detail(self, html: str, fallback_title: str) -> tuple[str, str]:
        """입력: 상세 HTML·목록 제목, 출력: 정제한 제목과 본문; 메뉴/푸터는 제외한다."""
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one(
            ".BD_table th.title, .bbs-view-title, .view-title, .board-view-title"
        )
        title = " ".join((title_node.get_text(" ", strip=True) if title_node else fallback_title).split())
        body_node = soup.select_one(
            ".BD_table td.dragable, .bbs-view-content, .view-content, .board-view-content, .nttCn, .cont"
        )
        if body_node is None:
            body_node = self._largest_content_candidate(soup)
        return title or fallback_title, block_text(body_node)[:30000]

    async def crawl(self) -> list[CrawledNotice]:
        """입력 없음, 출력: 목록·상세 페이지를 병렬 수집한 정규화 공지 목록."""
        timeout = httpx.Timeout(20.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": self.user_agent}) as client:
            list_html = await self.fetch_text(client, self.source_url)
            entries = [entry for entry in self.parse_list(list_html) if entry[0] not in self.known_ids]
            details = await asyncio.gather(
                *(self._fetch_detail(client, entry) for entry in entries),
                return_exceptions=True,
            )
        return [detail for detail in details if isinstance(detail, CrawledNotice)]

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        entry: tuple[str, str, str, datetime | None],
    ) -> CrawledNotice:
        """입력: HTTP 클라이언트·목록 항목, 출력: 상세 본문까지 포함한 공지 한 건."""
        external_id, fallback_title, url, published_at = entry
        html = await self.fetch_text(client, url)
        title, raw_text = self.parse_detail(html, fallback_title)
        return CrawledNotice(external_id, title, url, await with_attachments(client, html, url, raw_text or fallback_title), published_at)

    @staticmethod
    def _extract_external_id(url: str) -> str:
        """입력: 상세 URL, 출력: nttSn 쿼리값 또는 URL 기반 안정 식별자."""
        query = parse_qs(urlparse(url).query)
        return query.get("nttSn", [""])[0]

    @staticmethod
    def _extract_row_date(anchor: Tag) -> datetime | None:
        """입력: 제목 링크 노드, 출력: 같은 행에서 찾은 게시일 또는 None."""
        row = anchor.find_parent("tr") or anchor.parent
        if row is None:
            return None
        match = re.search(r"20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}", row.get_text(" ", strip=True))
        if not match:
            return None
        try:
            return date_parser.parse(match.group(0).replace(".", "-"), yearfirst=True)
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _largest_content_candidate(soup: BeautifulSoup) -> Tag:
        """입력: 상세 페이지 DOM, 출력: 텍스트가 가장 긴 article/main/section/div 노드."""
        candidates = soup.select("article, main, section, div")
        return max(candidates, key=lambda node: len(node.get_text(" ", strip=True)), default=soup)


class AcademicNoticeCrawler(ScnuBoardCrawler):
    """학사 게시판 전용 파서 타입으로 카테고리 기본값을 고정한다."""

    category_hint = "학사"


class ScholarshipNoticeCrawler(ScnuBoardCrawler):
    """장학 게시판 전용 파서 타입으로 카테고리 기본값을 고정한다."""

    category_hint = "장학"


class DepartmentNoticeCrawler(ScnuBoardCrawler):
    """학과 게시판 파서로 공통 ntt 구조를 사용하되 독립 확장 지점을 제공한다."""

    category_hint = "학과"


CRAWLER_REGISTRY: dict[str, type[ScnuBoardCrawler]] = {
    "academic": AcademicNoticeCrawler,
    "scholarship": ScholarshipNoticeCrawler,
    "department": DepartmentNoticeCrawler,
}
