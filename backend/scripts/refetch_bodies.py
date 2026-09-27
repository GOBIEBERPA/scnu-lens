"""이미 저장된 학교 공지의 본문(첨부 텍스트 포함)을 다시 받아 새 추출 규칙으로 정리한다.

본문 추출 방식을 바꾼 뒤 한 번 실행한다. 새 글은 평소 크롤링이 새 규칙으로 저장하므로 필요 없다.
실행: backend 폴더에서 `python -m scripts.refetch_bodies`
"""

import asyncio
import hashlib
import sys

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.crawlers.base import ensure_school_url
from app.crawlers.scnu import ScnuBoardCrawler, with_attachments
from app.database import SessionLocal, create_tables
from app.models import Notice
from app.services.ai import LocalNoticeClassifier
from app.services.pipeline import apply_structured

REQUEST_INTERVAL_SECONDS = 0.3


async def main() -> None:
    """입력 없음, 출력 없음; 학교 게시판 공지마다 원문을 다시 받아 본문·구조화 결과를 갱신한다."""
    sys.stdout.reconfigure(encoding="utf-8")
    create_tables()
    classifier = LocalNoticeClassifier(get_settings())
    parser = ScnuBoardCrawler("https://www.scnu.ac.kr/", 1)
    changed = failed = 0
    with SessionLocal() as db:
        notices = list(db.scalars(select(Notice).where(Notice.source_url.contains("scnu.ac.kr"))))
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            for notice in notices:
                try:
                    ensure_school_url(notice.source_url)
                    response = await client.get(notice.source_url)
                    response.raise_for_status()
                    _, body = parser.parse_detail(response.text, notice.title)
                    body = await with_attachments(client, response.text, notice.source_url, body)
                except Exception as exc:
                    failed += 1
                    print(f"실패 {notice.id}: {exc}")
                    continue
                if body and body != notice.raw_text:
                    notice.raw_text = body
                    notice.content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
                    apply_structured(notice, classifier._structure_notice_sync(notice))
                    changed += 1
                await asyncio.sleep(REQUEST_INTERVAL_SECONDS)
        db.commit()
    print(f"대상 {len(notices)}건 · 본문 갱신 {changed}건 · 실패 {failed}건")


if __name__ == "__main__":
    asyncio.run(main())
