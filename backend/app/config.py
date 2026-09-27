from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수를 타입 안전한 애플리케이션 설정으로 변환한다."""

    app_env: str = "development"
    app_name: str = "SCNU Lens"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./scnu_lens.db"
    frontend_origin: str = "http://localhost:3000"
    data_go_kr_key: str = ""
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:scnu-lens@example.com"
    llm_enabled: bool = False
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:3b-instruct"
    llm_timeout_seconds: float = 90.0
    # 0이면 Ollama가 정한다. CPU 서버에서는 코어 하나를 API 응답용으로 남겨 두는 편이 좋다.
    llm_num_threads: int = Field(default=0, ge=0, le=64)
    admin_api_key: str = "local-admin-key"
    scheduler_enabled: bool = True
    crawl_cron_hours: str = "8,13,19"
    max_notices_per_source: int = Field(default=10, ge=1, le=50)
    # 게시판 목록에서 이 일수 안에 올라온 글만 상세까지 수집한다.
    crawl_recent_days: int = Field(default=7, ge=1, le=90)
    # 게시일이 이 일수를 넘긴 공지는 목록에서 내린다(삭제하지 않음).
    notice_retention_days: int = Field(default=30, ge=1, le=365)
    # 방해 금지 시간(한국 시간, 시작 시~끝 시). 이 사이에는 알림을 보내지 않고 모았다가 끝난 뒤 묶어서 보낸다.
    # 시작과 끝을 같게 두면 방해 금지를 쓰지 않는다.
    quiet_hours_start: int = Field(default=23, ge=0, le=23)
    quiet_hours_end: int = Field(default=8, ge=0, le=23)
    # 접수 시작·마감 몇 분 전에 알릴지(쉼표 구분, 0은 정시).
    alarm_open_minutes: str = "60,5,0"
    alarm_close_minutes: str = "60,10,0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cron_hours(self) -> list[int]:
        """입력: 쉼표 구분 시각 문자열('*'는 매시간), 출력: 0~23 범위의 정수 시각 목록."""
        if self.crawl_cron_hours.strip() == "*":
            return list(range(24))
        return sorted({int(hour.strip()) for hour in self.crawl_cron_hours.split(",") if hour.strip()})


@lru_cache
def get_settings() -> Settings:
    """입력 없음, 출력: 프로세스에서 재사용할 캐시된 Settings 인스턴스."""
    return Settings()

