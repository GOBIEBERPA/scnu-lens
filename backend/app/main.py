from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.database import SessionLocal, create_tables
from app.services.alarms import AlarmDispatcher
from app.services.pipeline import BatchPipeline, backfill_deadline_dates, ensure_default_sources

settings = get_settings()


async def scheduled_pipeline() -> None:
    """입력 없음, 출력 없음; 예약 시각마다 독립 DB 세션으로 전체 배치를 실행한다."""
    with SessionLocal() as db:
        await BatchPipeline(db, settings).run()


async def scheduled_time_alarms() -> None:
    """입력 없음, 출력 없음; 1분마다 접수 시작·마감 시각 알림(1시간·몇 분 전·정시) 중 보낼 것을 보낸다."""
    with SessionLocal() as db:
        await AlarmDispatcher(db, settings).send_time_alarms()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """입력: FastAPI 앱, 출력: 수명주기 컨텍스트; DB·소스·스케줄러를 관리한다."""
    # 코드에 적힌 기본 비밀값은 누구나 알 수 있으므로 배포 환경에서는 켜지지 않게 막는다.
    if settings.app_env == "production" and settings.admin_api_key == "local-admin-key":
        raise RuntimeError("ADMIN_API_KEY를 기본값에서 바꾼 뒤 실행하세요.")
    create_tables()
    with SessionLocal() as db:
        ensure_default_sources(db)
        backfill_deadline_dates(db)
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    if settings.scheduler_enabled:
        scheduler.add_job(
            scheduled_pipeline,
            trigger="cron",
            hour=",".join(str(hour) for hour in settings.cron_hours),
            minute=0,
            id="notice-pipeline",
            max_instances=1,
            coalesce=True,
        )
        # 수집(매시간)과 따로, 분 단위 알림은 1분마다 확인해야 "5분 전"을 맞출 수 있다.
        scheduler.add_job(
            scheduled_time_alarms,
            trigger="interval",
            minutes=1,
            id="time-alarms",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    description="순천대학교 공지를 수집·분류하고 학과·관심사 기반 매칭 알림을 제공하는 API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.frontend_origin.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/")
def root() -> dict[str, str]:
    """입력 없음, 출력: 서비스 식별과 API 문서 경로."""
    return {"service": settings.app_name, "docs": "/docs", "health": f"{settings.api_prefix}/health"}

