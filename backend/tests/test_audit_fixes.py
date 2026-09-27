"""점검에서 실제 데이터로 확인된 문제들의 회귀 테스트."""

from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base
from app.models import Notice, UserProfile
from app.services.ai import LocalNoticeClassifier, extract_deadline, match_reason, relevance_score
from app.services.pipeline import archive_stale_notices, push_body

PUBLISHED = date(2026, 9, 17)


def _notice(title: str, raw_text: str = "본문", **extra) -> Notice:
    """입력: 제목·본문·추가 필드, 출력: 테스트용 공지 객체."""
    return Notice(
        external_id=extra.pop("external_id", "1"),
        source=extra.pop("source", "테스트"),
        source_url="https://example.com",
        title=title,
        raw_text=raw_text,
        category=extra.pop("category", "기타"),
        content_hash="x" * 64,
        **extra,
    )


def test_ascii_interest_needs_word_boundary() -> None:
    """입력: 'AI' 관심사와 Gmail 안내 공지, 출력: 단어 속 글자로는 매칭되지 않음을 검증한다."""
    user = UserProfile(department="미설정", interests=["AI"])
    gmail = _notice("학생 메일 Gmail 전환 안내", "main 계정으로 로그인하세요.")
    assert relevance_score(user, gmail) == 0
    assert relevance_score(user, _notice("AI 활용 특강 안내")) >= 2


def test_interest_synonyms_match() -> None:
    """입력: 'AI' 관심사와 '인공지능' 공지, 출력: 동의어로 매칭되고 이유에는 사용자가 쓴 말이 나온다."""
    user = UserProfile(department="미설정", interests=["AI"])
    notice = _notice("생성형 인공지능 교육 참가자 모집")
    assert relevance_score(user, notice) >= 2
    assert "AI" in match_reason(user, notice)


def test_event_date_is_not_deadline() -> None:
    """입력: 행사 일시만 있는 공지(실제 사례), 출력: 마감일로 잡지 않음을 검증한다."""
    text = "직무 특강 개최 안내\n- 일시: 2026년 10월 8일(목) 14:00 ~\n- 장소: 공학관"
    assert extract_deadline(text, PUBLISHED) is None
    assert extract_deadline("수상자 발표\n2026. 9. 29.(화) 15:00", PUBLISHED) is None


def test_apply_line_date_is_deadline() -> None:
    """입력: 일시와 신청기간이 함께 있는 공지, 출력: 신청기간 끝 날짜를 마감으로 고름을 검증한다."""
    text = "- 일시: 2026. 10. 20.\n- 신청: 2026. 9. 20. ~ 2026. 10. 2. 구글폼 접수"
    assert extract_deadline(text, PUBLISHED) == "2026-10-02"


def test_deadline_across_split_lines() -> None:
    """입력: HTML 태그마다 줄이 끊긴 실제 원문 모양, 출력: 라벨과 날짜를 이어 읽어 범위 끝을 고른다."""
    text = "원서 접수기간\n: 2026.9.14.(\n월\n) ~ 2026.9.29.(\n화)"
    assert extract_deadline(text, PUBLISHED) == "2026-09-29"
    text = "서류제출 및 가구원동의\n: 2026. 8. 12.(수\n시\n~ 9. 16.(수"
    assert extract_deadline(text, PUBLISHED) == "2026-09-16"


def test_title_decides_category_before_body() -> None:
    """입력: 본문에 학자금이 나오는 추가등록 공지, 출력: 장학이 아니라 학사로 분류됨을 검증한다."""
    classifier = LocalNoticeClassifier(Settings())
    text = "2026학년도 2학기 2차 추가등록 실시 안내 학자금 대출자와 장학생은 확인 바랍니다."
    assert classifier._classify_category(text, "기타", "2026학년도 2학기 2차 추가등록 실시 안내") == "학사"


def test_push_body_uses_found_period() -> None:
    """입력: 일부 칸만 확인된 구조화 결과, 출력: 확인된 기간만 알림 본문에 들어감을 검증한다."""
    structured = {
        "brief": [
            {"label": "기간", "value": "2026.9.1 ~ 9.30", "found": True},
            {"label": "문의", "value": "원문 페이지 자료 확인 필요", "found": False},
        ]
    }
    notice = _notice("모집", structured_json=structured)
    assert push_body("이유", notice) == "이유\n기간: 2026.9.1 ~ 9.30"


def test_archive_stale_notices() -> None:
    """입력: 오래된 공지·최근 공지·마감 지난 시험일정, 출력: 앞의 것과 시험일정만 목록에서 내려감을 검증한다."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        old = _notice("옛 공지", external_id="a", published_at=datetime(2026, 7, 1), processing_status="structured")
        fresh = _notice("새 공지", external_id="b", published_at=datetime(2026, 9, 20), processing_status="structured")
        exam = _notice(
            "기사 원서접수",
            external_id="c",
            processing_status="structured",
            structured_json={"deadline": "2026-09-01"},
        )
        db.add_all([old, fresh, exam])
        db.commit()
        assert archive_stale_notices(db, 30, today=date(2026, 9, 24)) == 2
        assert fresh.processing_status == "structured"
        assert old.processing_status == exam.processing_status == "archived"


def test_department_suffix_variants_match_board() -> None:
    """입력: '전자공학과' 사용자와 '전자공학전공 공지' 게시판 공지, 출력: 내 학과 게시판으로 매칭된다."""
    user = UserProfile(department="전자공학과", interests=[])
    notice = _notice("졸업작품 전시 안내", source="전자공학전공 공지")
    assert relevance_score(user, notice) >= 3
    assert "내 학과" in match_reason(user, notice)
    assert relevance_score(user, _notice("졸업작품 전시 안내", source="전기공학전공 공지")) == 0
