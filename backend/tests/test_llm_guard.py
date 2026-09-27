from datetime import date

import pytest

from app.config import Settings
from app.schemas import NoticeStructured
from app.services.llm import LlmStructurer, deadline_supported_by_text

BODY = "컴퓨터교육과 재학생은 2026.10.02까지 신청서를 제출하세요. 담당: 교무처"

BASE = NoticeStructured(
    title="장학금 신청 안내",
    category="장학",
    summary="규칙이 만든 발췌",
    deadline=None,
    target_departments=[],
    target_students=[],
    keywords=[],
    action_required=None,
    contact=None,
)


def _structurer(payload: dict | None) -> LlmStructurer:
    """입력: 모델이 반환했다고 가정할 JSON, 출력: 네트워크 없이 그 값을 쓰는 구조화기."""
    structurer = LlmStructurer(Settings())

    async def fake_ask(title: str, body: str, published: date | None) -> dict | None:
        return payload

    structurer._ask = fake_ask  # type: ignore[method-assign]
    return structurer


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        ("2026-10-02", True),  # 본문에 "2026.10.02"로 존재
        ("2026-10-03", False),  # 본문에 없는 날짜 = 환각
        ("not-a-date", False),
    ],
)
def test_deadline_must_be_supported_by_text(iso: str, expected: bool) -> None:
    """입력: 마감일 후보, 출력: 본문에서 확인되는 날짜만 통과함을 검증한다."""
    assert deadline_supported_by_text(iso, BODY) is expected


@pytest.mark.asyncio
async def test_hallucinated_deadline_is_discarded() -> None:
    """입력: 본문에 없는 마감일을 지어낸 응답, 출력: 규칙 결과(None)가 유지됨을 검증한다."""
    structurer = _structurer({"category": "장학", "summary": "요약", "deadline": "2027-01-01"})
    result = await structurer.refine(BASE, "장학금 신청 안내", BODY, None)
    assert result.deadline is None


@pytest.mark.asyncio
async def test_supported_deadline_is_accepted() -> None:
    """입력: 본문에 실제로 있는 마감일, 출력: 모델 값이 채택됨을 검증한다."""
    structurer = _structurer({"category": "장학", "summary": "요약", "deadline": "2026-10-02"})
    result = await structurer.refine(BASE, "장학금 신청 안내", BODY, None)
    assert result.deadline == "2026-10-02"


@pytest.mark.asyncio
async def test_unverifiable_departments_are_dropped() -> None:
    """입력: 본문에 없는 학과를 섞은 응답, 출력: 본문에 있는 학과만 남음을 검증한다."""
    structurer = _structurer(
        {
            "category": "장학",
            "summary": "요약",
            "deadline": None,
            "target_departments": ["컴퓨터교육과", "물리학과"],
            "target_students": ["재학생", "대학원생"],
        }
    )
    result = await structurer.refine(BASE, "장학금 신청 안내", BODY, None)
    assert result.target_departments == ["컴퓨터교육과"]
    assert result.target_students == ["재학생"]


@pytest.mark.asyncio
async def test_invalid_category_falls_back_to_rules() -> None:
    """입력: 허용 목록 밖 카테고리, 출력: 규칙이 정한 카테고리가 유지됨을 검증한다."""
    structurer = _structurer({"category": "동아리", "summary": "요약", "deadline": None})
    result = await structurer.refine(BASE, "장학금 신청 안내", BODY, None)
    assert result.category == "장학"


@pytest.mark.asyncio
async def test_llm_failure_keeps_rule_result() -> None:
    """입력: 모델 호출 실패(None), 출력: 규칙 기반 결과가 그대로 반환됨을 검증한다."""
    result = await _structurer(None).refine(BASE, "장학금 신청 안내", BODY, None)
    assert result == BASE
