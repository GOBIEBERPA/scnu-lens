"""여러 게시판에 같은 공지가 올라온 경우 하나로 묶는다.

학사 공지를 학과 게시판에 그대로 다시 올리는 일이 흔해서, 묶지 않으면 목록에 같은 글이 두세 번 보이고
알림도 여러 번 간다. 대표 공지만 목록·알림에 쓰고, 나머지는 "다른 게시판에도 게시"로만 보여준다.
"""

import re
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Notice

# 제목이 이만큼 비슷하면 같은 공지로 본다. 회차·학기만 다른 공지(1차/2차)는 이보다 낮게 나온다.
SIMILARITY_THRESHOLD = 0.93
# 한쪽 제목이 다른 쪽 제목으로 시작할 때("…안내" vs "…안내에 대한 상세정보 …") 인정하는 최소 길이.
MIN_PREFIX_LENGTH = 12
# 대표로 우선 고르는 학교 본부 게시판 이름의 앞머리.
CENTRAL_PREFIX = "순천대 "


def normalize_title(title: str) -> str:
    """입력: 공지 제목, 출력: 말머리([학생상담센터] 등)·기호·공백을 뺀 비교용 문자열."""
    title = re.sub(r"\[[^\]]*\]|【[^】]*】|<[^>]*>|\([^)]*공지[^)]*\)", "", title)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", title).lower()


def same_notice(a: str, b: str) -> bool:
    """입력: 정규화한 제목 두 개, 출력: 같은 공지로 볼지 여부."""
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= MIN_PREFIX_LENGTH and longer.startswith(shorter):
        return True
    # 숫자(회차·날짜)가 다르면 다른 공지다. "1차 신청"과 "2차 신청"은 제목이 거의 같아도 별개다.
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    # 비싼 ratio() 전에 상한값으로 먼저 거른다. 길이 차이만으로 상한이 기준 미만이면 볼 것도 없다.
    # (공지 수천 건을 쌍으로 비교할 때 대부분의 쌍이 여기서 끝난다.)
    matcher = SequenceMatcher(None, a, b)
    return (
        matcher.real_quick_ratio() >= SIMILARITY_THRESHOLD
        and matcher.quick_ratio() >= SIMILARITY_THRESHOLD
        and matcher.ratio() >= SIMILARITY_THRESHOLD
    )


def mark_duplicates(db: Session) -> int:
    """입력: DB 세션, 출력: 중복으로 표시된 공지 수.

    목록에 보이는 공지(structured) 전체를 매번 다시 묶는다. 수백 건 수준이라 비용이 작고,
    대표 공지가 보관 처리되면 다음 공지가 자연스럽게 대표가 된다.
    """
    notices = list(
        db.scalars(select(Notice).where(Notice.processing_status == "structured").order_by(Notice.id))
    )
    # 본부 게시판 글을 대표로 먼저 두고, 같은 조건이면 먼저 수집된 글을 대표로 둔다.
    notices.sort(key=lambda n: (not (n.source or "").startswith(CENTRAL_PREFIX), n.id))
    # same_notice와 같은 규칙을 공지 수천 건에서도 빠르게 적용하려고 비교 대상을 줄인다.
    # - 제목이 똑같으면 사전으로 바로 찾는다.
    # - 유사도 비교는 숫자(회차·날짜)가 같은 대표끼리만 한다(숫자가 다르면 어차피 다른 공지).
    # - 앞부분 일치("…안내" vs "…안내에 대한 상세정보 2026…")는 숫자가 달라도 되므로 전체와 비교하되 startswith만 쓴다.
    exact: dict[str, Notice] = {}
    by_digits: dict[tuple[str, ...], list[tuple[str, Notice]]] = {}
    long_keys: list[tuple[str, Notice]] = []
    duplicates = 0
    for notice in notices:
        key = normalize_title(notice.title)
        leader = exact.get(key) if key else None
        if leader is None and len(key) >= MIN_PREFIX_LENGTH:
            leader = next(
                (lead for lead_key, lead in long_keys if key.startswith(lead_key) or lead_key.startswith(key)), None
            )
        digits = tuple(re.findall(r"\d+", key))
        if leader is None and key:
            for lead_key, lead in by_digits.get(digits, []):
                matcher = SequenceMatcher(None, key, lead_key)
                if (
                    matcher.real_quick_ratio() >= SIMILARITY_THRESHOLD
                    and matcher.quick_ratio() >= SIMILARITY_THRESHOLD
                    and matcher.ratio() >= SIMILARITY_THRESHOLD
                ):
                    leader = lead
                    break
        if leader is None:
            notice.duplicate_of = None
            if key:
                exact[key] = notice
                by_digits.setdefault(digits, []).append((key, notice))
                if len(key) >= MIN_PREFIX_LENGTH:
                    long_keys.append((key, notice))
        else:
            notice.duplicate_of = leader.id
            duplicates += 1
    db.commit()
    return duplicates
