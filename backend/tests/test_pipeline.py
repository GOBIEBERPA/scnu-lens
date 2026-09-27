import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.crawlers.base import CrawledNotice
from app.database import Base
from app.models import Briefing, CrawlerSource, Notice, UserProfile
from app.services import pipeline as pipeline_module
from app.services.pipeline import BatchPipeline


class FakeCrawler:
    """네트워크 없이 파이프라인을 검증하는 고정 결과 크롤러."""

    def __init__(self, source_url: str, limit: int) -> None:
        """입력: URL·제한, 출력 없음; 인터페이스 호환 값만 보관한다."""
        self.source_url = source_url
        self.limit = limit

    async def crawl(self) -> list[CrawledNotice]:
        """입력 없음, 출력: 장학 공지 한 건."""
        return [CrawledNotice("fake-1", "AI 장학금 신청", self.source_url, "컴퓨터교육과 9월 30일까지 신청", None)]


@pytest.mark.asyncio
async def test_notify_categories_filter_blocks_other_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 자격증만 받기로 한 사용자, 출력: 장학 공지로는 알림이 생기지 않음을 검증한다."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(CrawlerSource(key="fake", name="가짜", url="https://example.com", parser_type="fake", category_hint="장학"))
        db.add(
            UserProfile(
                web_device_id="device",
                department="컴퓨터교육과",
                interests=["AI"],
                notify_categories=["자격증"],
            )
        )
        db.commit()
        monkeypatch.setattr(pipeline_module, "ensure_default_sources", lambda session: None)
        monkeypatch.setitem(pipeline_module.CRAWLER_REGISTRY, "fake", FakeCrawler)
        result = await BatchPipeline(db, Settings()).run()
        assert result.structured == 1
        assert result.briefings_created == 0
        assert db.scalar(select(Briefing)) is None


@pytest.mark.asyncio
async def test_pipeline_reuses_notice_for_briefing(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 가짜 크롤러·사용자, 출력: 원문 구조화와 같은 Notice 기반 브리핑 생성을 검증한다."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(CrawlerSource(key="fake", name="가짜", url="https://example.com", parser_type="fake", category_hint="장학"))
        db.add(UserProfile(web_device_id="device", department="컴퓨터교육과", interests=["AI"]))
        db.commit()
        monkeypatch.setattr(pipeline_module, "ensure_default_sources", lambda session: None)
        monkeypatch.setitem(pipeline_module.CRAWLER_REGISTRY, "fake", FakeCrawler)
        result = await BatchPipeline(db, Settings()).run()
        notice = db.scalar(select(Notice).where(Notice.external_id == "fake-1"))
        briefing = db.scalar(select(Briefing))
        assert result.inserted == 1
        assert result.structured == 1
        assert notice is not None and notice.structured_json is not None
        assert briefing is not None and briefing.notice_id == notice.id
