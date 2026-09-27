import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import Settings, get_settings
from app.database import SessionLocal, get_db
from app.models import Briefing, CrawlerSource, EvalLabel, Notice, UserProfile
from app.schemas import (
    CrawlRunResponse,
    EvalItem,
    EvalLabelInput,
    InboxRead,
    MatchedNotice,
    NoticeListResponse,
    NoticeResponse,
    ProfileResponse,
    ProfileUpsert,
    PushSubscribe,
    SourceResponse,
    SourceToggle,
)
from app.services.ai import days_until_deadline, match_reason, relevance_score
from app.services.calendar import build_calendar, notice_dates
from app.services import inbox
from app.services.evaluation import evaluate
from app.services.pipeline import BatchPipeline
from app.services.push import WebPushSender
from app.services.query import find_user

# 이 점수 미만이면 "나에게 해당되는 공지"로 보지 않는다.
MATCH_THRESHOLD = 1.5
# "마감 임박"으로 보는 남은 일수(오늘 포함 D-3까지).
URGENT_DAYS = 3

router = APIRouter()


def require_admin(
    x_admin_key: str = Header(default=""),
    settings: Settings = Depends(get_settings),
) -> None:
    """입력: X-Admin-Key 헤더·설정, 출력 없음; 불일치 시 401 예외를 발생시킨다."""
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="관리자 키가 올바르지 않습니다.")


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, object]:
    """입력: DB 세션, 출력: API·DB 연결 상태와 저장된 공지 수."""
    total = db.scalar(select(func.count()).select_from(Notice)) or 0
    return {"status": "ok", "database": "connected", "notices": total, "time": datetime.now(timezone.utc).isoformat()}


def _visible() -> list:
    """입력 없음, 출력: 목록에 보일 공지 조건(구조화 완료·보관 안 됨·중복 대표만)."""
    return [Notice.processing_status == "structured", Notice.duplicate_of.is_(None)]


def _responses(db: Session, notices: list[Notice]) -> list[NoticeResponse]:
    """입력: DB 세션·대표 공지 목록, 출력: 같은 공지가 함께 올라온 다른 게시판 이름을 채운 응답 목록."""
    others: dict[int, set[str]] = defaultdict(set)
    ids = [notice.id for notice in notices]
    if ids:
        rows = db.execute(
            select(Notice.duplicate_of, Notice.source).where(
                Notice.duplicate_of.in_(ids), Notice.processing_status == "structured"
            )
        )
        for leader_id, source in rows:
            others[leader_id].add(source)
    return [
        NoticeResponse.model_validate(notice).model_copy(update={"also_in": sorted(others[notice.id] - {notice.source})})
        for notice in notices
    ]


def _matched_for(db: Session, user: UserProfile, include_closed: bool = False) -> list[tuple[Notice, float]]:
    """입력: DB 세션·사용자·마감 지난 공지 포함 여부, 출력: 기준 점수를 넘는 (공지, 점수). 점수순, 같으면 마감이 급한 순.

    추천에서는 마감이 지난 공지를 뺀다(추천 10건 중 절반이 이미 마감이던 문제). 캘린더처럼 지난 날짜도
    보여줘야 하는 곳은 include_closed=True로 부른다.
    """
    filters = _visible()
    if not include_closed:
        filters.append(or_(Notice.deadline_date.is_(None), Notice.deadline_date >= date.today().isoformat()))
    recent = db.scalars(
        select(Notice).where(*filters).order_by(Notice.published_at.desc(), Notice.id.desc()).limit(200)
    )
    scored = [(notice, relevance_score(user, notice)) for notice in recent]

    def urgency(pair: tuple[Notice, float]) -> tuple[float, int]:
        days = days_until_deadline(pair[0])
        return (-pair[1], days if days is not None else 10_000)

    return sorted((pair for pair in scored if pair[1] >= MATCH_THRESHOLD), key=urgency)


