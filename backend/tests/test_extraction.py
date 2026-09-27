from datetime import date

import pytest

from app.config import Settings
from app.models import Notice, UserProfile
from app.services.ai import LocalNoticeClassifier, days_until_deadline, extract_deadline, match_reason

PUBLISHED = date(2026, 9, 17)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 실제 크롤링에서 "26-2"처럼 학기 표기를 마감일로 오인하던 사례.
        ("2026학년도 2학기 스터디 온 프로그램 참여팀 모집", None),
        ("[교직 복수전공] 25-2 컴퓨터교육과 복수 전공자 선발기준", None),
        ("신청기간: 2026.5.14까지", "2026-05-14"),
        ("재학생은 9월 30일까지 신청하세요.", "2026-09-30"),
        ("제출 기한은 2026년 10월 2일 입니다.", "2026-10-02"),
        ("2026-11-05 까지 접수합니다.", "2026-11-05"),
    ],
)
def test_extract_deadline(text: str, expected: str | None) -> None:
    """입력: 실제 공지에서 관찰된 문장들, 출력: ISO 마감일 또는 None임을 검증한다."""
    assert extract_deadline(text, PUBLISHED) == expected


def test_deadline_rolls_over_to_next_year() -> None:
    """입력: 연도 없는 연초 날짜와 연말 게시일, 출력: 다음 해로 넘긴 마감일을 검증한다."""
    assert extract_deadline("1월 10일까지 신청", date(2026, 12, 20)) == "2027-01-10"


def test_strong_keyword_beats_embedding() -> None:
    """입력: 제목이 학사처럼 보이는 국가장학금 공지, 출력: 장학으로 분류됨을 검증한다."""
    classifier = LocalNoticeClassifier(Settings())
    assert classifier._classify_category("2026년 2학기 국가장학금 1차 신청 안내", "기타") == "장학"


@pytest.mark.parametrize(
    ("title", "not_expected"),
    [
        # "연구실" 라벨이 모집 성격 공지를 싹쓸이하던 회귀 사례.
        ("2026학년도 2학기 스터디 온(Study On) 프로그램 참여팀 모집 안내", "연구실"),
        ("국립순천대학교 구글 워크스페이스 및 MS Office 365 아이디 가입 방법", "연구실"),
        ("공공와이파이(SCNU Free WiFi) 서비스 개시 안내", "안전"),
    ],
)
def test_does_not_overreach_to_lab_category(title: str, not_expected: str) -> None:
    """입력: 연구실과 무관한 공지 제목, 출력: 해당 카테고리로 분류되지 않음을 검증한다."""
    assert LocalNoticeClassifier(Settings())._classify_category(title, "기타") != not_expected


def test_program_terms_are_not_departments() -> None:
    """입력: 복수전공 제도 용어가 섞인 공지, 출력: 학과 목록에서 제외됨을 검증한다."""
    departments = LocalNoticeClassifier(Settings())._extract_departments(
        "[교직 복수전공] 컴퓨터교육과 복수 전공자 선발기준"
    )
    assert departments == ["컴퓨터교육과"]


@pytest.mark.parametrize(
    ("interests", "expected_particle"),
    [(["수강신청"], "’과"), (["AI", "장학금"], "’과"), (["인턴"], "’과"), (["학부연구생 제도"], "’와")],
)
def test_match_reason_uses_correct_particle(interests: list[str], expected_particle: str) -> None:
    """입력: 받침 유무가 다른 관심 키워드, 출력: 조사 '과/와'가 올바르게 붙는지 검증한다."""
    notice = Notice(
        external_id="1",
        source="테스트",
        source_url="https://example.com",
        title=" ".join(interests),
        raw_text="본문",
        category="기타",
        content_hash="x" * 64,
    )
    user = UserProfile(department="미설정", interests=interests)
    assert expected_particle in match_reason(user, notice)


def test_extracts_targets_and_days_left() -> None:
    """입력: 대상이 명시된 공지, 출력: 학과·대상 추출과 남은 일수 계산을 검증한다."""
    notice = Notice(
        external_id="1",
        source="테스트",
        source_url="https://example.com",
        title="컴퓨터교육과 학부연구생 모집",
        raw_text="컴퓨터교육과 3학년 재학생을 대상으로 2026.10.01까지 신청을 받습니다.",
        category="기타",
        content_hash="x" * 64,
        published_at=None,
    )
    structured = LocalNoticeClassifier(Settings())._structure_notice_sync(notice)
    assert "컴퓨터교육과" in structured.target_departments
    assert "재학생" in structured.target_students
    assert structured.category == "연구실"
    assert structured.deadline == "2026-10-01"

    notice.structured_json = structured.model_dump()
    assert days_until_deadline(notice, today=date(2026, 9, 28)) == 3
