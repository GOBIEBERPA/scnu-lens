import asyncio
import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.crawlers import CRAWLER_REGISTRY, default_sources
from app.models import Briefing, CrawlerSource, Notice, UserProfile
from app.schemas import CrawlRunResponse, NoticeStructured
from app.services.ai import LocalNoticeClassifier, days_until_deadline, match_reason, relevance_score
from app.services.alarms import AlarmDispatcher
from app.services.dedup import mark_duplicates
from app.services.inbox import record
from app.services.delivery import DIGEST_THRESHOLD, digest_message, in_quiet_hours, notice_link, utc_now, wants
from app.services.push import PushJob, WebPushSender, send_all

SOURCE_INTERVAL_SECONDS = 0.3


def _now() -> datetime:
    """입력 없음, 출력: DB 저장용 시간대 없는 UTC 현재 시각."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def apply_structured(notice: Notice, structured: NoticeStructured) -> None:
    """입력: 공지·구조화 결과, 출력 없음; 결과와 거기서 나온 분류·마감일 컬럼을 함께 맞춘다."""
    notice.structured_json = structured.model_dump()
    notice.category = structured.category
    notice.deadline_date = structured.deadline
    # 시각까지 알 때만 채운다. 날짜만 있으면 시각 알림 대상이 아니다.
    notice.open_at = structured.open_at if structured.open_at and "T" in structured.open_at else None
    notice.close_at = structured.close_at if structured.close_at and "T" in structured.close_at else None
    notice.open_date = structured.open_at[:10] if structured.open_at else None


def backfill_deadline_dates(db: Session) -> int:
    """입력: DB 세션, 출력: 채운 공지 수; 컬럼을 추가하기 전에 구조화된 공지의 마감일·접수 시각 컬럼을 채운다."""
    filled = 0
    pending = select(Notice).where(
        Notice.structured_json.is_not(None),
        or_(Notice.deadline_date.is_(None), Notice.open_at.is_(None), Notice.close_at.is_(None)),
    )
    for notice in db.scalars(pending):
        data = notice.structured_json or {}
        changed = False
        for column, key in (("deadline_date", "deadline"), ("open_at", "open_at"), ("close_at", "close_at")):
            value = data.get(key)
            if getattr(notice, column) is None and isinstance(value, str) and (column == "deadline_date" or "T" in value):
                setattr(notice, column, value)
                changed = True
        opens = data.get("open_at")
        if notice.open_date is None and isinstance(opens, str):
            notice.open_date = opens[:10]
            changed = True
        filled += changed
    db.commit()
    return filled


def push_body(reason: str, notice: Notice) -> str:
    """입력: 매칭 이유·공지, 출력: 이유 아래에 확인된 기간을 붙인 알림 본문(잠금화면에서 바로 판단하도록)."""
    brief = (notice.structured_json or {}).get("brief", [])
    period = next((f["value"] for f in brief if f.get("label") == "기간" and f.get("found")), None)
    return f"{reason}\n기간: {period}" if period else reason


def archive_stale_notices(db: Session, retention_days: int, today: date | None = None) -> int:
    """입력: DB 세션·보관 일수·기준일, 출력: 목록에서 내린 공지 수.

    지우지 않고 상태만 'archived'로 바꾼다. 목록·지표·매칭은 모두 'structured'만 보므로 화면에서 빠지고,
    알림 이력(briefings)은 그대로 남는다. 대상은 (1) 게시일이 보관 기간을 넘긴 공지,
    (2) 게시일이 없는 시험일정 중 접수 마감이 지난 것이다.
    """
    today = today or date.today()
    cutoff = datetime.combine(today - timedelta(days=retention_days), datetime.min.time())
    archived = 0
    for notice in db.scalars(select(Notice).where(Notice.processing_status == "structured")):
        if notice.published_at is not None:
            stale = notice.published_at < cutoff
        else:
            days_left = days_until_deadline(notice, today)
            stale = days_left is not None and days_left < 0
        if stale:
            notice.processing_status = "archived"
            archived += 1
    db.commit()
    return archived


def ensure_default_sources(db: Session) -> None:
    """입력: DB 세션, 출력 없음; 누락된 기본 공식 소스만 멱등적으로 추가한다."""
    existing = set(db.scalars(select(CrawlerSource.key)))
    for item in default_sources():
        if item["key"] not in existing:
            db.add(CrawlerSource(**item))
    db.commit()


class BatchPipeline:
    """수집→원문 저장→AI 구조화→개인화→웹 푸시·알림함의 전체 배치."""

    def __init__(self, db: Session, settings: Settings) -> None:
        """입력: DB 세션·설정, 출력 없음; 외부 서비스 어댑터를 준비한다."""
        self.db = db
        self.settings = settings
        self.ai = LocalNoticeClassifier(settings)
        self.push = WebPushSender(settings)
        # 현재 시각(UTC). 테스트에서 방해 금지·아침 9시 판단을 고정하려고 바꿔 끼운다.
        self.clock = utc_now

    async def run(self) -> CrawlRunResponse:
        """입력 없음, 출력: 단계별 건수와 오류; 소스 하나의 실패가 나머지를 막지 않는다."""
        result = CrawlRunResponse(
            fetched=0, inserted=0, structured=0, briefings_created=0, sent=0, reminders_sent=0, errors=[]
        )
        ensure_default_sources(self.db)
        sources = list(self.db.scalars(select(CrawlerSource).where(CrawlerSource.is_active.is_(True))))
        candidate_ids: list[int] = []
        for source in sources:
            try:
                crawler_class = CRAWLER_REGISTRY[source.parser_type]
                # 공모전 모음처럼 한 번에 수십 건이 열려 있는 소스는 크롤러가 더 큰 상한을 정한다.
                limit = getattr(crawler_class, "limit_override", None) or self.settings.max_notices_per_source
                crawler = crawler_class(source.url, limit)
                crawler.known_ids = set(
                    self.db.scalars(select(Notice.external_id).where(Notice.source_id == source.id))
                )
                crawled = await crawler.crawl()
                result.fetched += len(crawled)
                for item in crawled:
                    notice, inserted = self._store_raw(source, item)
                    candidate_ids.append(notice.id)
                    result.inserted += int(inserted)
                source.last_fetched = len(crawled)
                source.last_error = None
            except Exception as exc:
                result.errors.append(f"{source.name}: {exc}")
                source.last_error = str(exc)[:500] or exc.__class__.__name__
            source.last_crawled_at = _now()
            # 게시판이 70곳이 넘으므로 학교 서버에 몰아서 요청하지 않도록 간격을 둔다.
            await asyncio.sleep(SOURCE_INTERVAL_SECONDS)
        self.db.commit()

        raw_notices = list(
            self.db.scalars(
                select(Notice)
                .where(Notice.processing_status.in_(["raw", "error"]))
                .order_by(Notice.id.desc())
                .limit(max(30, len(candidate_ids)))
            )
        )
        structured_notices: list[Notice] = []
        for notice in raw_notices:
            try:
                apply_structured(notice, await self.ai.structure_notice(notice))
                notice.processing_status = "structured"
                structured_notices.append(notice)
                result.structured += 1
            except Exception as exc:
                notice.processing_status = "error"
                result.errors.append(f"구조화 {notice.id}: {exc}")
        self.db.commit()
        mark_duplicates(self.db)
        self._match_new_notices(structured_notices, result)

        await self._deliver_new_briefings(result)
        try:
            result.reminders_sent += await AlarmDispatcher(self.db, self.settings, self.push).send_day_alarms(self.clock())
        except Exception as exc:
            result.errors.append(f"마감 알림: {exc}")
        archive_stale_notices(self.db, self.settings.notice_retention_days)
        mark_duplicates(self.db)
        return result

    def _match_new_notices(self, structured_notices: list[Notice], result: CrawlRunResponse) -> None:
        """입력: 이번에 구조화된 공지·집계 결과, 출력 없음; 맞는 사용자마다 브리핑과 알림함 기록을 만든다."""
        # 다른 게시판에 먼저 올라온 같은 공지면 알림을 두 번 보내지 않는다.
        leaders = [notice for notice in structured_notices if notice.duplicate_of is None]
        if not leaders:
            return
        users = list(self.db.scalars(select(UserProfile)))
        # 이미 만든 (사용자, 공지) 쌍을 한 번에 읽는다. 쌍마다 조회하면 학생 1000명·새 공지 30건에 3만 번 조회한다.
        existing = set(
            self.db.execute(
                select(Briefing.user_id, Briefing.notice_id).where(Briefing.notice_id.in_([n.id for n in leaders]))
            ).tuples()
        )
        for notice in leaders:
            for user in users:
                # 사용자가 알림 카테고리를 골랐다면 그 밖의 공지는 알림을 만들지 않는다.
                if user.notify_categories and notice.category not in user.notify_categories:
                    continue
                if (user.id, notice.id) in existing or relevance_score(user, notice) < 1.5:
                    continue
                existing.add((user.id, notice.id))
                reason = match_reason(user, notice)
                self.db.add(Briefing(user_id=user.id, notice_id=notice.id, relevance_reason=reason))
                # 알림함에는 바로 남긴다. 푸시는 방해 금지·묶음 규칙에 따라 나중에 가도, 앱에서는 지금 볼 수 있다.
                record(self.db, user.id, "new", notice.title, push_body(reason, notice), notice)
                result.briefings_created += 1
        self.db.commit()

    async def _deliver_new_briefings(self, result: CrawlRunResponse) -> None:
        """입력: 집계 결과, 출력 없음; 새 매칭 알림을 사용자별로 모아 보낸다.

        - 웹 푸시를 구독하지 않은 사용자는 화면 목록에만 두고(web_only) 끝낸다.
        - 방해 금지 시간에는 보내지 않고 pending으로 남겨, 끝난 뒤 첫 배치에서 한꺼번에 묶어 보낸다.
        - 한 사용자에게 4건 이상이면 알림 하나로 묶는다(공모전 수십 건이 한 번에 들어와도 한 번만 울림).
        """
        pending = list(
            self.db.scalars(
                select(Briefing)
                .options(joinedload(Briefing.user), joinedload(Briefing.notice))
                .where(Briefing.delivery_status == "pending")
                .limit(2000)
            )
        )
        per_user: dict[int, list[Briefing]] = defaultdict(list)
        for briefing in pending:
            per_user[briefing.user_id].append(briefing)
        quiet = in_quiet_hours(self.clock(), self.settings.quiet_hours_start, self.settings.quiet_hours_end)
        groups: list[list[Briefing]] = []
        jobs: list[PushJob] = []
        owner: list[int] = []  # jobs[i]가 어느 사용자 묶음(groups 번호)의 푸시인지
        for items in per_user.values():
            user = items[0].user
            reachable = bool(user.push_subscription)
            # 푸시 구독이 없거나 새 공지 휴대폰 알림을 끈 사용자는 알림함에만 둔다(매칭 때 이미 기록됨).
            if not reachable or not wants(user, "new"):
                for briefing in items:
                    briefing.delivery_status = "web_only"
                continue
            if quiet and wants(user, "quiet"):
                continue
            groups.append(items)
            if len(items) > DIGEST_THRESHOLD:
                jobs.append((user, *digest_message(items), "/"))
                owner.append(len(groups) - 1)
            else:
                for briefing in items:
                    notice = briefing.notice
                    jobs.append((user, notice.title, push_body(briefing.relevance_reason, notice), notice_link(notice)))
                    owner.append(len(groups) - 1)
        # 사용자마다 차례로 보내지 않고 한꺼번에 동시에 보낸다.
        delivered = [False] * len(groups)
        errors: dict[int, BaseException] = {}
        for index, outcome in zip(owner, await send_all(self.push, jobs)):
            if isinstance(outcome, BaseException):
                errors.setdefault(index, outcome)
            elif outcome:
                delivered[index] = True
        for index, items in enumerate(groups):
            if index in errors:
                for briefing in items:
                    briefing.delivery_status = "failed"
                result.errors.append(f"알림 사용자 {items[0].user_id}: {errors[index]}")
            elif delivered[index]:
                for briefing in items:
                    briefing.delivery_status = "sent"
                    briefing.sent_at = _now()
                result.sent += len(items)
        self.db.commit()

    def _store_raw(self, source: CrawlerSource, item: object) -> tuple[Notice, bool]:
        """입력: 소스·CrawledNotice, 출력: 저장된 Notice와 신규 여부; 변경 시 재구조화한다."""
        from app.crawlers.base import CrawledNotice

        if not isinstance(item, CrawledNotice):
            raise TypeError("지원하지 않는 크롤러 결과입니다.")
        digest = hashlib.sha256(item.raw_text.encode("utf-8")).hexdigest()
        existing = self.db.scalar(
            select(Notice).where(Notice.source_id == source.id, Notice.external_id == item.external_id)
        )
        if existing:
            # 본문이 같아도 원문 주소는 바뀔 수 있으므로(주소 체계 변경 등) 항상 최신으로 맞춘다.
            existing.source_url = item.url
            if existing.content_hash != digest:
                existing.title = item.title
                existing.raw_text = item.raw_text
                existing.published_at = item.published_at
                existing.content_hash = digest
                existing.processing_status = "raw"
            return existing, False
        notice = Notice(
            source_id=source.id,
            external_id=item.external_id,
            source=source.name,
            source_url=item.url,
            title=item.title,
            raw_text=item.raw_text,
            category=source.category_hint if source.category_hint != "학과" else "기타",
            published_at=item.published_at,
            content_hash=digest,
            processing_status="raw",
        )
        self.db.add(notice)
        self.db.flush()
        return notice, True