def _today_range() -> tuple[datetime, datetime]:
    """입력 없음, 출력: 오늘 0시와 내일 0시(게시일 비교용)."""
    start = datetime.combine(date.today(), datetime.min.time())
    return start, start + timedelta(days=1)


def _external_source_ids():
    """입력 없음, 출력: 학교 밖 소스(공모전 모음·시험 일정)의 ID를 고르는 하위 쿼리."""
    return select(CrawlerSource.id).where(
        or_(CrawlerSource.parser_type.like("exam_%"), CrawlerSource.parser_type.like("contest_%"))
    )


def _origin_filter(origin: str | None) -> list:
    """입력: school(학교 게시판)·external(공모전·시험 일정)·None, 출력: 해당 출처 조건."""
    if origin == "external":
        return [Notice.source_id.in_(_external_source_ids())]
    if origin == "school":
        return [or_(Notice.source_id.is_(None), Notice.source_id.not_in(_external_source_ids()))]
    return []


def _urgent_filter() -> list:
    """입력 없음, 출력: 오늘부터 3일 안에 마감되는 공지 조건. 상단 지표와 같은 기준이다."""
    today = date.today()
    return [Notice.deadline_date >= today.isoformat(), Notice.deadline_date <= (today + timedelta(days=URGENT_DAYS)).isoformat()]


def _status_filter(status: str | None) -> list:
    """입력: open(접수중)·upcoming(접수 예정)·None, 출력: 조건 목록.

    접수중 = 마감 전이고, 시작일을 모르거나 이미 시작했다. 접수 예정 = 시작일이 아직 안 왔다.
    """
    today = date.today().isoformat()
    if status == "open":
        return [Notice.deadline_date >= today, or_(Notice.open_date.is_(None), Notice.open_date <= today)]
    if status == "upcoming":
        return [Notice.open_date > today]
    return []


@router.get("/notices", response_model=NoticeListResponse)
def list_notices(
    category: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=50),
    sort: Literal["latest", "deadline", "opening", "roomy"] = "latest",
    due: Literal["today", "urgent"] | None = None,
    origin: Literal["school", "external"] | None = None,
    hide_closed: bool = False,
    status: Literal["open", "upcoming"] | None = None,
    db: Session = Depends(get_db),
) -> NoticeListResponse:
    """입력: 카테고리·검색·페이지·정렬·빠른 필터·출처·마감 지난 공지 숨김·접수 상태, 출력: 공지 한 페이지와 사용 가능한 카테고리.

    sort=deadline은 아직 마감 전인 공지만 마감이 가까운 순서로 보여준다.
    sort=opening은 아직 접수 전인 공지를 접수 시작이 빠른 순서로, roomy는 마감 전 공지를 마감이 먼 순서(여유 있는 순)로 보여준다.
    status=open은 지금 신청할 수 있는 공지(접수중), upcoming은 아직 접수 전인 공지만 보여준다.
    due=today는 오늘 올라온 공지, due=urgent는 3일 안에 마감되는 공지만 보여준다(상단 지표를 누를 때).
    origin=school은 학교 게시판, external은 공모전 모음·시험 일정만 보여준다.
    hide_closed=true면 마감일이 지난 공지를 뺀다(마감일이 없는 공지는 남긴다).
    """
    filters = _visible() + _origin_filter(origin)
    if hide_closed:
        filters.append(or_(Notice.deadline_date.is_(None), Notice.deadline_date >= date.today().isoformat()))
    if category and category != "전체":
        filters.append(Notice.category == category)
    if search:
        # 원문에는 첨부파일 텍스트도 붙어 있어 첨부 내용으로도 검색된다.
        filters.append(or_(Notice.title.ilike(f"%{search}%"), Notice.raw_text.ilike(f"%{search}%")))
    if due == "today":
        start, end = _today_range()
        filters += [Notice.published_at >= start, Notice.published_at < end]
    elif due == "urgent":
        filters += _urgent_filter()
    filters += _status_filter(status)
    if sort == "deadline":
        filters.append(Notice.deadline_date >= date.today().isoformat())
        order = (Notice.deadline_date.asc(), Notice.published_at.desc(), Notice.id.desc())
    elif sort == "opening":
        filters.append(Notice.open_date > date.today().isoformat())
        order = (Notice.open_date.asc(), Notice.deadline_date.asc(), Notice.id.desc())
    elif sort == "roomy":
        filters.append(Notice.deadline_date >= date.today().isoformat())
        order = (Notice.deadline_date.desc(), Notice.published_at.desc(), Notice.id.desc())
    else:
        order = (Notice.published_at.desc(), Notice.id.desc())
    total = db.scalar(select(func.count()).select_from(Notice).where(*filters)) or 0
    items = list(
        db.scalars(select(Notice).where(*filters).order_by(*order).offset((page - 1) * per_page).limit(per_page))
    )
    categories = list(db.scalars(select(Notice.category).where(*_visible()).distinct().order_by(Notice.category)))
    return NoticeListResponse(items=_responses(db, items), total=total, categories=categories)


