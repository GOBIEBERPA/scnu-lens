"""브라우저 웹 푸시 발송.

별도 앱 설치 없이 브라우저에서 알림을 허용만 하면 되므로, 휴대폰 알림은 이 경로 하나로 보낸다.
푸시를 못 받는 사람은 앱 안 알림함에서 같은 알림을 본다.
"""

import asyncio
import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from pywebpush import WebPushException, webpush

from app.config import Settings
from app.models import UserProfile

# 구독이 만료·해지되었을 때 브라우저 푸시 서버가 돌려주는 상태 코드.
GONE_STATUS = (404, 410)

# 푸시 한 건은 대부분 푸시 서버 응답을 기다리는 시간이다. 한 건씩 보내면 학생 1000명에게 1분이 넘게 걸려
# "10분 전" 알림이 늦게 도착하므로 여러 건을 동시에 보낸다. 기본 스레드 풀(코어 수+4)과 따로 둔다.
PUSH_CONCURRENCY = 32
_PUSH_POOL = ThreadPoolExecutor(max_workers=PUSH_CONCURRENCY, thread_name_prefix="webpush")

# (사용자, 제목, 본문, 누르면 열 주소)
PushJob = tuple[UserProfile, str, str, str]


async def send_all(sender: object, jobs: Sequence[PushJob]) -> list[bool | BaseException]:
    """입력: send()가 있는 발송기·보낼 푸시 목록, 출력: 같은 순서의 결과(성공 여부, 실패 시 예외 객체).

    한 건이 실패해도 나머지는 그대로 보낸다. 동시에 보내는 수는 PUSH_CONCURRENCY로 묶는다.
    """
    gate = asyncio.Semaphore(PUSH_CONCURRENCY)

    async def one(job: PushJob) -> bool:
        async with gate:
            return await sender.send(*job)

    return await asyncio.gather(*(one(job) for job in jobs), return_exceptions=True)


class WebPushSender:
    """VAPID 키가 설정돼 있을 때만 실제로 푸시를 보낸다."""

    def __init__(self, settings: Settings) -> None:
        """입력: 앱 설정, 출력 없음; 키가 없으면 비활성 상태로 둔다."""
        self.settings = settings
        self.enabled = bool(settings.vapid_public_key and settings.vapid_private_key)

    async def send(self, user: UserProfile, title: str, body: str, url: str) -> bool:
        """입력: 사용자·알림 내용, 출력: 발송 성공 여부; 만료된 구독은 정리한다."""
        subscription = user.push_subscription
        if not self.enabled or not subscription:
            return False
        payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
        try:
            await asyncio.get_running_loop().run_in_executor(
                _PUSH_POOL,
                partial(
                    webpush,
                    subscription_info=subscription,
                    data=payload,
                    vapid_private_key=self.settings.vapid_private_key,
                    vapid_claims={"sub": self.settings.vapid_subject},
                ),
            )
            return True
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in GONE_STATUS:
                # 브라우저에서 알림을 끄거나 앱을 지운 경우라 더 보낼 곳이 없다.
                user.push_subscription = None
            return False
