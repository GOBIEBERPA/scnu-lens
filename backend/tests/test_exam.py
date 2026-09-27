import pytest

from app.config import Settings
from app.crawlers import CRAWLER_REGISTRY
from app.crawlers.exam import QnetExamCrawler
from app.services.ai import LocalNoticeClassifier, extract_deadline

# 실제 API 응답에서 가져온 형태. 필기(doc)는 비어 있고 실기(prac)만 있는 회차가 흔하다.
PRACTICAL_ONLY = {
    "implYy": "2026",
    "implSeq": 107,
    "qualgbCd": "T",
    "qualgbNm": "국가기술자격",
    "description": "국가기술자격 기능사 (2026년도 제107회)",
    "docRegStartDt": "",
    "docRegEndDt": "",
    "docExamStartDt": "",
    "docExamEndDt": "",
    "docPassDt": "",
    "pracRegStartDt": "20261127",
    "pracRegEndDt": "20261127",
    "pracExamStartDt": "20261207",
    "pracExamEndDt": "20261216",
    "pracPassDt": "20261222",
}

BOTH_PHASES = {
    **PRACTICAL_ONLY,
    "implSeq": 3,
    "description": "국가기술자격 기사 (2026년도 제3회)",
    "docRegStartDt": "20260907",
    "docRegEndDt": "20260910",
    "docExamStartDt": "20260920",
    "docExamEndDt": "20260920",
    "docPassDt": "20261008",
}


def test_exam_crawler_is_registered() -> None:
    """입력 없음, 출력: 시험일정 수집기가 파이프라인 레지스트리에 등록됐는지 검증한다."""
    assert CRAWLER_REGISTRY["exam_qnet"] is QnetExamCrawler


def test_practical_only_row_is_not_dropped() -> None:
    """입력: 필기가 비고 실기만 있는 실제 응답, 출력: 실기 공지 한 건이 만들어짐을 검증한다."""
    notices = QnetExamCrawler._to_notices(PRACTICAL_ONLY)
    assert len(notices) == 1
    notice, registration_end = notices[0]
    assert notice.title == "국가기술자격 기능사 제107회 실기 원서접수"
    assert "실기 시험일: 2026-12-07 ~ 2026-12-16" in notice.raw_text
    assert "합격발표: 2026-12-22" in notice.raw_text
    assert registration_end == "2026-11-27"
    assert extract_deadline(notice.raw_text, None) == "2026-11-27"


