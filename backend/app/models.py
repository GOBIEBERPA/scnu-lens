from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CrawlerSource(Base):
    """관리자가 켜고 끌 수 있는 공지 수집 원본 설정."""

    __tablename__ = "crawler_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    parser_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category_hint: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 마지막 수집 결과. 70곳이 넘는 게시판 중 어디가 고장 났는지 관리자 화면에서 바로 보이게 한다.
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_fetched: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    notices: Mapped[list["Notice"]] = relationship(back_populates="crawler_source")


class Notice(Base):
    """크롤링 원문과 로컬 모델 구조화 결과를 함께 보관하는 공유 지식 레코드."""

    __tablename__ = "notices"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_notice_source_external"),
        Index("ix_notices_category_published", "category", "published_at"),
        # 목록·통계는 거의 항상 "structured이고 대표 공지"만 본다.
        Index("ix_notices_status_duplicate", "processing_status", "duplicate_of"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("crawler_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    # 한글은 글자당 3바이트라 본문+첨부가 MariaDB TEXT(64KB)를 넘을 수 있다.
    raw_text: Mapped[str] = mapped_column(Text(), nullable=False)
    structured_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    category: Mapped[str] = mapped_column(String(50), default="기타", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(20), default="raw", nullable=False)
    # 같은 공지가 여러 게시판에 올라온 경우 대표 공지의 id. 목록·알림에서는 대표만 쓴다.
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # structured_json의 마감일(YYYY-MM-DD)을 따로 둔 것. JSON 안 값으로는 정렬·필터를 DB에서 할 수 없어서다.
    deadline_date: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    # 접수 시작·마감 시각(한국 시간 "YYYY-MM-DDTHH:MM", 시각을 모르면 비움). 1분마다 도는 시각 알림이
    # 모든 알림 대상을 읽지 않고 "곧 시작·마감하는 공지"만 DB에서 바로 고르게 한다.
    open_at: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    close_at: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    # 신청기간 시작일(YYYY-MM-DD). 시각을 몰라도 채운다. "접수중·접수 예정" 필터와 "접수 시작순" 정렬에 쓴다.
    open_date: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)

    crawler_source: Mapped[CrawlerSource | None] = relationship(back_populates="notices")
    briefings: Mapped[list["Briefing"]] = relationship(back_populates="notice", cascade="all, delete-orphan")


class UserProfile(Base):
    """웹 브라우저(기기) 식별자와 학과·관심사·알림 설정을 저장한다."""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    web_device_id: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str] = mapped_column(String(100), default="미설정", nullable=False)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # 알림을 받을 카테고리. 비어 있으면 전체를 받는다.
    notify_categories: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    # 브라우저가 발급한 구독 정보(endpoint/keys). 기기마다 web_device_id가 달라 한 건이면 충분하다.
    push_subscription: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # 사용자가 별표로 저장한 공지 id. 매칭과 상관없이 마감 알림을 보낸다.
    saved_notice_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    # 휴대폰 알림 종류별 켜기/끄기. {"new": 새 공지, "deadline": 마감 7·3·1일 전, "time": 접수 시각, "quiet": 밤 방해 금지}
    # 비어 있으면 모두 켜짐. 꺼도 앱 안 알림함에는 그대로 쌓인다(휴대폰으로만 안 울림).
    alert_prefs: Mapped[dict[str, bool] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    briefings: Mapped[list["Briefing"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class InboxItem(Base):
    """앱 안 알림함에 쌓이는 알림 한 건. 휴대폰 푸시를 못 받는 사용자도 앱에 들어와 확인할 수 있게 모든 알림을 남긴다."""

    __tablename__ = "inbox_items"
    __table_args__ = (Index("ix_inbox_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    notice_id: Mapped[int | None] = mapped_column(ForeignKey("notices.id", ondelete="SET NULL"), nullable=True)
    # new(새 공지)·deadline(마감 7·3·1일 전)·time(접수 시작·마감 시각)·test(테스트)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(String(300), nullable=False, default="/")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AlarmLog(Base):
    """사용자·공지·알림 종류별로 이미 보낸 알림을 기록한다. 같은 알림(예: 마감 3일 전)을 두 번 보내지 않기 위함이다.

    key 예: d7·d3·d1(마감 7·3·1일 전), open-60·open-5·open-0(접수 시작 1시간·5분 전·시작),
    close-60·close-10·close-0(마감 1시간·10분 전·마감).
    """

    __tablename__ = "alarm_logs"
    __table_args__ = (UniqueConstraint("user_id", "notice_id", "key", name="uq_alarm_user_notice_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(20), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class EvalLabel(Base):
    """사람이 확인한 정답(분류·마감일). 규칙을 바꿀 때마다 같은 정답으로 정확도를 잰다."""

    __tablename__ = "eval_labels"

    notice_id: Mapped[int] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # None이면 "마감일 없는 공지"가 정답이다.
    deadline: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    notice: Mapped[Notice] = relationship()


class Briefing(Base):
    """규칙 기반 매칭으로 특정 공지가 특정 사용자에게 해당됨을 기록하는 매칭 결과."""

    __tablename__ = "briefings"
    __table_args__ = (
        UniqueConstraint("user_id", "notice_id", name="uq_briefing_user_notice"),
        # 알림은 "이 공지를 받은 사람"을 찾으므로 공지 쪽에서 찾는 인덱스가 필요하다.
        Index("ix_briefings_notice_status", "notice_id", "delivery_status"),
        Index("ix_briefings_status", "delivery_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), nullable=False)
    relevance_reason: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped[UserProfile] = relationship(back_populates="briefings")
    notice: Mapped[Notice] = relationship(back_populates="briefings")

