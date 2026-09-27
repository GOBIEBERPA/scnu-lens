"""여러 테스트 파일이 함께 쓰는 공지·메모리 DB 도우미."""

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Notice


def make_notice(title: str, **extra) -> Notice:
    """입력: 제목·추가 필드, 출력: 목록에 보이는 상태(structured)의 테스트용 공지.

    구조화 결과에 마감일·접수 시각이 있으면 파이프라인(apply_structured)처럼 같은 값을 컬럼에도 채운다.
    """
    structured = extra.get("structured_json") or {}
    extra.setdefault("deadline_date", structured.get("deadline"))
    for column in ("open_at", "close_at"):
        value = structured.get(column)
        extra.setdefault(column, value if isinstance(value, str) and "T" in value else None)
    defaults = dict(
        external_id=title,
        source="테스트 공지",
        source_url="https://example.com/n",
        raw_text="본문",
        category="기타",
        content_hash="x" * 64,
        processing_status="structured",
        published_at=datetime(2026, 9, 20),
    )
    return Notice(title=title, **{**defaults, **extra})


def memory_db() -> sessionmaker:
    """입력 없음, 출력: 테스트마다 새로 만드는 메모리 SQLite 세션 팩토리."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