@router.get("/notices/stats")
def notice_stats(db: Session = Depends(get_db)) -> dict[str, object]:
    """입력 없음, 출력: 전체 공지 기준 오늘 올라온 수·3일 안 마감 수·분야별 공지 수.

    화면 목록은 페이지 단위라, 요약 지표는 페이지가 아니라 전체에서 세야 한다.
    """
    start, end = _today_range()

    def by_category(*extra) -> dict[str, int]:
        rows = db.execute(select(Notice.category, func.count()).where(*_visible(), *extra).group_by(Notice.category))
        return dict(rows.all())

    return {
        "total": _count(db),
        "today": _count(db, Notice.published_at >= start, Notice.published_at < end),
        "urgent": _count(db, *_urgent_filter()),
        "categories": by_category(),
        # 출처 탭(학교 공지 / 공모전·자격증)마다 분야 칩 개수가 달라서 따로 센다.
        "categories_by_origin": {
            "school": by_category(*_origin_filter("school")),
            "external": by_category(*_origin_filter("external")),
        },
        # 탭마다 "마감임박" 칩 숫자가 달라서 출처별로도 센다.
        "urgent_by_origin": {
            "school": _count(db, *_urgent_filter(), *_origin_filter("school")),
            "external": _count(db, *_urgent_filter(), *_origin_filter("external")),
        },
        # "접수중"·"접수 예정" 칩 숫자.
        "status_by_origin": {
            origin: {status: _count(db, *_status_filter(status), *_origin_filter(origin)) for status in ("open", "upcoming")}
            for origin in ("school", "external")
        },
    }


def _count(db: Session, *extra) -> int:
    """입력: DB 세션·추가 조건, 출력: 목록에 보이는 공지 중 조건에 맞는 수."""
    return db.scalar(select(func.count()).select_from(Notice).where(*_visible(), *extra)) or 0


@router.get("/departments")
def departments(db: Session = Depends(get_db)) -> list[str]:
    """입력 없음, 출력: 수집 중인 학과·전공·학부 게시판 이름 목록(마이페이지 학과 자동완성용).

    학과 이름을 게시판 이름과 똑같이 고르게 하면 오타로 "내 학과 게시판" 매칭이 빠지는 일이 없다.
    """
    names = (re.sub(r"\s*공지$", "", name) for name in db.scalars(select(CrawlerSource.name)))
    return sorted({name for name in names if re.search(r"(학과|전공|학부|교육과)$", name)})


@router.get("/notices/for-me", response_model=list[MatchedNotice])
def notices_for_me(
    web_device_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=30),
    db: Session = Depends(get_db),
) -> list[MatchedNotice]:
    """입력: 사용자 식별자·최대 건수, 출력: 학과·관심사와 맞는 공지를 점수순으로 정렬한 목록."""
    user = find_user(db, web_device_id)
    if user is None:
        return []
    matched = _matched_for(db, user)[:limit]
    responses = _responses(db, [notice for notice, _ in matched])
    return [
        MatchedNotice(
            notice=response,
            relevance_reason=match_reason(user, notice),
            score=score,
            days_left=days_until_deadline(notice),
        )
        for (notice, score), response in zip(matched, responses)
    ]


