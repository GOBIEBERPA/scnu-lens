"""알림을 언제·몇 개로 보낼지 정한다.

공모전·시험 일정처럼 한 번에 수십 건이 들어오는 소스가 생기면서, 건마다 알림을 보내면
휴대폰이 수십 번 울린다(실제로 자정에 한 사용자에게 40건이 나갔다). 그래서
(1) 한 번에 여러 건이면 한 개로 묶어 보내고 (2) 밤에는 보내지 않고 모아 뒀다가 아침에 보낸다.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.models import Briefing
from app.services.ai import days_until_deadline

# 한국은 서머타임이 없어 고정 시차로 충분하다(윈도우에서 zoneinfo는 tzdata가 따로 필요하다).
KST = timezone(timedelta(hours=9))
# 한 사용자에게 한 번에 이보다 많이 쌓이면 묶음 알림 하나로 보낸다.
DIGEST_THRESHOLD = 3
# 묶음 알림 본문에 제목을 몇 개까지 적을지.
DIGEST_TITLES = 2


def in_quiet_hours(now: datetime, start: int, end: int) -> bool:
    """입력: 현재 시각(UTC)·방해 금지 시작·끝 시(한국 시간), 출력: 지금 알림을 보내면 안 되는지.

    start == end면 방해 금지를 쓰지 않는다. 23→8처럼 자정을 넘는 구간도 처리한다.
    """
    if start == end:
        return False
    hour = now.astimezone(KST).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def _short(title: str, limit: int = 28) -> str:
    """입력: 공지 제목, 출력: 잠금 화면에 맞게 줄인 제목."""
    return title if len(title) <= limit else f"{title[:limit]}…"


def _by_deadline(briefings: list[Briefing]) -> list[Briefing]:
    """입력: 브리핑 목록, 출력: 마감이 가까운 순(마감일 없는 것은 뒤)."""
    return sorted(briefings, key=lambda b: (days_until_deadline(b.notice) is None, days_until_deadline(b.notice) or 0))


def digest_message(briefings: list[Briefing]) -> tuple[str, str]:
    """입력: 한 사용자의 새 브리핑 여러 건, 출력: 묶음 알림 (제목, 본문).

    예) "나에게 해당되는 새 공지 23건" / "경진대회 12 · 자격증 8 · 취업 3\n가장 급한 것: SK하이닉스 AI 해커톤 (D-4)"
    """
    counts = Counter(b.notice.category for b in briefings)
    lines = [" · ".join(f"{name} {count}" for name, count in counts.most_common())]
    urgent = [b for b in _by_deadline(briefings) if days_until_deadline(b.notice) is not None][:DIGEST_TITLES]
    for index, briefing in enumerate(urgent):
        prefix = "가장 급한 것" if index == 0 else "다음"
        lines.append(f"{prefix}: {_short(briefing.notice.title)} (D-{days_until_deadline(briefing.notice)})")
    return f"📬 나에게 해당되는 새 공지 {len(briefings)}건", "\n".join(lines)


def reminder_digest_message(items: list[tuple[Briefing, int]]) -> tuple[str, str]:
    """입력: (브리핑, 남은 일수) 여러 건, 출력: 마감 임박 묶음 알림 (제목, 본문)."""
    ordered = sorted(items, key=lambda item: item[1])
    lines = [f"{'오늘' if days == 0 else f'D-{days}'} · {_short(b.notice.title)}" for b, days in ordered[:3]]
    if len(ordered) > 3:
        lines.append(f"외 {len(ordered) - 3}건")
    return f"⏰ 마감 임박 {len(items)}건", "\n".join(lines)


def wants(user, key: str) -> bool:
    """입력: 사용자·알림 종류(new·deadline·time·quiet), 출력: 그 종류를 휴대폰으로 받을지(설정이 없으면 켜짐)."""
    return bool((user.alert_prefs or {}).get(key, True))


def notice_link(notice) -> str:
    """입력: 공지, 출력: 알림을 눌렀을 때 열 앱 안 주소. 정리된 칸을 먼저 보고 원문으로 넘어가게 한다."""
    return f"/?notice={notice.id}"


def utc_now() -> datetime:
    """입력 없음, 출력: 현재 UTC 시각(시간대 포함)."""
    return datetime.now(timezone.utc)
