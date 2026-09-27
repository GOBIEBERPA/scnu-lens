from app.config import Settings
from app.models import Notice, UserProfile
from app.services.ai import LocalNoticeClassifier, match_reason, relevance_score


def test_structure_and_relevance() -> None:
    """입력: 장학 성격의 공지와 관심사가 겹치는 사용자, 출력: 분류·관련성·매칭 이유를 검증한다."""
    notice = Notice(
        external_id="1",
        source="테스트",
        source_url="https://example.com",
        title="AI 장학금 신청",
        raw_text="컴퓨터교육과 학생은 9월 30일까지 신청하세요.",
        category="기타",
        content_hash="x" * 64,
    )
    user = UserProfile(department="컴퓨터교육과", interests=["AI", "장학금"])

    structured = LocalNoticeClassifier(Settings())._structure_notice_sync(notice)
    notice.structured_json = structured.model_dump()
    notice.category = structured.category

    assert structured.category == "장학"
    assert structured.deadline is not None and structured.deadline.endswith("-09-30")
    assert relevance_score(user, notice) >= 7
    assert "AI" in match_reason(user, notice) or "장학금" in match_reason(user, notice)


def test_deadline_label_looks_forward_not_at_previous_line() -> None:
    """입력: 운영기간 다음 줄에 신청기간이 있는 공지, 출력: 운영기간 끝이 아니라 신청기간 끝이 마감이다."""
    from datetime import date

    from app.services.ai import extract_deadline

    text = "나. 운영기간: ’26. 10. 26.(화) ~ ’27. 1. 7.(목) 다. 신청기간: ’26. 9. 21.(월) ~ 10. 8.(목)"
    assert extract_deadline(text, date(2026, 9, 21)) == "2026-10-08"


def test_deadline_ignores_open_time_and_reads_survey_period() -> None:
    """입력: '신청 시작' 공지·설문 기간 공지, 출력: 시작일은 마감이 아니고, 설문 기간 끝은 마감이다."""
    from datetime import date

    from app.services.ai import extract_deadline

    assert extract_deadline("오픈클래스 신청 재오픈 안내 > 신청 시작: 9월 23일(수) 오후 3시~", date(2026, 9, 22)) is None
    assert extract_deadline("설문 기간 : 2026년 9월 21(월) ∼ 10월 8일 (목)", date(2026, 9, 21)) == "2026-10-08"


def test_result_notice_is_not_recommended_by_interest() -> None:
    """입력: 공모전 관심 학생과 '수상자 발표' 공지, 출력: 관심사로는 추천하지 않지만 내 학과 게시판 글이면 보인다."""
    notice = Notice(title="[학생상담센터] 2026학년도 학생상담센터 공모전 수상자 발표", raw_text="공모전 수상자를 발표합니다.",
                    source="컴퓨터공학전공 공지", category="경진대회", structured_json={})
    outsider = UserProfile(web_device_id="a", department="간호학과", interests=["공모전"], notify_categories=["경진대회"])
    insider = UserProfile(web_device_id="b", department="컴퓨터공학전공", interests=["공모전"], notify_categories=[])
    assert relevance_score(outsider, notice) == 0
    assert relevance_score(insider, notice) == 3.0
    assert "공모전" not in match_reason(insider, notice)


def test_interest_only_once_in_body_is_ignored() -> None:
    """입력: 자격요건에 'AI'가 한 번 나오는 채용공고, 출력: AI 관심 학생에게 추천하지 않는다. 제목에 있으면 추천한다."""
    user = UserProfile(web_device_id="c", department="미설정", interests=["AI"], notify_categories=[])
    job = Notice(title="체험형 청년인턴 채용 공고", raw_text="우대: 한글, 엑셀 등 OA와 생성형 AI 활용 능력",
                 source="장애학생지원센터 공지", category="취업", structured_json={})
    course = Notice(title="AI 부트캠프 참가자 모집", raw_text="교육 과정 안내", source="학사공지", category="행사", structured_json={})
    assert relevance_score(user, job) == 0
    assert relevance_score(user, course) >= 2.0


def test_apply_start_from_period() -> None:
    """입력: '신청기간 A ~ B' 공지들, 출력: A가 접수 시작일, '~까지'만 있거나 행사 일시 범위면 시작일 없음."""
    from datetime import date

    from app.services.ai import extract_apply_start, extract_deadline

    day = date(2026, 9, 20)
    for text, start in [
        ("신청기간 : 2026. 9. 22.(화) 10:00 ~ 2026. 9. 29.(화) 17:00까지", "2026-09-22"),
        ("접수: 2026-10-12 ~ 2026-10-16", "2026-10-12"),
        ("신청기간: 2026. 9. 21.(월) ~ 10. 8.(목)", "2026-09-21"),
        ("접수기간: 10월 5일까지", None),
        ("일시: 10.3 ~ 10.5, 신청: 9.30까지", None),
    ]:
        assert extract_apply_start(text, day, extract_deadline(text, day)) == start


def test_apply_start_with_exam_dates_after() -> None:
    """입력: 큐넷 모양 '필기 원서접수: A ~ B' 다음 줄에 시험일 범위, 출력: A가 접수 시작일."""
    from datetime import date

    from app.services.ai import extract_apply_start

    text = "필기 원서접수: 2026-09-30 ~ 2026-10-01\n필기 시험일: 2026-10-06 ~ 2026-10-08\n접수는 2026-10-01까지입니다."
    assert extract_apply_start(text, date(2026, 9, 20), "2026-10-01") == "2026-09-30"