@router.get("/notices/saved", response_model=list[NoticeResponse])
def saved_notices(web_device_id: str, db: Session = Depends(get_db)) -> list[NoticeResponse]:
    """입력: 기기 ID, 출력: 별표로 저장한 공지(최근 저장 순). 목록에서 내려간 공지도 보여준다."""
    user = find_user(db, web_device_id)
    ids = list(user.saved_notice_ids or []) if user else []
    if not ids:
        return []
    found = {notice.id: notice for notice in db.scalars(select(Notice).where(Notice.id.in_(ids)))}
    return _responses(db, [found[i] for i in ids if i in found])


@router.put("/notices/{notice_id}/save")
def save_notice(notice_id: int, web_device_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    """입력: 공지 ID·기기 ID, 출력: 저장 후 저장 목록; 매칭과 상관없이 마감 알림 대상이 된다."""
    if db.get(Notice, notice_id) is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    user = find_user(db, web_device_id)
    if user is None:
        user = UserProfile(web_device_id=web_device_id)
        db.add(user)
        db.flush()
    ids = [i for i in (user.saved_notice_ids or []) if i != notice_id]
    user.saved_notice_ids = [notice_id, *ids]  # 새 리스트를 넣어야 JSON 변경이 저장된다.
    existing = db.scalar(select(Briefing).where(Briefing.user_id == user.id, Briefing.notice_id == notice_id))
    if existing is None:
        db.add(Briefing(user_id=user.id, notice_id=notice_id, relevance_reason="별표로 저장한 공지예요.", delivery_status="saved"))
    db.commit()
    return {"saved": True, "ids": user.saved_notice_ids}


@router.delete("/notices/{notice_id}/save")
def unsave_notice(notice_id: int, web_device_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    """입력: 공지 ID·기기 ID, 출력: 저장 해제 후 저장 목록; 저장 때문에 생긴 알림 대상도 지운다."""
    user = find_user(db, web_device_id)
    if user is None:
        return {"saved": False, "ids": []}
    user.saved_notice_ids = [i for i in (user.saved_notice_ids or []) if i != notice_id]
    briefing = db.scalar(
        select(Briefing).where(
            Briefing.user_id == user.id, Briefing.notice_id == notice_id, Briefing.delivery_status == "saved"
        )
    )
    if briefing is not None:
        db.delete(briefing)
    db.commit()
    return {"saved": False, "ids": user.saved_notice_ids}


def _ics(body: str, filename: str | None = None) -> Response:
    """입력: .ics 본문·내려받기 파일 이름, 출력: 캘린더 앱이 여는 응답(파일 이름이 있으면 내려받기)."""
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if filename else {}
    return Response(body, media_type="text/calendar; charset=utf-8", headers=headers)


@router.get("/notices/{notice_id}/calendar.ics")
def notice_calendar(notice_id: int, db: Session = Depends(get_db)) -> Response:
    """입력: 공지 ID, 출력: 그 공지 마감일 하나를 담은 .ics 파일; 마감일이 없으면 404."""
    notice = db.get(Notice, notice_id)
    if notice is None or days_until_deadline(notice) is None:
        raise HTTPException(status_code=404, detail="마감일이 확인된 공지가 아닙니다.")
    return _ics(build_calendar([notice]), f"scnu-lens-{notice_id}.ics")


@router.get("/calendar/events")
def calendar_events(
    start: date,
    end: date,
    scope: Literal["all", "mine"] = "all",
    web_device_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    """입력: 기간(최대 62일)·범위(전체/내 공지)·기기 ID, 출력: 날짜별 마감·시험·발표 일정 목록.

    달력은 지난 날짜도 보여줘야 하므로 목록에서 내려간(archived) 공지도 포함한다.
    "내 공지"는 나에게 해당되는 공지와 별표로 저장한 공지다.
    """
    if end < start or (end - start).days > 62:
        raise HTTPException(status_code=422, detail="기간은 62일 이내로 요청해 주세요.")
    base = [Notice.processing_status.in_(["structured", "archived"]), Notice.duplicate_of.is_(None)]
    if scope == "mine":
        user = find_user(db, web_device_id)
        if user is None:
            return []
        ids = {notice.id for notice, _ in _matched_for(db, user, include_closed=True)} | set(user.saved_notice_ids or [])
        base.append(Notice.id.in_(ids))
    events = []
    for notice in db.scalars(select(Notice).where(*base)):
        dates = notice_dates(notice)
        for day, kind, label in dates:
            if start <= day <= end:
                events.append(
                    {"date": day.isoformat(), "kind": kind, "label": label, "notice_id": notice.id,
                     "title": notice.title, "category": notice.category}
                )
        # 신청기간(접수 시작~마감)이 이 기간과 겹치면 한 건으로 넣는다. 화면은 점을 찍지 않고 "이날 접수중" 목록에만 쓴다.
        opened = next((day for day, kind, _ in dates if kind == "open"), None)
        closes = next((day for day, kind, _ in dates if kind == "deadline"), None)
        # 목록에서 내린(archived) 공지는 지금 신청할 것으로 권하지 않는다.
        if opened and closes and opened <= end and closes >= start and notice.processing_status == "structured":
            events.append(
                {"date": opened.isoformat(), "end": closes.isoformat(), "kind": "period", "label": "접수중",
                 "notice_id": notice.id, "title": notice.title, "category": notice.category}
            )
    # 같은 날 안에서는 마감 → 접수 시작 → 시험 → 발표 순서로 보여준다.
    order = {"deadline": 0, "open": 1, "exam": 2, "result": 3, "period": 4}
    return sorted(events, key=lambda event: (event["date"], order[event["kind"]], event["title"]))


@router.get("/notices/{notice_id}", response_model=NoticeResponse)
def get_notice(notice_id: int, db: Session = Depends(get_db)) -> Notice:
    """입력: 공지 ID, 출력: 해당 공지; 없으면 404."""
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    return notice


@router.post("/profiles", response_model=ProfileResponse)
def upsert_profile(payload: ProfileUpsert, db: Session = Depends(get_db)) -> UserProfile:
    """입력: 웹 기기 ID와 관심사, 출력: 생성 또는 갱신된 간이 프로필."""
    if not payload.web_device_id:
        raise HTTPException(status_code=422, detail="web_device_id가 필요합니다.")
    profile = find_user(db, payload.web_device_id)
    if profile is None:
        profile = UserProfile()
        db.add(profile)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/profiles", response_model=ProfileResponse)
def get_profile(
    web_device_id: str | None = None,
    db: Session = Depends(get_db),
) -> UserProfile:
    """입력: 웹 기기 ID, 출력: 저장된 프로필; 없으면 404."""
    profile = find_user(db, web_device_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
    return profile


@router.get("/briefings")
def list_briefings(
    web_device_id: str,
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    """입력: 웹 기기 ID·최대 건수, 출력: 매칭된 공지와 매칭 이유 목록."""
    user = find_user(db, web_device_id)
    if user is None:
        return []
    rows = list(
        db.scalars(
            select(Briefing)
            .options(joinedload(Briefing.notice))
            .where(Briefing.user_id == user.id)
            .order_by(Briefing.created_at.desc())
            .limit(limit)
        )
    )
    return [
        {
            "id": row.id,
            "relevance_reason": row.relevance_reason,
            "created_at": row.created_at,
            "notice": NoticeResponse.model_validate(row.notice),
        }
        for row in rows
    ]


@router.get("/push/key")
def push_public_key(settings: Settings = Depends(get_settings)) -> dict[str, str | bool]:
    """입력 없음, 출력: 브라우저 구독에 필요한 VAPID 공개키와 사용 가능 여부."""
    return {"enabled": bool(settings.vapid_public_key), "public_key": settings.vapid_public_key}


@router.post("/push/subscribe")
def push_subscribe(payload: PushSubscribe, db: Session = Depends(get_db)) -> dict[str, bool]:
    """입력: 기기 ID와 브라우저 구독 정보, 출력: 저장 성공 여부; 프로필이 없으면 만든다."""
    user = find_user(db, payload.web_device_id)
    if user is None:
        user = UserProfile(web_device_id=payload.web_device_id)
        db.add(user)
    user.push_subscription = payload.subscription
    db.commit()
    return {"ok": True}


@router.get("/inbox")
def inbox_list(web_device_id: str, limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)) -> dict[str, object]:
    """입력: 기기 ID·최대 건수, 출력: 알림함 항목(새것 먼저)과 안 읽은 수."""
    user = find_user(db, web_device_id)
    if user is None:
        return {"items": [], "unread": 0}
    items = [
        {"id": i.id, "kind": i.kind, "title": i.title, "body": i.body, "url": i.url, "notice_id": i.notice_id,
         "created_at": i.created_at, "read": i.read_at is not None}
        for i in inbox.list_items(db, user, limit)
    ]
    return {"items": items, "unread": inbox.unread_count(db, user)}


@router.get("/inbox/unread-count")
def inbox_unread(web_device_id: str, db: Session = Depends(get_db)) -> dict[str, int]:
    """입력: 기기 ID, 출력: 안 읽은 알림 수(상단 종 아이콘 배지용, 가볍게 자주 부른다)."""
    user = find_user(db, web_device_id)
    return {"unread": inbox.unread_count(db, user) if user else 0}


@router.post("/inbox/read")
def inbox_read(payload: InboxRead, db: Session = Depends(get_db)) -> dict[str, int]:
    """입력: 기기 ID·읽음 처리할 ID 목록(없으면 전부), 출력: 읽음으로 바뀐 수와 남은 안 읽은 수."""
    user = find_user(db, payload.web_device_id)
    if user is None:
        return {"changed": 0, "unread": 0}
    changed = inbox.mark_read(db, user, payload.ids)
    return {"changed": changed, "unread": inbox.unread_count(db, user)}


@router.get("/inbox/upcoming")
def inbox_upcoming(web_device_id: str, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    """입력: 기기 ID, 출력: 앞으로 2주 안에 울릴 알림(마감 7·3·1일 전, 접수 시작·마감 시각)."""
    user = find_user(db, web_device_id)
    return inbox.upcoming(db, user) if user else []


@router.post("/push/test")
async def push_test(
    web_device_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, bool | str]:
    """입력: 기기 ID, 출력: 테스트 알림 발송 결과와 실패 이유; 서버→휴대폰 전체 경로를 확인한다."""
    sender = WebPushSender(settings)
    if not sender.enabled:
        return {"ok": False, "reason": "서버에 VAPID 키가 설정되지 않았어요."}
    user = find_user(db, web_device_id)
    if user is None or not user.push_subscription:
        return {"ok": False, "reason": "이 기기는 알림 구독이 안 돼 있어요. 알림을 먼저 켜 주세요."}
    sent = await sender.send(user, "🔔 SCNU Lens 테스트 알림", "알림이 정상적으로 도착했어요.", "/me")
    if sent:
        inbox.record(db, user.id, "test", "🔔 SCNU Lens 테스트 알림", "알림이 정상적으로 도착했어요.", url="/me")
    db.commit()  # 만료된 구독이면 send가 지워 두므로 반영한다.
    if sent:
        return {"ok": True, "reason": "보냈어요. 몇 초 안에 알림이 와야 해요."}
    if user.push_subscription is None:
        return {"ok": False, "reason": "구독이 만료됐어요. 알림을 껐다가 다시 켜 주세요."}
    return {"ok": False, "reason": "푸시 서버가 발송을 거절했어요. 잠시 후 다시 시도해 주세요."}


@router.delete("/push/subscribe")
def push_unsubscribe(web_device_id: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    """입력: 기기 ID, 출력: 해지 성공 여부; 저장된 구독 정보를 지운다."""
    user = find_user(db, web_device_id)
    if user is not None:
        user.push_subscription = None
        db.commit()
    return {"ok": True}


async def _run_pipeline_background(settings: Settings) -> None:
    """입력: 앱 설정, 출력 없음; 별도 세션으로 관리자 요청 배치를 실행한다."""
    with SessionLocal() as db:
        await BatchPipeline(db, settings).run()


@router.post("/admin/crawl", response_model=CrawlRunResponse, dependencies=[Depends(require_admin)])
async def run_crawl(db: Session = Depends(get_db)) -> CrawlRunResponse:
    """입력: 인증된 관리자 요청, 출력: 즉시 완료된 전체 배치 결과."""
    return await BatchPipeline(db, get_settings()).run()


@router.get("/admin/sources", response_model=list[SourceResponse], dependencies=[Depends(require_admin)])
def list_sources(db: Session = Depends(get_db)) -> list[CrawlerSource]:
    """입력: 인증된 관리자 요청, 출력: 크롤링 소스 설정 목록."""
    return list(db.scalars(select(CrawlerSource).order_by(CrawlerSource.id)))


@router.get("/admin/eval/items", response_model=list[EvalItem], dependencies=[Depends(require_admin)])
def eval_items(db: Session = Depends(get_db)) -> list[EvalItem]:
    """입력: 인증된 관리자 요청, 출력: 정답 입력용 최근 공지와 현재 예측·저장된 정답."""
    labels = {label.notice_id: label for label in db.scalars(select(EvalLabel))}
    notices = db.scalars(
        select(Notice).where(*_visible()).order_by(Notice.published_at.desc(), Notice.id.desc()).limit(200)
    )
    items = []
    for notice in notices:
        label = labels.get(notice.id)
        items.append(
            EvalItem(
                notice_id=notice.id,
                title=notice.title,
                source=notice.source,
                source_url=notice.source_url,
                predicted_category=notice.category,
                predicted_deadline=(notice.structured_json or {}).get("deadline"),
                gold_category=label.category if label else None,
                gold_deadline=label.deadline if label else None,
                labeled=label is not None,
            )
        )
    return items


@router.put("/admin/eval/{notice_id}", dependencies=[Depends(require_admin)])
def save_eval_label(notice_id: int, payload: EvalLabelInput, db: Session = Depends(get_db)) -> dict[str, bool]:
    """입력: 공지 ID·정답(분류·마감일), 출력: 저장 성공 여부."""
    if db.get(Notice, notice_id) is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없습니다.")
    label = db.get(EvalLabel, notice_id) or EvalLabel(notice_id=notice_id)
    label.category = payload.category
    label.deadline = payload.deadline
    db.add(label)
    db.commit()
    return {"ok": True}


@router.delete("/admin/eval/{notice_id}", dependencies=[Depends(require_admin)])
def delete_eval_label(notice_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    """입력: 공지 ID, 출력: 삭제 성공 여부; 잘못 입력한 정답을 지운다."""
    label = db.get(EvalLabel, notice_id)
    if label is not None:
        db.delete(label)
        db.commit()
    return {"ok": True}


@router.get("/admin/eval/report", dependencies=[Depends(require_admin)])
async def eval_report(db: Session = Depends(get_db)) -> dict[str, object]:
    """입력: 인증된 관리자 요청, 출력: 정답지 기준 현재 분류기의 정확도 보고서."""
    return await evaluate(db, get_settings())


@router.patch("/admin/sources/{source_id}", response_model=SourceResponse, dependencies=[Depends(require_admin)])
def toggle_source(source_id: int, payload: SourceToggle, db: Session = Depends(get_db)) -> CrawlerSource:
    """입력: 소스 ID·활성 여부, 출력: 갱신된 크롤링 소스."""
    source = db.get(CrawlerSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="소스를 찾을 수 없습니다.")
    source.is_active = payload.is_active
    db.commit()
    db.refresh(source)
    return source
