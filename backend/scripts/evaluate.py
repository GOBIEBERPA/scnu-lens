"""정답지(관리자 화면 /admin/eval에서 확인한 공지)로 정확도를 출력한다.

    python -m scripts.evaluate

규칙을 고친 뒤 같은 정답지로 다시 채점해 전후 점수를 비교한다.
"""

import asyncio
import json
import sys

from app.config import get_settings
from app.database import SessionLocal, create_tables
from app.services.evaluation import evaluate


async def main() -> None:
    """입력 없음, 출력 없음; 채점 결과를 JSON으로 출력한다."""
    sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    create_tables()
    with SessionLocal() as db:
        report = await evaluate(db, settings)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
