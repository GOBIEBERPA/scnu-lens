"""마감 7·3·1일 전 알림, 접수 시작·마감 시각 알림, 묶음 알림, 방해 금지 시간 테스트."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.models import AlarmLog, Briefing, UserProfile
from app.services.alarms import AlarmDispatcher, alarm_schedule, due_time_alarms
from app.services.delivery import KST, digest_message, in_quiet_hours
from app.services.pipeline import BatchPipeline
from helpers import make_notice, memory_db

SETTINGS = Settings(quiet_hours_start=23, quiet_hours_end=8)


class RecordingPush:
    """실제 발송 없이 웹 푸시 호출을 기록한다."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, user, title: str, body: str, url: str) -> bool:
        self.sent.append((title, body, url))
        return True



def _kst(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """입력: 한국 시간, 출력: 같은 순간의 UTC 시각(시간대 포함)."""
    return datetime(year, month, day, hour, minute, tzinfo=KST).astimezone(timezone.utc)


def _setup(db, deadlines: list[int], today: date, **structured) -> UserProfile:
    """입력: DB·마감까지 남은 일수 목록·기준일, 출력: 그 공지들을 알림 받은(sent) 구독 사용자."""
    user = UserProfile(web_device_id="dev", department="컴퓨터교육과", interests=[], push_subscription={"endpoint": "x"})
    db.add(user)
    db.flush()
    for index, days in enumerate(deadlines):
        deadline = (today + timedelta(days=days)).isoformat()
        notice = make_notice(f"공지{index} D-{days}", external_id=f"n{index}", structured_json={"deadline": deadline, **structured})
        db.add(notice)
        db.flush()
        db.add(Briefing(user_id=user.id, notice_id=notice.id, relevance_reason="이유", delivery_status="sent"))
    db.commit()
    return user


@pytest.mark.asyncio
async def test_day_alarms_7_3_1_once_after_9am() -> None:
    """입력: 마감 7·3·1·5일 남은 공지, 출력: 9시 전엔 안 보내고, 9시 후 7·3·1일만 한 번씩 보낸다."""
    today = date(2026, 9, 25)
    with memory_db()() as db:
        _setup(db, [7, 3, 1, 5], today)
        push = RecordingPush()
        dispatcher = AlarmDispatcher(db, SETTINGS, push)
        assert await dispatcher.send_day_alarms(_kst(2026, 9, 25, 7)) == 0
        assert await dispatcher.send_day_alarms(_kst(2026, 9, 25, 9, 5)) == 3
        assert sorted(title.split(" · ")[0] for title, _, _ in push.sent) == ["⏰ 마감 D-1", "⏰ 마감 D-3", "⏰ 마감 D-7"]
        # 같은 날 다음 배치에서는 다시 보내지 않는다.
        assert await dispatcher.send_day_alarms(_kst(2026, 9, 25, 13)) == 0
        assert db.query(AlarmLog).count() == 3


@pytest.mark.asyncio
async def test_many_day_alarms_are_digested() -> None:
    """입력: 같은 날 마감 3일 전인 공지 5건, 출력: 알림 하나로 묶여 나간다."""
    today = date(2026, 9, 25)
    with memory_db()() as db:
        _setup(db, [3, 3, 3, 3, 3], today)
        push = RecordingPush()
        assert await AlarmDispatcher(db, SETTINGS, push).send_day_alarms(_kst(2026, 9, 25, 10)) == 5
        assert len(push.sent) == 1 and push.sent[0][0] == "⏰ 마감 임박 5건"
        assert "외 2건" in push.sent[0][1]


def test_due_time_alarms_windows() -> None:
    """입력: 접수 시작 10:00·마감 18:00, 출력: 9:00 → 시작 1시간 전, 9:55 → 5분 전, 17:50 → 마감 10분 전, 날짜만이면 없음."""
    structured = {"open_at": "2026-10-01T10:00", "close_at": "2026-10-08T18:00"}
    keys = lambda now: [alarm.key for alarm in due_time_alarms(structured, now)]  # noqa: E731
    assert keys(_kst(2026, 10, 1, 9, 0)) == ["open-60"]
    assert keys(_kst(2026, 10, 1, 9, 55)) == ["open-5"]
    assert keys(_kst(2026, 10, 1, 10, 3)) == ["open-0"]
    assert keys(_kst(2026, 10, 8, 17, 50)) == ["close-10"]
    assert keys(_kst(2026, 10, 1, 11, 0)) == []  # 유예 10분이 지났다
    assert due_time_alarms({"open_at": "2026-10-01", "close_at": "2026-10-08"}, _kst(2026, 10, 1, 0, 0)) == []


@pytest.mark.asyncio
async def test_time_alarms_sent_once_even_in_quiet_hours() -> None:
    """입력: 접수 시작이 밤 23:30인 공지, 출력: 방해 금지 시간이어도 5분 전 알림이 한 번 나간다."""
    today = date(2026, 9, 25)
    with memory_db()() as db:
        _setup(db, [20], today, open_at="2026-09-25T23:30")
        push = RecordingPush()
        dispatcher = AlarmDispatcher(db, SETTINGS, push)
        assert await dispatcher.send_time_alarms(_kst(2026, 9, 25, 23, 25)) == 1
        assert await dispatcher.send_time_alarms(_kst(2026, 9, 25, 23, 26)) == 0
        assert push.sent[0][0].startswith("🔔 접수 시작 5분 전")
        assert push.sent[0][1] == "09월 25일 23:30 접수 시작"


def test_alarm_schedule_lists_upcoming() -> None:
    """입력: 마감일·접수 시각, 출력: 앞으로 울릴 알림만 시각 순으로."""
    plan = alarm_schedule({"deadline": "2026-10-08", "close_at": "2026-10-08T18:00"}, today=date(2026, 10, 4))
    assert plan == [
        ("2026-10-05 09:00", "마감 3일 전"),
        ("2026-10-07 09:00", "마감 1일 전"),
        ("2026-10-08 17:00", "마감 1시간 전"),
        ("2026-10-08 17:50", "마감 10분 전"),
        ("2026-10-08 18:00", "지금 접수 마감"),
    ]


def test_quiet_hours_across_midnight() -> None:
    """입력: 23~8시 방해 금지, 출력: 23시·3시는 금지, 8시·22시는 허용, 시작=끝이면 사용 안 함."""
    assert in_quiet_hours(_kst(2026, 9, 25, 23), 23, 8)
    assert in_quiet_hours(_kst(2026, 9, 26, 3), 23, 8)
    assert not in_quiet_hours(_kst(2026, 9, 26, 8), 23, 8)
    assert not in_quiet_hours(_kst(2026, 9, 25, 22), 23, 8)
    assert not in_quiet_hours(_kst(2026, 9, 26, 3), 0, 0)


@pytest.mark.asyncio
async def test_new_briefings_digest_and_quiet_hours() -> None:
    """입력: 새 매칭 공지 6건, 출력: 밤에는 보류, 아침에 알림 하나로 묶여 나간다(실제로 자정에 40건이 나갔던 문제)."""
    today = date(2026, 9, 25)
    with memory_db()() as db:
        user = UserProfile(web_device_id="dev", department="미설정", interests=[], push_subscription={"endpoint": "x"})
        db.add(user)
        db.flush()
        for index in range(6):
            notice = make_notice(f"공모전 {index}", external_id=f"c{index}", category="경진대회",
                                 structured_json={"deadline": (today + timedelta(days=index + 2)).isoformat()})
            db.add(notice)
            db.flush()
            db.add(Briefing(user_id=user.id, notice_id=notice.id, relevance_reason="이유"))
        db.commit()
        pipeline = BatchPipeline(db, SETTINGS)
        push = RecordingPush()
        pipeline.push = push
        result = type("R", (), {"sent": 0, "errors": []})()
        pipeline.clock = lambda: _kst(2026, 9, 25, 0, 30)
        await pipeline._deliver_new_briefings(result)
        assert push.sent == [] and db.query(Briefing).filter_by(delivery_status="pending").count() == 6
        pipeline.clock = lambda: _kst(2026, 9, 25, 8, 5)
        await pipeline._deliver_new_briefings(result)
        assert len(push.sent) == 1 and result.sent == 6
        title, body, url = push.sent[0]
        assert title == "📬 나에게 해당되는 새 공지 6건" and body.startswith("경진대회 6") and url == "/"


def test_digest_message_names_most_urgent() -> None:
    """입력: 마감이 다른 공지 여러 건, 출력: 분야별 개수와 가장 급한 공지를 앞에 적는다."""
    notices = [make_notice(t, structured_json={"deadline": (date.today() + timedelta(days=d)).isoformat()}, category=c)
               for t, d, c in (("느긋한 공모전", 20, "경진대회"), ("급한 장학", 2, "장학"), ("중간 공모전", 9, "경진대회"))]
    briefings = [Briefing(notice=n, relevance_reason="") for n in notices]
    title, body = digest_message(briefings)
    assert title.endswith("3건") and body.splitlines()[0] == "경진대회 2 · 장학 1"
    assert body.splitlines()[1] == "가장 급한 것: 급한 장학 (D-2)"


def test_alarm_offsets_are_configurable() -> None:
    """입력: "10,5,1"·"60,10,0" 설정, 출력: 그 시점의 알림과 사람이 읽는 이름이 만들어진다."""
    from app.services.alarms import build_time_alarms

    alarms = build_time_alarms("10,5,1", "60,10,0")
    assert [(a.key, a.label) for a in alarms] == [
        ("open-10", "접수 시작 10분 전"), ("open-5", "접수 시작 5분 전"), ("open-1", "접수 시작 1분 전"),
        ("close-60", "마감 1시간 전"), ("close-10", "마감 10분 전"), ("close-0", "지금 접수 마감"),
    ]
