"""앱 안 알림함: 푸시를 못 받는 사용자도 알림이 쌓이는지, 읽음 처리·예정된 알림 API 테스트."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.models import Briefing, InboxItem, UserProfile
from app.services.alarms import AlarmDispatcher
from app.services.delivery import KST
from helpers import make_notice, memory_db


class FailingPush:
    """구독이 없거나 발송이 실패하는 상태."""

    async def send(self, user, title, body, url) -> bool:
        return False


@pytest.mark.asyncio
async def test_day_alarm_lands_in_inbox_without_push() -> None:
    """입력: 푸시 구독이 없는(web_only) 사용자의 마감 3일 전 공지, 출력: 푸시는 못 가도 알림함에 한 번 쌓인다."""
    today = date(2026, 9, 25)
    with memory_db()() as db:
        user = UserProfile(web_device_id="dev", department="미설정", interests=[])
        notice = make_notice("국가장학금 신청", structured_json={"deadline": (today + timedelta(days=3)).isoformat()})
        db.add_all([user, notice])
        db.flush()
        db.add(Briefing(user_id=user.id, notice_id=notice.id, relevance_reason="관심 키워드", delivery_status="web_only"))
        db.commit()
        dispatcher = AlarmDispatcher(db, Settings(), FailingPush())
        now = datetime(2026, 9, 25, 10, tzinfo=KST).astimezone(timezone.utc)
        assert await dispatcher.send_day_alarms(now) == 1
        assert await dispatcher.send_day_alarms(now) == 0
        items = db.query(InboxItem).all()
        assert [(i.kind, i.title, i.url) for i in items] == [("deadline", "⏰ 마감 D-3 · 국가장학금 신청", f"/?notice={notice.id}")]


def test_inbox_api_list_read_and_upcoming(client) -> None:
    """입력: 안 읽은 알림 2건·저장한 공지, 출력: 목록·안 읽은 수·하나 읽음·전부 읽음·예정된 알림이 맞게 나온다."""
    api, factory = client
    soon = (date.today() + timedelta(days=10)).isoformat()
    with factory() as db:
        user = UserProfile(web_device_id="dev", department="미설정", interests=[])
        notice = make_notice("TOEIC 원서접수", structured_json={"deadline": soon, "close_at": f"{soon}T10:00"})
        db.add_all([user, notice])
        db.flush()
        db.add(Briefing(user_id=user.id, notice_id=notice.id, relevance_reason="", delivery_status="saved"))
        db.add_all([
            InboxItem(user_id=user.id, notice_id=notice.id, kind="new", title="첫 알림", body="", url="/"),
            InboxItem(user_id=user.id, kind="deadline", title="둘째 알림", body="", url="/"),
        ])
        db.commit()
    data = api.get("/api/inbox", params={"web_device_id": "dev"}).json()
    assert data["unread"] == 2 and {i["title"] for i in data["items"]} == {"첫 알림", "둘째 알림"}
    first = next(i["id"] for i in data["items"] if i["title"] == "첫 알림")
    assert api.post("/api/inbox/read", json={"web_device_id": "dev", "ids": [first]}).json() == {"changed": 1, "unread": 1}
    assert api.post("/api/inbox/read", json={"web_device_id": "dev"}).json()["unread"] == 0
    assert api.get("/api/inbox/unread-count", params={"web_device_id": "nobody"}).json() == {"unread": 0}
    upcoming = api.get("/api/inbox/upcoming", params={"web_device_id": "dev"}).json()
    labels = [u["label"] for u in upcoming]
    assert labels[:2] == ["마감 7일 전", "마감 3일 전"] and "마감 10분 전" in labels and upcoming[0]["saved"] is True


@pytest.mark.asyncio
async def test_muted_deadline_push_still_lands_in_inbox() -> None:
    """입력: 마감 알림 휴대폰 받기를 끈 사용자, 출력: 푸시는 안 보내고 알림함에는 남는다."""
    today = date(2026, 9, 25)

    class CountingPush:
        calls = 0

        async def send(self, user, title, body, url) -> bool:
            CountingPush.calls += 1
            return True

    with memory_db()() as db:
        user = UserProfile(web_device_id="dev", department="미설정", interests=[], push_subscription={"e": 1},
                           alert_prefs={"deadline": False})
        notice = make_notice("장학 신청", structured_json={"deadline": (today + timedelta(days=1)).isoformat()})
        db.add_all([user, notice])
        db.flush()
        db.add(Briefing(user_id=user.id, notice_id=notice.id, relevance_reason="", delivery_status="sent"))
        db.commit()
        now = datetime(2026, 9, 25, 10, tzinfo=KST).astimezone(timezone.utc)
        assert await AlarmDispatcher(db, Settings(), CountingPush()).send_day_alarms(now) == 1
        assert CountingPush.calls == 0 and db.query(InboxItem).count() == 1


def test_for_me_skips_closed_and_puts_urgent_first(client) -> None:
    """입력: 점수가 같은 마감 지남·10일 남음·2일 남음 공지, 출력: 지난 건 빠지고 급한 것부터."""
    api, factory = client
    with factory() as db:
        db.add(UserProfile(web_device_id="dev", department="미설정", interests=["장학금"]))
        for title, days in (("지난 장학금", -1), ("여유 장학금", 10), ("급한 장학금", 2)):
            deadline = (date.today() + timedelta(days=days)).isoformat()
            db.add(make_notice(title, structured_json={"deadline": deadline}, deadline_date=deadline))
        db.commit()
    titles = [m["notice"]["title"] for m in api.get("/api/notices/for-me", params={"web_device_id": "dev"}).json()]
    assert titles == ["급한 장학금", "여유 장학금"]


def test_profile_alert_prefs_roundtrip(client) -> None:
    """입력: 알 수 없는 키가 섞인 알림 설정, 출력: 알려진 키만 저장되고 다시 읽힌다."""
    api, _ = client
    saved = api.post("/api/profiles", json={"web_device_id": "p", "alert_prefs": {"new": False, "quiet": True, "hack": True}}).json()
    assert saved["alert_prefs"] == {"new": False, "quiet": True}
    assert api.get("/api/profiles", params={"web_device_id": "p"}).json()["alert_prefs"] == {"new": False, "quiet": True}
