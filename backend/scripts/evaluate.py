"""정답지(관리자 화면 /admin/eval에서 확인한 공지)로 정확도를 출력한다.

    python -m scripts.evaluate          # .env 설정 그대로(LLM 꺼져 있으면 규칙만)
    python -m scripts.evaluate --llm    # LLM을 켜고 같은 정답지로 다시 채점(Ollama 필요)

두 결과를 나란히 두면 "LLM을 붙여서 몇 점 올랐는지"를 발표 자료에 그대로 쓸 수 있다.
"""

import asyncio
import json
import sys

from app.config import get_settings
from app.database import SessionLocal, create_tables
from app.services.evaluation import evaluate


async def main() -> None:
    """입력 없음(명령줄 --llm), 출력 없음; 채점 결과를 JSON으로 출력한다."""
    sys.stdout.reconfigure(encoding="utf-8")
    settings = get_settings()
    if "--llm" in sys.argv:
        settings = settings.model_copy(update={"llm_enabled": True})
    create_tables()
    with SessionLocal() as db:
        report = await evaluate(db, settings)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
