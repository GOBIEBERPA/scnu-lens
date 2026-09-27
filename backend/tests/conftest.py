import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.database import get_db
from app.main import app
from helpers import memory_db


@pytest.fixture
def client():
    """입력 없음, 출력: 메모리 DB를 쓰는 API 클라이언트와 세션 팩토리(관리자 키 "k")."""
    factory = memory_db()

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[get_settings] = lambda: Settings(admin_api_key="k")
    yield TestClient(app), factory
    app.dependency_overrides.clear()
