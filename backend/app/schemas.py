from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ALERT_PREF_KEYS = ("new", "deadline", "time", "quiet")


class BriefField(BaseModel):
    """상세 화면에 보여줄 정해진 칸 하나. found=False면 값은 '제공 여부 미확인'이다."""

    label: str
    value: str
    found: bool
    method: str | None = None


class ScheduleItem(BaseModel):
    """마감일 외의 날짜 일정(시험일·발표일). 캘린더에 마감과 함께 표시한다."""

    date: str
    label: str


class NoticeStructured(BaseModel):
    """로컬 분류 모델·규칙이 반환하는 구조화 공지 형식."""

    title: str = Field(description="공지 제목")
    category: Literal["학사", "장학", "취업", "행사", "경진대회", "자격증", "연구실", "안전", "기타"]
    summary: str = Field(description="핵심 내용 2~3문장")
    deadline: str | None = Field(default=None, description="확인 가능한 ISO 날짜 또는 원문 날짜")
    target_departments: list[str] = Field(default_factory=list)
    target_students: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    action_required: str | None = None
    contact: str | None = None
    # 정해진 칸 순서대로 채운 상세 정보. 자유 요약문 대신 이것만 화면에 보여준다.
    brief: list[BriefField] = Field(default_factory=list)
    # LLM이 정해진 주제 목록(INTEREST_SYNONYMS의 키)에서만 고른 주제. 본문에 그 단어가 없어도
    # "머신러닝 교육" → "ai"처럼 관심사와 잇는 데 쓴다. LLM이 꺼져 있으면 비어 있다.
    topics: list[str] = Field(default_factory=list)
    # 시험일·성적발표일처럼 "라벨: 날짜" 줄로 적힌 일정.
    schedule: list[ScheduleItem] = Field(default_factory=list)
    # 접수 시작·마감 시각. 시각까지 알면 "YYYY-MM-DDTHH:MM", 날짜만 알면 "YYYY-MM-DD".
    # 시각이 있을 때만 1시간 전·5분(10분) 전·정시 알림을 건다.
    open_at: str | None = None
    close_at: str | None = None


class NoticeResponse(BaseModel):
    """화면·알림이 함께 쓰는 공지 응답 DTO."""

    id: int
    source: str
    source_url: str
    title: str
    # 원문(raw_text)은 첨부 텍스트까지 붙어 수만 자가 될 수 있고 화면에서도 쓰지 않아 응답에서 뺀다.
    structured_json: dict[str, Any] | None
    category: str
    published_at: datetime | None
    crawled_at: datetime
    # 같은 공지가 함께 올라온 다른 게시판 이름.
    also_in: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class NoticeListResponse(BaseModel):
    """공지 목록과 필터 UI용 집계 정보를 묶는다."""

    items: list[NoticeResponse]
    total: int
    categories: list[str]


class ProfileUpsert(BaseModel):
    """웹 기기 프로필 생성·수정 입력."""

    web_device_id: str | None = None
    display_name: str | None = None
    department: str = "미설정"
    interests: list[str] = Field(default_factory=list, max_length=20)
    notify_categories: list[str] = Field(default_factory=list, max_length=12)
    # 휴대폰 알림 종류별 켜기/끄기(new·deadline·time·quiet). 없으면 모두 켜짐.
    alert_prefs: dict[str, bool] | None = None

    @field_validator("alert_prefs")
    @classmethod
    def known_prefs(cls, value: dict[str, bool] | None) -> dict[str, bool] | None:
        """입력: 알림 설정, 출력: 알려진 키(new·deadline·time·quiet)만 남긴 설정."""
        if value is None:
            return None
        return {key: bool(on) for key, on in value.items() if key in ALERT_PREF_KEYS}

    @field_validator("interests")
    @classmethod
    def normalize_interests(cls, values: list[str]) -> list[str]:
        """입력: 관심사 문자열 목록, 출력: 공백 제거·중복 제거된 최대 20개 목록."""
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))[:20]


class ProfileResponse(ProfileUpsert):
    """저장된 프로필 응답."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CrawlRunResponse(BaseModel):
    """수동 또는 예약 배치 실행 결과."""

    fetched: int
    inserted: int
    structured: int
    briefings_created: int
    sent: int
    reminders_sent: int = 0
    errors: list[str]


class MatchedNotice(BaseModel):
    """사용자 프로필과 실시간으로 매칭한 공지와 그 근거."""

    notice: NoticeResponse
    relevance_reason: str
    score: float
    days_left: int | None = None


class SourceResponse(BaseModel):
    """관리자 화면의 크롤러 소스 응답."""

    id: int
    key: str
    name: str
    url: str
    parser_type: str
    category_hint: str
    is_active: bool
    last_crawled_at: datetime | None = None
    last_fetched: int | None = None
    last_error: str | None = None

    model_config = ConfigDict(from_attributes=True)


class PushSubscribe(BaseModel):
    """브라우저가 만든 웹 푸시 구독 정보를 서버에 등록하는 입력."""

    web_device_id: str
    subscription: dict[str, Any]


class EvalLabelInput(BaseModel):
    """관리자가 확인한 공지 한 건의 정답. deadline이 None이면 '마감일 없음'이 정답이다."""

    category: Literal["학사", "장학", "취업", "행사", "경진대회", "자격증", "연구실", "안전", "기타"]
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class EvalItem(BaseModel):
    """정답 입력 화면의 한 줄: 현재 예측과 저장된 정답."""

    notice_id: int
    title: str
    source: str
    source_url: str
    predicted_category: str
    predicted_deadline: str | None
    gold_category: str | None = None
    gold_deadline: str | None = None
    labeled: bool = False


class InboxRead(BaseModel):
    """알림함 읽음 처리 입력. ids가 없으면 전부 읽음."""

    web_device_id: str
    ids: list[int] | None = None


class SourceToggle(BaseModel):
    """크롤러 활성 여부 변경 입력."""

    is_active: bool

