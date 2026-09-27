"""앱 안 알림함. 푸시가 실제로 갔는지와 상관없이 모든 알림을 남겨, 앱에 들어오면 확인할 수 있게 한다."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.models import Briefing, InboxItem, Notice, UserProfile
from app.services.delivery import notice_link

# 예정된 알림을 며칠 앞까지 보여줄지.
UPCOMING_DAYS = 14


def record(db: Session, user_id: int, kind: str, title: str, body: str = "", notice: Notice | None = None, url: str | None = None) -> InboxItem:
    """입력: 사용자·종류·내용·공지, 출력: 알림함에 추가된 항목(커밋은 호출한 쪽이 한다)."""
    item = InboxItem(
        user_id=user_id,
        notice_id=notice.id if notice is not None else None,
        kind=kind,
        title=title[:300],
        body=body,
        url=url or (notice_link(notice) if notice is not None else "/"),
    )
    db.add(item)
    return item


def list_items(db: Session, user: UserProfile, limit: int = 50) -> list[InboxItem]:
    """입력: 사용자·최대 건수, 출력: 최근 알림(새것 먼저)."""
    return list(
        db.scalars(
            select(InboxItem).where(InboxItem.user_id == user.id).order_by(InboxItem.created_at.desc(), InboxItem.id.desc()).limit(limit)
        )
    )


def unread_count(db: Session, user: UserProfile) -> int:
    """입력: 사용자, 출력: 안 읽은 알림 수(상단 종 아이콘 배지)."""
    return db.scalar(
        select(func.count()).select_from(InboxItem).where(InboxItem.user_id == user.id, InboxItem.read_at.is_(None))
    ) or 0


def mark_read(db: Session, user: UserProfile, ids: list[int] | None) -> int:
    """입력: 사용자·읽음 처리할 ID(None이면 전부), 출력: 읽음으로 바뀐 수."""
    conditions = [InboxItem.user_id == user.id, InboxItem.read_at.is_(None)]
    if ids is not None:
        conditions.append(InboxItem.id.in_(ids))
    result = db.execute(
        update(InboxItem).where(*conditions).values(read_at=datetime.now(timezone.utc).replace(tzinfo=None))
    )
    db.commit()
    return result.rowcount or 0


def upcoming(db: Session, user: UserProfile, today: date | None = None) -> list[dict[str, object]]:
    """입력: 사용자·기준일, 출력: 앞으로 UPCOMING_DAYS일 안에 울릴 알림(시각 순).

    알림 대상(받은 공지·저장한 공지·앱에서만 본 공지)의 마감·접수 시각으로 알림 모듈과 같은 규칙을 계산한다.
    """
    # 알림 모듈이 이 모듈(record)을 불러오므로, 순환을 피하려고 여기서 늦게 불러온다.
    from app.config import get_settings
    from app.services.alarms import alarm_schedule, build_time_alarms

    settings = get_settings()
    alarms = build_time_alarms(settings.alarm_open_minutes, settings.alarm_close_minutes)
    today = today or date.today()
    limit = (today + timedelta(days=UPCOMING_DAYS)).isoformat()
    briefings = db.scalars(
        select(Briefing)
        .options(joinedload(Briefing.notice))
        .where(Briefing.user_id == user.id, Briefing.delivery_status.in_(["sent", "saved", "web_only", "pending"]))
    )
    plan = []
    for briefing in briefings:
        notice = briefing.notice
        for when, label in alarm_schedule(notice.structured_json or {}, today, alarms):
            if when[:10] <= limit:
                plan.append({"when": when, "label": label, "notice_id": notice.id, "title": notice.title, "saved": briefing.delivery_status == "saved"})
    return sorted(plan, key=lambda item: (item["when"], item["title"]))
