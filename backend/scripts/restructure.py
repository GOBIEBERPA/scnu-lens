"""이미 저장된 공지에 바뀐 추출·필터 규칙을 다시 적용한다(원문은 다시 받지 않는다).

마감일 규칙이나 K-Startup 지역 필터를 바꾼 뒤 한 번 실행한다. 새 글은 평소 수집이 새 규칙으로 저장한다.
실행: backend 폴더에서 `python -m scripts.restructure`
"""

import sys

from sqlalchemy import select

from app.config import get_settings
from app.crawlers.kstartup import local_elsewhere
from app.database import SessionLocal, create_tables
from app.models import Notice
from app.services.ai import LocalNoticeClassifier
from app.services.pipeline import apply_structured


def _host(raw_text: str | None) -> str:
    """입력: K-Startup 공지 원문, 출력: '주관:' 줄의 기관 이름(없으면 빈 문자열)."""
    return next((line[3:].strip() for line in (raw_text or "").splitlines() if line.startswith("주관:")), "")


def main() -> None:
    """입력 없음, 출력 없음; 목록에 보이는 공지를 다시 구조화하고, 다른 지역 한정 K-Startup 공고는 목록에서 내린다."""
    sys.stdout.reconfigure(encoding="utf-8")
    create_tables()
    classifier = LocalNoticeClassifier(get_settings())
    changed = hidden = 0
    with SessionLocal() as db:
        notices = list(db.scalars(select(Notice).where(Notice.processing_status == "structured")))
        for notice in notices:
            if (notice.source or "").startswith("K-Startup") and local_elsewhere(notice.title, _host(notice.raw_text)):
                notice.processing_status = "archived"
                hidden += 1
                print(f"목록에서 내림 #{notice.id} {notice.title[:40]}")
                continue
            before = (notice.structured_json or {}).get("deadline")
            apply_structured(notice, classifier._structure_notice_sync(notice))
            after = (notice.structured_json or {}).get("deadline")
            if before != after:
                changed += 1
                print(f"마감일 #{notice.id} {notice.title[:40]}: {before} -> {after}")
        db.commit()
    print(f"대상 {len(notices)}건 · 마감일 변경 {changed}건 · 목록에서 내림 {hidden}건")


if __name__ == "__main__":
    main()
