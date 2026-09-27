from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserProfile


def find_user(db: Session, web_device_id: str | None) -> UserProfile | None:
    """입력: DB 세션·웹 기기 ID, 출력: 일치하는 사용자 또는 None."""
    if not web_device_id:
        return None
    return db.scalar(select(UserProfile).where(UserProfile.web_device_id == web_device_id))
