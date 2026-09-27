"""사람이 확인한 정답(EvalLabel)으로 현재 분류·마감일 추출의 정확도를 잰다.

저장된 결과가 아니라 공지 원문을 지금의 분류기로 다시 돌려서 비교한다. 그래야 규칙을 고치거나
LLM을 켠 뒤 "같은 정답지로 몇 점이 됐는지"를 바로 비교할 수 있다.
"""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.models import EvalLabel
from app.services.ai import LocalNoticeClassifier

MAX_ERRORS_SHOWN = 50


def _ratio(hit: int, total: int) -> float | None:
    """입력: 맞은 수·전체 수, 출력: 소수 셋째 자리까지의 비율; 전체가 0이면 None."""
    return round(hit / total, 3) if total else None


async def evaluate(db: Session, settings: Settings) -> dict[str, object]:
    """입력: DB 세션·설정, 출력: 분류 정확도·마감일 정확도/정밀도/재현율·틀린 사례 목록."""
    labels = list(db.scalars(select(EvalLabel).options(joinedload(EvalLabel.notice))))
    classifier = LocalNoticeClassifier(settings)
    category_hit = deadline_hit = 0
    predicted_with_deadline = predicted_correct = gold_with_deadline = recalled = 0
    per_category_total: Counter[str] = Counter()
    per_category_hit: Counter[str] = Counter()
    errors: list[dict[str, object]] = []
    for label in labels:
        result = await classifier.structure_notice(label.notice)
        per_category_total[label.category] += 1
        if result.category == label.category:
            category_hit += 1
            per_category_hit[label.category] += 1
        else:
            errors.append(_error(label, "분류", label.category, result.category))
        if result.deadline == label.deadline:
            deadline_hit += 1
        else:
            errors.append(_error(label, "마감일", label.deadline or "없음", result.deadline or "없음"))
        if result.deadline:
            predicted_with_deadline += 1
            predicted_correct += int(result.deadline == label.deadline)
        if label.deadline:
            gold_with_deadline += 1
            recalled += int(result.deadline == label.deadline)
    return {
        "mode": f"규칙+LLM({settings.llm_model})" if settings.llm_enabled else "규칙",
        "labeled": len(labels),
        "category_accuracy": _ratio(category_hit, len(labels)),
        "deadline_accuracy": _ratio(deadline_hit, len(labels)),
        # 정밀도: 마감일이라고 알린 것 중 맞은 비율(틀린 D-day 알림이 얼마나 적은지).
        "deadline_precision": _ratio(predicted_correct, predicted_with_deadline),
        # 재현율: 실제 마감일이 있는 공지 중 찾아낸 비율(놓친 마감이 얼마나 적은지).
        "deadline_recall": _ratio(recalled, gold_with_deadline),
        "per_category": {
            name: {"total": total, "accuracy": _ratio(per_category_hit[name], total)}
            for name, total in sorted(per_category_total.items())
        },
        "errors": errors[:MAX_ERRORS_SHOWN],
    }


def _error(label: EvalLabel, field: str, gold: str, predicted: str) -> dict[str, object]:
    """입력: 정답·항목 이름·정답값·예측값, 출력: 화면에 보여줄 틀린 사례 한 건."""
    return {"notice_id": label.notice_id, "title": label.notice.title, "field": field, "gold": gold, "predicted": predicted}