@pytest.mark.asyncio
async def test_crawl_keeps_only_open_registrations_without_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 접수 끝난 회차·중복 행이 섞인 응답, 출력: 신청 가능한 회차만 한 번씩 남음을 검증한다."""
    from datetime import date as real_date

    from app.crawlers import exam as exam_module

    class FixedDate(real_date):
        @classmethod
        def today(cls) -> "FixedDate":
            return cls(2026, 9, 23)

    closed = {**PRACTICAL_ONLY, "implSeq": 3, "pracRegStartDt": "20260727", "pracRegEndDt": "20260824"}

    async def fake_fetch(self: QnetExamCrawler, client: object, key: str, kind: str) -> list[dict]:
        return [PRACTICAL_ONLY, PRACTICAL_ONLY, closed]

    monkeypatch.setattr(exam_module, "date", FixedDate)
    monkeypatch.setattr(exam_module, "get_settings", lambda: Settings(data_go_kr_key="key"))
    monkeypatch.setattr(QnetExamCrawler, "_fetch", fake_fetch)
    notices = await QnetExamCrawler("https://www.q-net.or.kr", 10).crawl()
    assert [n.title for n in notices] == ["국가기술자격 기능사 제107회 실기 원서접수"]


def test_row_with_both_phases_makes_two_notices() -> None:
    """입력: 필기·실기가 모두 있는 회차, 출력: 서로 다른 ID의 공지 두 건을 검증한다."""
    notices = [notice for notice, _ in QnetExamCrawler._to_notices(BOTH_PHASES)]
    assert [n.title.split()[-2] for n in notices] == ["필기", "실기"]
    assert len({n.external_id for n in notices}) == 2
    assert extract_deadline(notices[0].raw_text, None) == "2026-09-10"


@pytest.mark.parametrize(
    ("description", "sche_type"),
    [
        ("국가기술자격 기사 (2026년도 제3회)", "03"),
        ("국가기술자격 산업기사 (2026년도 제3회)", "03"),
        ("국가기술자격 기능사 (2026년도 제107회)", "04"),
        ("국가기술자격 기술사 (2026년도 제140회)", "01"),
        ("국가기술자격 기능장 (2026년도 제80회)", "02"),
    ],
)
def test_notice_links_to_its_grade_schedule_page(description: str, sche_type: str) -> None:
    """입력: 등급별 회차 설명, 출력: 큐넷 메인이 아니라 그 등급의 시험일정 페이지로 연결됨을 검증한다."""
    notice, _ = QnetExamCrawler._to_notices({**PRACTICAL_ONLY, "description": description})[0]
    assert notice.url.endswith(f"scheType={sche_type}")
    assert "crf021.do" in notice.url


def test_row_without_any_registration_is_skipped() -> None:
    """입력: 접수일이 전혀 없는 응답, 출력: 공지를 만들지 않음을 검증한다."""
    assert QnetExamCrawler._to_notices({**PRACTICAL_ONLY, "pracRegEndDt": ""}) == []


def _exam_notice(title: str) -> "Notice":
    """입력: 시험 공지 제목, 출력: 자격증으로 분류된 공지 객체."""
    from app.models import Notice

    return Notice(
        external_id="x", source="큐넷", source_url="https://www.q-net.or.kr", title=title,
        raw_text="실기 원서접수: 2026-10-19", category="자격증", content_hash="x" * 64,
    )


@pytest.mark.parametrize(
    ("interest", "title", "should_match"),
    [
        ("정보처리기사", "국가기술자격 기사 제3회 실기 원서접수", True),
        ("정보처리산업기사", "국가기술자격 산업기사 제3회 실기 원서접수", True),
        # '산업기사' 관심이 '기사' 회차에 잘못 붙으면 안 된다.
        ("정보처리산업기사", "국가기술자격 기사 제3회 실기 원서접수", False),
        ("정보처리기사", "국가기술자격 산업기사 제3회 실기 원서접수", False),
        ("정보처리기사", "국가기술자격 기능사 제30회 필기 원서접수", False),
    ],
)
def test_specific_certificate_interest_matches_grade(interest: str, title: str, should_match: bool) -> None:
    """입력: 종목 이름 관심사·등급 단위 시험 공지, 출력: 같은 등급일 때만 매칭됨을 검증한다."""
    from app.models import UserProfile
    from app.services.ai import match_reason, relevance_score

    user = UserProfile(department="미설정", interests=[interest], notify_categories=[])
    notice = _exam_notice(title)
    assert (relevance_score(user, notice) >= 1.5) is should_match
    if should_match:
        assert interest in match_reason(user, notice)


def test_selected_category_alone_is_enough_to_match() -> None:
    """입력: 관심사 없이 '자격증' 분야만 고른 사용자, 출력: 시험 공지가 매칭되고 이유가 설명됨을 검증한다."""
    from app.models import UserProfile
    from app.services.ai import match_reason, relevance_score

    user = UserProfile(department="미설정", interests=[], notify_categories=["자격증"])
    notice = _exam_notice("국가기술자격 기능사 제30회 필기 원서접수")
    assert relevance_score(user, notice) >= 1.5
    assert "‘자격증’ 분야" in match_reason(user, notice)


def test_certificate_word_only_in_body_is_not_certificate() -> None:
    """입력: 본문에만 '자격증'이 나오는 학사 공지, 출력: 자격증으로 분류되지 않음을 검증한다."""
    title = "한국어교육실습 수강 기준 변경 안내 (복수전공)"
    body = "한국어교원 2급 자격증 취득을 위한 교육실습 수강 기준이 다음과 같이 변경됩니다."
    category = LocalNoticeClassifier(Settings())._classify_category(f"{title} {body}", "기타", title)
    assert category != "자격증"


def test_exam_notice_is_classified_as_certificate() -> None:
    """입력: 시험일정 공지 본문, 출력: '자격증' 카테고리로 분류됨을 검증한다."""
    notice, _ = QnetExamCrawler._to_notices(PRACTICAL_ONLY)[0]
    category = LocalNoticeClassifier(Settings())._classify_category(
        f"{notice.title} {notice.raw_text}", "기타", notice.title
    )
    assert category == "자격증"


@pytest.mark.asyncio
async def test_no_api_key_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """입력: 인증키 없음, 출력: 오류 없이 빈 목록을 반환함을 검증한다."""
    from app.crawlers import exam as exam_module

    monkeypatch.setattr(exam_module, "get_settings", lambda: Settings(data_go_kr_key=""))
    assert await QnetExamCrawler("https://example.com", 10).crawl() == []
