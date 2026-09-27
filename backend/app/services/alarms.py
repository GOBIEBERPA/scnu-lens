"""마감·접수 시각 알림.

- 날짜 알림: 마감 7일·3일·1일 전. 하루 단위라 한국 시간 아침 9시 이후 첫 배치에서 보내고, 여러 건이면 묶는다.
- 시각 알림: 접수 시작 1시간·5분 전·시작, 마감 1시간·10분 전·마감. 시작·마감 시각이 분 단위까지 알려진
  공지(토익·한국사 등)에만 걸고, 1분마다 도는 작업이 보낸다. 사용자가 받기로 한 공지의 정해진 시각이라
  방해 금지 시간과 상관없이 정시에 보낸다.

대상은 나에게 해당돼 알림을 받은 공지(sent)와 별표로 저장한 공지(saved)다. 같은 알림은 AlarmLog로 한 번만 보낸다.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.models import AlarmLog, Briefing, Notice
from app.services.ai import days_until_deadline
from app.services.delivery import DIGEST_THRESHOLD, KST, notice_link, reminder_digest_message, utc_now, wants
from app.services.inbox import record
from app.services.push import PushJob, WebPushSender, send_all

# 마감 며칠 전에 알릴지.
DAY_ALARMS = (7, 3, 1)
# 날짜 알림은 이 시각(한국 시간) 이후에 보낸다. 자정 배치에서 울리지 않게 하려는 것이다.
DAY_ALARM_HOUR = 9


@dataclass(frozen=True, slots=True)
class TimeAlarm:
    """접수 시작·마감 시각 기준 알림 하나."""

    field: str  # "open_at" 또는 "close_at"
    minutes_before: int
    label: str

    @property
    def key(self) -> str:
        """입력 없음, 출력: AlarmLog에 남길 이름(open-60, close-0 …)."""
        return f"{self.field.split('_')[0]}-{self.minutes_before}"


def _label(field: str, minutes: int) -> str:
    """입력: 시작/마감·몇 분 전, 출력: "접수 시작 1시간 전"·"마감 10분 전"·"지금 접수 시작" 같은 이름."""
    what = "접수 시작" if field == "open_at" else "마감"
    if minutes == 0:
        return "지금 접수 시작" if field == "open_at" else "지금 접수 마감"
    when = f"{minutes // 60}시간" if minutes % 60 == 0 else f"{minutes}분"
    return f"{what} {when} 전"


def build_time_alarms(open_minutes: str, close_minutes: str) -> tuple[TimeAlarm, ...]:
    """입력: "60,5,0" 같은 몇 분 전 목록(시작·마감), 출력: 시각 알림 목록. 설정으로 알림 시점을 바꿀 수 있게 한다."""
    alarms = []
    for field, spec in (("open_at", open_minutes), ("close_at", close_minutes)):
        for part in spec.split(","):
            if part.strip().isdigit():
                minutes = int(part)
                alarms.append(TimeAlarm(field, minutes, _label(field, minutes)))
    return tuple(alarms)


# 기본: 접수 시작 1시간·5분 전·시작, 마감 1시간·10분 전·마감.
TIME_ALARMS: tuple[TimeAlarm, ...] = build_time_alarms("60,5,0", "60,10,0")
# 서버가 잠깐 멈췄어도 이 시간 안이면 늦게라도 보낸다. 더 지나면 의미가 없어 보내지 않는다.
TIME_ALARM_GRACE = timedelta(minutes=10)


def parse_local_time(value: object) -> datetime | None:
    """입력: "YYYY-MM-DDTHH:MM"(한국 시간), 출력: 시간대가 붙은 시각. 날짜만 있으면 None(시각 알림 대상 아님)."""
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=KST)
    except ValueError:
        return None


def due_time_alarms(structured: dict, now: datetime, alarms: tuple[TimeAlarm, ...] = TIME_ALARMS) -> list[TimeAlarm]:
    """입력: 공지의 구조화 결과·현재 시각, 출력: 지금 보낼 시각 알림(보낼 시각이 지났고 유예 시간 안인 것).

    시작·마감마다 가장 최근 것 하나만 고른다. 서버가 잠깐 멈췄다 10:03에 돌면 "5분 전"과 "지금 시작"이
    둘 다 유예 안에 들지만, 이미 시작한 뒤에 "5분 전"을 보내면 틀린 알림이 되기 때문이다.
    """
    latest: dict[str, TimeAlarm] = {}
    for alarm in alarms:
        at = parse_local_time(structured.get(alarm.field))
        if at is None:
            continue
        target = at - timedelta(minutes=alarm.minutes_before)
        if target <= now < target + TIME_ALARM_GRACE:
            current = latest.get(alarm.field)
            if current is None or alarm.minutes_before < current.minutes_before:
                latest[alarm.field] = alarm
    return list(latest.values())


def alarm_schedule(
    structured: dict, today: date | None = None, alarms: tuple[TimeAlarm, ...] = TIME_ALARMS
) -> list[tuple[str, str]]:
    """입력: 구조화 결과·기준일, 출력: 앞으로 울릴 알림 (시각 설명, 이름) 목록. 화면에 "알림 예정"으로 보여준다."""
    today = today or date.today()
    plan: list[tuple[str, str]] = []
    deadline = structured.get("deadline")
    if isinstance(deadline, str):
        try:
            end = date.fromisoformat(deadline)
        except ValueError:
            end = None
        for days in DAY_ALARMS:
            if end and end - timedelta(days=days) >= today:
                plan.append(((end - timedelta(days=days)).isoformat() + f" {DAY_ALARM_HOUR:02d}:00", f"마감 {days}일 전"))
    for alarm in alarms:
        at = parse_local_time(structured.get(alarm.field))
        if at and (at - timedelta(minutes=alarm.minutes_before)).date() >= today:
            plan.append(((at - timedelta(minutes=alarm.minutes_before)).strftime("%Y-%m-%d %H:%M"), alarm.label))
    return sorted(plan)


class AlarmDispatcher:
    """날짜·시각 알림을 보내고 AlarmLog에 기록한다."""

    def __init__(self, db: Session, settings: Settings, push: WebPushSender | None = None) -> None:
        """입력: DB 세션·설정·(테스트용) 발송기, 출력 없음."""
        self.db = db
        self.settings = settings
        self.push = push or WebPushSender(settings)
        self.time_alarms = build_time_alarms(settings.alarm_open_minutes, settings.alarm_close_minutes)

    def _targets(self, *notice_filters) -> list[Briefing]:
        """입력: 공지 조건, 출력: 그 공지들의 알림 대상 브리핑과 사용자·공지.

        모든 알림 대상을 읽고 파이썬에서 거르면 학생이 많을 때 1분마다 수만 행을 읽는다. 그래서 알림을 보낼
        공지만 DB에서 먼저 고른다(마감일·접수 시각 컬럼 인덱스 사용).
        web_only(푸시 구독이 없어 앱에서만 보는 사용자)도 포함한다. 푸시는 못 가도 알림함에는 남아야 하기 때문이다.
        """
        return list(
            self.db.scalars(
                select(Briefing)
                .join(Briefing.notice)
                .options(joinedload(Briefing.user), joinedload(Briefing.notice))
                .where(Briefing.delivery_status.in_(["sent", "saved", "web_only"]), *notice_filters)
            )
        )

    def _logged(self, briefings: list[Briefing]) -> set[tuple[int, int, str]]:
        """입력: 브리핑 목록, 출력: 그 공지들에 대해 이미 보낸 (사용자 ID, 공지 ID, 알림 이름) 집합(한 번에 조회)."""
        notice_ids = {briefing.notice_id for briefing in briefings}
        if not notice_ids:
            return set()
        rows = self.db.execute(
            select(AlarmLog.user_id, AlarmLog.notice_id, AlarmLog.key).where(AlarmLog.notice_id.in_(notice_ids))
        )
        return {(user_id, notice_id, key) for user_id, notice_id, key in rows}

    def _log(self, briefing: Briefing, key: str) -> None:
        """입력: 브리핑·알림 이름, 출력 없음; 보낸 기록을 남긴다.

        저장점 안에서 넣어, 다른 작업이 같은 기록을 먼저 남겼더라도 이 기록만 버리고 나머지는 지킨다.
        """
        try:
            with self.db.begin_nested():
                self.db.add(AlarmLog(user_id=briefing.user_id, notice_id=briefing.notice_id, key=key))
        except IntegrityError:
            pass

    @staticmethod
    def _job(briefing: Briefing, title: str, body: str) -> PushJob:
        """입력: 브리핑·알림 내용, 출력: 보낼 푸시 한 건."""
        return (briefing.user, title, body, notice_link(briefing.notice))

    async def _send_all(self, jobs: list[PushJob]) -> None:
        """입력: 보낼 푸시 목록, 출력 없음; 동시에 보낸다.

        알림함에는 이미 남겼으므로, 발송 오류가 나도 다른 사용자 알림을 막지 않게 결과의 예외는 버린다.
        """
        await send_all(self.push, jobs)

    async def send_day_alarms(self, now: datetime | None = None) -> int:
        """입력: 현재 시각, 출력: 보낸 알림 수; 마감 7·3·1일 전 공지를 사용자별로 모아 보낸다."""
        now = now or utc_now()
        if now.astimezone(KST).hour < DAY_ALARM_HOUR:
            return 0
        today = now.astimezone(KST).date()
        target_dates = [(today + timedelta(days=days)).isoformat() for days in DAY_ALARMS]
        candidates = self._targets(Notice.deadline_date.in_(target_dates))
        logged = self._logged(candidates)
        per_user: dict[int, list[tuple[Briefing, int]]] = defaultdict(list)
        for briefing in candidates:
            days = days_until_deadline(briefing.notice, today)
            if days in DAY_ALARMS and (briefing.user_id, briefing.notice_id, f"d{days}") not in logged:
                per_user[briefing.user_id].append((briefing, days))
        sent = 0
        jobs: list[PushJob] = []
        for items in per_user.values():
            # 알림함에는 공지마다 남기고 보낸 것으로 기록한다. 푸시는 그다음에 가능하면 보낸다(실패해도 알림함엔 있음).
            for briefing, days in items:
                record(self.db, briefing.user_id, "deadline", f"⏰ 마감 D-{days} · {briefing.notice.title}",
                       briefing.relevance_reason, briefing.notice)
                self._log(briefing, f"d{days}")
            sent += len(items)
            if not wants(items[0][0].user, "deadline"):
                continue
            if len(items) > DIGEST_THRESHOLD:
                jobs.append(self._job(items[0][0], *reminder_digest_message(items)))
            else:
                jobs += [
                    self._job(briefing, f"⏰ 마감 D-{days} · {briefing.notice.title}", briefing.relevance_reason)
                    for briefing, days in items
                ]
        await self._send_all(jobs)
        self.db.commit()
        return sent

    async def send_time_alarms(self, now: datetime | None = None) -> int:
        """입력: 현재 시각, 출력: 보낸 알림 수; 접수 시작·마감 시각 알림 중 지금 보낼 것을 보낸다."""
        now = now or utc_now()
        # 지금부터 가장 긴 "몇 분 전"까지 안에 시작·마감하거나, 유예 시간 안에 막 지난 공지만 본다.
        local = now.astimezone(KST)
        longest = max((alarm.minutes_before for alarm in self.time_alarms), default=0)
        low = (local - TIME_ALARM_GRACE).strftime("%Y-%m-%dT%H:%M")
        high = (local + timedelta(minutes=longest + 1)).strftime("%Y-%m-%dT%H:%M")
        candidates = self._targets(or_(Notice.open_at.between(low, high), Notice.close_at.between(low, high)))
        logged = self._logged(candidates)
        sent = 0
        jobs: list[PushJob] = []
        for briefing in candidates:
            structured = briefing.notice.structured_json or {}
            for alarm in due_time_alarms(structured, now, self.time_alarms):
                if (briefing.user_id, briefing.notice_id, alarm.key) in logged:
                    continue
                at = parse_local_time(structured.get(alarm.field))
                title = f"🔔 {alarm.label} · {briefing.notice.title}"
                body = f"{at:%m월 %d일 %H:%M} {'접수 시작' if alarm.field == 'open_at' else '접수 마감'}"
                record(self.db, briefing.user_id, "time", title, body, briefing.notice)
                self._log(briefing, alarm.key)
                logged.add((briefing.user_id, briefing.notice_id, alarm.key))
                sent += 1
                if wants(briefing.user, "time"):
                    jobs.append(self._job(briefing, title, body))
        # 인기 일정은 수백 명이 같은 분에 받으므로 한꺼번에 보내야 마지막 사람도 제시간에 받는다.
        await self._send_all(jobs)
        self.db.commit()
        return sent
