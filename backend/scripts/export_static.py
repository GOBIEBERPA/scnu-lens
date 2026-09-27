"""서버 없이 도는 정적 버전(static-app/)이 읽을 공지 데이터 파일(notices.js)을 DB에서 뽑는다.

    python -m scripts.export_static

사용자·푸시 구독 같은 개인정보는 넣지 않는다. 목록에 보이는 공지(구조화 완료·중복 대표)만 넣는다.
notices.json이 아니라 notices.js인 이유: index.html을 더블클릭(file://)으로 열면 브라우저가 JSON 파일 읽기를 막지만
<script>로 읽는 파일은 허용하기 때문이다.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.crawlers.attachments import body_only
from app.database import SessionLocal
from app.models import CrawlerSource, Notice

OUT = Path(__file__).resolve().parents[2] / "static-app" / "notices.js"
# 검색·추천에 쓸 본문 앞부분 길이. 전부 넣으면 파일이 수 MB가 된다.
TEXT_LIMIT = 400


def is_external(source: CrawlerSource | None) -> bool:
    """입력: 수집 소스, 출력: 공모전·시험 일정(학교 밖 공식 API) 소스인지 여부."""
    return source is not None and source.parser_type.startswith(("exam_", "contest_"))


def to_item(notice: Notice) -> dict:
    """입력: 공지, 출력: 정적 앱이 쓰는 필드만 담은 사전."""
    structured = notice.structured_json or {}
    return {
        "id": notice.id,
        "title": notice.title,
        "board": notice.source,
        "url": notice.source_url,
        "category": notice.category,
        "origin": "external" if is_external(notice.crawler_source) else "school",
        "published": notice.published_at.date().isoformat() if notice.published_at else None,
        "deadline": notice.deadline_date,
        "open_at": notice.open_at,
        "close_at": notice.close_at,
        "details": [{"label": b["label"], "value": b["value"]} for b in structured.get("brief", []) if b.get("found")],
        "schedule": structured.get("schedule", []),
        "targets": structured.get("target_departments", []),
        "text": " ".join(body_only(notice.raw_text).split())[:TEXT_LIMIT],
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with SessionLocal() as db:
        notices = db.scalars(
            select(Notice)
            .where(Notice.processing_status == "structured", Notice.duplicate_of.is_(None), ~Notice.title.startswith("[테스트]"))
            .order_by(Notice.published_at.desc(), Notice.id.desc())
        ).all()
        items = [to_item(notice) for notice in notices]
    payload = {"exported_at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "notices": items}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        "// scripts/export_static.py가 만든 파일. 직접 고치지 말고 스크립트로 다시 만든다.\n"
        f"window.SCNU_DATA = {json.dumps(payload, ensure_ascii=False)};\n",
        encoding="utf-8",
    )
    print(f"{len(items)}건 → {OUT} ({OUT.stat().st_size / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
