"""운영 규모(학생 수천 명, 한 학기 공지)를 흉내 낸 메모리 DB로 무거운 작업의 시간을 잰다.

    python -m scripts.benchmark                 # 기본: 학생 2000명, 공지 3000건, 푸시 1건 50ms
    python -m scripts.benchmark 5000 6000 0.1   # 학생 수, 공지 수, 푸시 1건 지연(초) 지정

실제 DB·푸시는 건드리지 않는다. 최적화 전후 비교용이다.
"""

import asyncio
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base
from app.models import Briefing, Notice, UserProfile
from app.schemas import CrawlRunResponse
from app.services.alarms import AlarmDispatcher
from app.services.dedup import mark_duplicates
from app.services.delivery import KST
from app.services.pipeline import BatchPipeline

WORDS = ["2026학년도", "2학기", "장학금", "신청", "안내", "모집", "공모전", "특강", "채용", "설명회", "수강", "정정", "학생", "참가자", "프로그램", "지원사업"]
INTERESTS = ["장학금", "공모전", "채용", "특강", "AI"]
# 매시간 배치에 새로 들어오는 공지 수
NEW_NOTICES = 30


class SlowPush:
    """보내는 데 실제 푸시 서버처럼 시간이 걸리는 가짜 푸시(스레드에서 기다린다)."""

    def __init__(self, latency: float) -> None:
        self.latency = latency
        self.count = 0

    async def send(self, *args, **kwargs) -> bool:
        await asyncio.to_thread(time.sleep, self.latency)
        self.count += 1
        return True


def build(users: int, notices: int):
    """입력: 학생 수·공지 수, 출력: 데이터를 채운 메모리 DB 세션 팩토리."""
    random.seed(7)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    today = date.today()
    with factory() as db:
        rows = []
        for index in range(notices + NEW_NOTICES):
            days = random.randint(-20, 40)
            deadline = (today + timedelta(days=days)).isoformat()
            timed = index % 10 == 0  # 열에 하나는 접수 시각이 있는 일정
            structured = {"deadline": deadline, "brief": []}
            if timed:
                structured |= {"open_at": f"{deadline}T10:00", "close_at": f"{deadline}T18:00"}
            title = " ".join(random.sample(WORDS, 5)) + f" {index}"
            rows.append(Notice(
                external_id=str(index), source="벤치 공지", source_url="https://www.scnu.ac.kr/", title=title, raw_text=title,
                category="학사", content_hash="x" * 64, processing_status="structured", structured_json=structured,
                deadline_date=deadline, open_at=structured.get("open_at"), close_at=structured.get("close_at"),
                published_at=datetime.now() - timedelta(days=random.randint(0, 29)),
            ))
        # 모두가 받아 둔 인기 자격증 일정 하나가 오늘 10시에 접수를 시작한다(시각 알림 최악의 경우).
        popular = Notice(
            external_id="popular", source="벤치 공지", source_url="https://www.scnu.ac.kr/", title="인기 자격증 원서접수",
            raw_text="원서접수", category="자격증", content_hash="y" * 64, processing_status="structured",
            structured_json={"deadline": today.isoformat(), "open_at": f"{today}T10:00"},
            deadline_date=today.isoformat(), open_at=f"{today}T10:00", published_at=datetime.now(),
        )
        db.add_all(rows + [popular])
        db.flush()
        people = [
            UserProfile(web_device_id=f"u{i}", department="미설정", interests=random.sample(INTERESTS, 2),
                        push_subscription={"endpoint": f"https://push.example/{i}"})
            for i in range(users)
        ]
        db.add_all(people)
        db.flush()
        old = rows[:notices]
        # 학생 한 명당 받은 공지 30건 + 인기 일정
        db.add_all(
            Briefing(user_id=person.id, notice_id=notice.id, relevance_reason="", delivery_status="sent")
            for person in people for notice in random.sample(old, 30) + [popular]
        )
        db.commit()
    return factory


def timed(label: str, func) -> None:
    """입력: 이름·실행할 함수, 출력 없음; 걸린 시간을 출력한다."""
    start = time.perf_counter()
    func()
    print(f"{label:18} {(time.perf_counter() - start) * 1000:8.0f} ms")


def pipeline_for(db, push) -> BatchPipeline:
    """입력: DB 세션·가짜 푸시, 출력: 분류 모델을 싣지 않은 배치 객체(매칭·발송 단계만 쓴다)."""
    pipeline = object.__new__(BatchPipeline)
    pipeline.db, pipeline.settings, pipeline.push = db, Settings(), push
    # 방해 금지 시간이 아닌 낮 시각으로 고정한다.
    pipeline.clock = lambda: datetime.now(KST).replace(hour=14).astimezone(timezone.utc)
    return pipeline


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    users = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    notices = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    latency = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
    start = time.perf_counter()
    factory = build(users, notices)
    print(f"준비: 학생 {users}명 · 공지 {notices}건 · 받은 공지 {users * 31}건 · 푸시 1건 {latency * 1000:.0f}ms ({time.perf_counter() - start:.1f}s)")
    now = datetime.now(KST).replace(hour=9, minute=55).astimezone(timezone.utc)
    for label, run in (
        ("1분 시각 알림", lambda d, p: d.send_time_alarms(now)),
        ("아침 날짜 알림", lambda d, p: d.send_day_alarms(now)),
    ):
        with factory() as db:
            push = SlowPush(latency)
            dispatcher = AlarmDispatcher(db, Settings(), push)
            timed(label, lambda: asyncio.run(run(dispatcher, push)))
            print(f"{'':18} 푸시 {push.count}건")
    with factory() as db:
        push = SlowPush(latency)
        pipeline = pipeline_for(db, push)
        new = list(db.query(Notice).filter(Notice.external_id.in_([str(i) for i in range(notices, notices + NEW_NOTICES)])))
        result = CrawlRunResponse(fetched=0, inserted=0, structured=0, briefings_created=0, sent=0, errors=[])
        timed("새 공지 매칭", lambda: pipeline._match_new_notices(new, result))
        timed("새 공지 발송", lambda: asyncio.run(pipeline._deliver_new_briefings(result)))
        print(f"{'':18} 매칭 {result.briefings_created}건 · 푸시 {push.count}건")
    with factory() as db:
        timed("중복 묶기", lambda: mark_duplicates(db))


if __name__ == "__main__":
    main()
