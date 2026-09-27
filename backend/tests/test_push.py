import pytest
from pywebpush import WebPushException

from app.config import Settings
from app.models import UserProfile
from app.services import push as push_module
from app.services.push import WebPushSender

SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/FAKE",
    "keys": {"p256dh": "fake-p256dh", "auth": "fake-auth"},
}
KEYED = Settings(vapid_public_key="pub", vapid_private_key="priv")
# .env에 실제 키가 들어 있어도 '키 없음' 상태를 확실히 만들기 위해 명시적으로 비운다.
KEYLESS = Settings(vapid_public_key="", vapid_private_key="")


class FakeResponse:
    """만료된 구독에 대한 푸시 서버 응답을 흉내 낸다."""

    def __init__(self, status_code: int) -> None:
        """입력: 상태 코드, 출력 없음; 응답 객체 형태만 맞춘다."""
        self.status_code = status_code


def _user() -> UserProfile:
    """입력 없음, 출력: 구독 정보를 가진 테스트용 사용자."""
    return UserProfile(web_device_id="device", department="컴퓨터교육과", interests=["AI"], push_subscription=dict(SUBSCRIPTION))


@pytest.mark.asyncio
async def test_disabled_without_vapid_keys() -> None:
    """입력: VAPID 키가 없는 설정, 출력: 발송하지 않고 False를 반환함을 검증한다."""
    sender = WebPushSender(KEYLESS)
    assert sender.enabled is False
    assert await sender.send(_user(), "제목", "본문", "https://example.com") is False


@pytest.mark.asyncio
async def test_no_subscription_is_skipped() -> None:
    """입력: 구독하지 않은 사용자, 출력: 발송을 시도하지 않음을 검증한다."""
    user = _user()
    user.push_subscription = None
    assert await WebPushSender(KEYED).send(user, "제목", "본문", "https://example.com") is False


@pytest.mark.asyncio
async def test_sends_payload_with_title_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 구독한 사용자, 출력: 제목·본문·링크가 담긴 페이로드로 발송됨을 검증한다."""
    captured: dict = {}

    def fake_webpush(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(push_module, "webpush", fake_webpush)
    assert await WebPushSender(KEYED).send(_user(), "장학금 마감", "관심 키워드와 일치", "https://scnu.ac.kr/1") is True
    assert captured["subscription_info"] == SUBSCRIPTION
    assert "장학금 마감" in captured["data"]
    assert "https://scnu.ac.kr/1" in captured["data"]


@pytest.mark.asyncio
async def test_expired_subscription_is_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 410 Gone 응답, 출력: 저장된 구독을 지워 다음 배치에서 재시도하지 않음을 검증한다."""

    def fake_webpush(**_: object) -> None:
        raise WebPushException("gone", response=FakeResponse(410))

    monkeypatch.setattr(push_module, "webpush", fake_webpush)
    user = _user()
    assert await WebPushSender(KEYED).send(user, "제목", "본문", "https://example.com") is False
    assert user.push_subscription is None


@pytest.mark.asyncio
async def test_push_test_endpoint_reports_each_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 키 없음·구독 없음·정상 구독, 출력: 테스트 알림 결과와 이유가 상황별로 맞는지 검증한다."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.api.routes import push_test
    from app.database import Base

    sent: list[dict] = []
    monkeypatch.setattr(push_module, "webpush", lambda **kwargs: sent.append(kwargs))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(UserProfile(web_device_id="no-sub", department="미설정", interests=[], notify_categories=[]))
        db.add(_user())
        db.commit()

        no_keys = await push_test(web_device_id="device", db=db, settings=KEYLESS)
        assert no_keys["ok"] is False and "VAPID" in no_keys["reason"]

        no_sub = await push_test(web_device_id="no-sub", db=db, settings=KEYED)
        assert no_sub["ok"] is False and "구독" in no_sub["reason"]

        ok = await push_test(web_device_id="device", db=db, settings=KEYED)
        assert ok["ok"] is True
        assert "테스트 알림" in sent[-1]["data"]


@pytest.mark.asyncio
async def test_temporary_failure_keeps_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 일시적 서버 오류(500), 출력: 구독을 유지해 다음에 다시 시도함을 검증한다."""

    def fake_webpush(**_: object) -> None:
        raise WebPushException("boom", response=FakeResponse(500))

    monkeypatch.setattr(push_module, "webpush", fake_webpush)
    user = _user()
    assert await WebPushSender(KEYED).send(user, "제목", "본문", "https://example.com") is False
    assert user.push_subscription == SUBSCRIPTION


@pytest.mark.asyncio
async def test_send_all_runs_concurrently_and_isolates_failures() -> None:
    """입력: 느린 푸시 20건(그중 한 건은 예외), 출력: 동시에 보내져 빨리 끝나고, 실패는 그 건에만 남는다."""
    import asyncio
    import time

    from app.services.push import send_all

    class Slow:
        async def send(self, user, title, body, url) -> bool:
            await asyncio.sleep(0.1)
            if title == "boom":
                raise RuntimeError("푸시 서버 오류")
            return True

    jobs = [(_user(), "boom" if index == 3 else "ok", "", "/") for index in range(20)]
    start = time.perf_counter()
    results = await send_all(Slow(), jobs)
    assert time.perf_counter() - start < 1.0  # 차례로 보내면 2초
    assert isinstance(results[3], RuntimeError)
    assert results[:3] == [True] * 3 and results[4:] == [True] * 16
