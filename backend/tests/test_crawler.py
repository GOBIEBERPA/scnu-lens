from datetime import datetime

import pytest

from app.crawlers import default_sources
from app.crawlers.scnu import AcademicNoticeCrawler
from app.models import Notice, UserProfile
from app.services.ai import match_reason, relevance_score

LIST_HTML = """
<table><tbody>
<tr><td>공지</td><td><a href="/SCNU/na/ntt/selectNttInfo.do?bbsId=1041&mi=1132&nttSn=100">오래된 상단 고정 공지</a></td><td>교무학사과</td><td>2026.03.02</td></tr>
<tr><td>101</td><td><a href="/SCNU/na/ntt/selectNttInfo.do?bbsId=1041&mi=1132&nttSn=12345">수강신청 안내</a></td><td>교무학사과</td><td>2026.09.17</td></tr>
<tr><td>100</td><td><a href="/SCNU/na/ntt/selectNttInfo.do?bbsId=1041&mi=1132&nttSn=12300">일주일 넘은 공지</a></td><td>교무학사과</td><td>2026.09.10</td></tr>
<tr><td>99</td><td><a href="/SCNU/na/ntt/selectNttInfo.do?bbsId=1041&mi=1132&nttSn=12299">날짜 없는 공지</a></td><td>교무학사과</td><td>-</td></tr>
</tbody></table>
"""

DETAIL_HTML = """
<html><body><nav>메뉴</nav><h2 class="bbs-view-title">수강신청 안내</h2>
<div class="bbs-view-content"><p>9월 20일까지 신청하세요.</p></div></body></html>
"""

NOW = datetime(2026, 9, 20)


def _crawler() -> AcademicNoticeCrawler:
    """입력 없음, 출력: 테스트용 학사공지 크롤러."""
    return AcademicNoticeCrawler("https://w1.scnu.ac.kr/SCNU/na/ntt/selectNttList.do?bbsId=1041&mi=1132")


def test_scnu_list_and_detail_parsing() -> None:
    """입력: 축약 SCNU HTML, 출력: ID·제목·날짜·본문 파싱 정확성을 검증한다."""
    rows = _crawler().parse_list(LIST_HTML, now=NOW)
    assert rows[0][0] == "12345"
    assert rows[0][1] == "수강신청 안내"
    assert rows[0][3].strftime("%Y-%m-%d") == "2026-09-17"
    title, body = _crawler().parse_detail(DETAIL_HTML, "fallback")
    assert title == "수강신청 안내"
    assert body == "9월 20일까지 신청하세요."


def test_only_recent_week_is_collected() -> None:
    """입력: 고정 공지·일주일 넘은 글·날짜 없는 글이 섞인 목록, 출력: 최근 7일 글만 남음을 검증한다."""
    rows = _crawler().parse_list(LIST_HTML, now=NOW)
    assert [row[1] for row in rows] == ["수강신청 안내"]


@pytest.mark.asyncio
async def test_known_notices_skip_detail_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 이미 저장된 글이 있는 목록, 출력: 상세 페이지는 새 글에만 요청함을 검증한다."""
    crawler = _crawler()
    crawler.known_ids = {"12345"}
    requested: list[str] = []

    async def fake_fetch(client: object, url: str) -> str:
        requested.append(url)
        return LIST_HTML if "selectNttList" in url else DETAIL_HTML

    monkeypatch.setattr(crawler, "fetch_text", fake_fetch)
    monkeypatch.setattr(crawler, "parse_list", lambda html: [("12345", "기존 글", "u1", NOW), ("99999", "새 글", "u2", NOW)])
    notices = await crawler.crawl()
    assert [n.external_id for n in notices] == ["99999"]
    assert requested == [crawler.source_url, "u2"]


def test_every_hour_schedule_setting() -> None:
    """입력: CRAWL_CRON_HOURS='*', 출력: 0~23시 모두 수집 시각이 됨을 검증한다."""
    from app.config import Settings

    assert Settings(crawl_cron_hours="*").cron_hours == list(range(24))
    assert Settings(crawl_cron_hours="8,13,19").cron_hours == [8, 13, 19]


def test_discovered_boards_become_sources() -> None:
    """입력 없음, 출력: 자동 수집한 학과 게시판이 소스로 포함되고 키가 겹치지 않음을 검증한다."""
    sources = default_sources()
    keys = [source["key"] for source in sources]
    assert len(sources) > 50
    assert len(keys) == len(set(keys))
    assert len({source["url"] for source in sources}) == len(sources)


def test_own_department_board_notice_matches() -> None:
    """입력: 본문에 학과명이 없는 학과 게시판 공지, 출력: 그 학과 학생에게 매칭됨을 검증한다."""
    notice = Notice(
        external_id="1", source="화학교육과 공지", source_url="https://example.com",
        title="실험실 사용 안내", raw_text="다음 주부터 실험실 사용 시간이 바뀝니다.",
        category="기타", content_hash="x" * 64,
    )
    mine = UserProfile(department="화학교육과", interests=[], notify_categories=[])
    other = UserProfile(department="수학교육과", interests=[], notify_categories=[])
    assert relevance_score(mine, notice) >= 1.5
    assert "내 학과(화학교육과)" in match_reason(mine, notice)
    assert relevance_score(other, notice) < 1.5


def test_detail_body_keeps_inline_spans_on_one_line() -> None:
    """입력: 날짜가 <span>마다 쪼개진 실제 원문 모양, 출력: 문단 단위로만 줄이 나뉘어 날짜가 이어짐을 검증한다."""
    html = (
        '<div class="cont"><p>▶ 접수기간 : 2026년 <span>9</span><span>월</span> <span>22</span><span>일</span></p>'
        "<p>▶ 접수방법 : 이메일</p>줄1<br>줄2</div>"
    )
    _, body = AcademicNoticeCrawler("https://w1.scnu.ac.kr/", 5).parse_detail(html, "제목")
    assert body.splitlines() == ["▶ 접수기간 : 2026년 9월 22일", "▶ 접수방법 : 이메일", "줄1", "줄2"]


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://www.scnu.ac.kr/SCNU/na/ntt/selectNttList.do", True),
        ("https://w1.scnu.ac.kr/SCNU/main.do", True),
        ("https://scnu.ac.kr/", True),
        ("https://www.wevity.com/?c=find", False),
        ("https://exam.toeic.co.kr/receipt/examSchList.php", False),
        ("https://scnu.ac.kr.evil.example/", False),
        ("ftp://www.scnu.ac.kr/", False),
    ],
)
def test_only_school_sites_are_crawled(url: str, allowed: bool) -> None:
    """입력: 학교·학교 밖·흉내 낸 주소, 출력: 순천대(scnu.ac.kr 하위) http(s) 주소만 허용됨을 검증한다."""
    from app.crawlers.base import ForbiddenCrawlTarget, ensure_school_url

    if allowed:
        ensure_school_url(url)
    else:
        with pytest.raises(ForbiddenCrawlTarget):
            ensure_school_url(url)
