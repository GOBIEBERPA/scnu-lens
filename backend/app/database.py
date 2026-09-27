from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """모든 SQLAlchemy ORM 모델의 공통 베이스."""


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """입력 없음, 출력: 요청 범위 DB 세션; 종료 시 항상 연결을 반환한다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    """입력 없음, 출력 없음; 등록된 ORM 모델의 누락 테이블을 생성한다."""
    from app import models  # noqa: F401 - 모델 등록을 위한 지연 임포트

    Base.metadata.create_all(bind=engine)
    _add_missing_nullable_columns()
    _add_missing_indexes()


def _add_missing_indexes() -> None:
    """입력 없음, 출력 없음; 이미 있는 테이블에 모델에 새로 선언된 인덱스를 만든다.

    create_all은 새 테이블에만 인덱스를 만든다. 운영 중 인덱스를 늘려도 DB를 다시 만들지 않도록 여기서 맞춘다.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in existing:
                index.create(bind=engine)


def _add_missing_nullable_columns() -> None:
    """입력 없음, 출력 없음; 이미 있는 테이블에 모델에 새로 생긴 NULL 허용 컬럼을 추가한다.

    create_all은 기존 테이블을 고치지 않는다. 컬럼을 늘릴 때마다 DB를 지우지 않도록 여기서 맞춘다.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing or not column.nullable:
                    continue
                column_type = column.type.compile(dialect=engine.dialect)
                connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column_type}"))

