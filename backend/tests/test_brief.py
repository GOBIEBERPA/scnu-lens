from app.services.brief import UNKNOWN, build_brief

# 실제 순천대 학사공지 본문 형태. '신청기간: ~' 다음 줄로 날짜가 넘어가 있다.
INSTALLMENT = """2026학년도 2학기
재학생 등록금 분할납부 및 연계대출
을 붙임과 같이 안내하니 해당 학생들은 기한 내 신청해주시기 바랍니다.
1. 대상: 재학생으로서 등록금을 일시 납부하기 곤란한 자
2. 신청기간: ~
2026. 8. 3.(월) / 신청양식 작성 후 학과 및 전공 사무실 제출
3. 분할납부 기간
가. 1차: 2026. 8. 14.(금) ~ 8. 21.(금)
문의: 재무과 061-750-3052"""

EVENT = """AI 아이디어 캠프 참가자를 모집합니다.
□ 일시: 2026. 10. 15.(목) 14:00
□ 장소: 공학관 301호
□ 신청방법: 구글폼 링크로 신청
□ 참여혜택: 수료증 및 간식 제공"""


def _as_dict(items):
    return {item.label: item for item in items}


def test_value_wrapped_to_next_line_is_joined() -> None:
    """입력: 값이 다음 줄로 넘어간 실제 공지, 출력: 두 줄을 이어 붙인 기간을 검증한다."""
    brief = _as_dict(build_brief("등록금 분할납부 안내", INSTALLMENT, "순천대 학사공지", "2026-08-03", []))
    assert brief["기간"].value == "~ 2026. 8. 3.(월)"
    assert brief["대상"].value.startswith("재학생으로서")
    assert brief["문의"].found and "061-750-3052" in brief["문의"].value
    # 기간 줄에 '/'로 붙어 있던 뒷부분은 신청방법 칸으로 넘어간다.
    assert brief["신청방법"].value == "신청양식 작성 후 학과 및 전공 사무실 제출"
    assert brief["신청방법"].method == "carried"
    # '학사공지'처럼 붙은 이름에서 '공지'를 떼지 않는다.
    assert brief["주관"].value == "순천대 학사공지 (게시판 기준)"


def test_contact_split_across_lines_inside_parentheses() -> None:
    """입력: 괄호 안 전화번호가 다음 줄로 넘어간 문의, 출력: 괄호를 닫을 때까지 이어 붙임을 검증한다."""
    body = "문의: 등록금 분할납부(재무과\n061-750-3052), 연계대출(학생과)"
    brief = _as_dict(build_brief("안내", body, "", None, []))
    assert "061-750-3052" in brief["문의"].value


def test_unrelated_contact_sentence_is_not_application_method() -> None:
    """입력: 신청 경로 없이 '문의'를 안내하는 문장, 출력: 신청방법으로 잡지 않음을 검증한다."""
    body = "향림통시스템에서 확인이 어려우신분들은 학과 사무실로 문의해주시기 바랍니다."
    brief = _as_dict(build_brief("전과 결과 안내", body, "", None, []))
    assert brief["신청방법"].value == UNKNOWN


def test_missing_core_fields_say_unknown_and_never_invent() -> None:
    """입력: 신청방법·주관이 본문에 없는 공지, 출력: 칸은 남기되 '제공 여부 미확인'으로 표시됨을 검증한다."""
    brief = _as_dict(build_brief("안내", "학생 여러분께 알려드립니다.", "", None, []))
    for label in ("대상", "기간", "신청방법", "문의", "주관"):
        assert brief[label].value == UNKNOWN
        assert brief[label].found is False


def test_optional_fields_appear_only_when_present() -> None:
    """입력: 행사형 공지와 학사형 공지, 출력: 일시·장소는 있을 때만 칸이 생김을 검증한다."""
    event = _as_dict(build_brief("캠프 모집", EVENT, "컴퓨터교육과 공지", None, ["재학생"]))
    assert event["일시"].value.startswith("2026. 10. 15.")
    assert event["장소"].value == "공학관 301호"
    assert event["지원내용"].found
    assert event["신청방법"].value == "구글폼 링크로 신청"

    plain = _as_dict(build_brief("등록금 분할납부 안내", INSTALLMENT, "순천대 학사공지", None, []))
    assert "장소" not in plain and "일시" not in plain


def test_fallbacks_are_labelled_by_origin() -> None:
    """입력: 라벨 없는 공지, 출력: 게시판·대상 추출값으로 채우고 출처를 표시함을 검증한다."""
    brief = _as_dict(build_brief("실험실 안내", "실험실 사용 시간이 바뀝니다.", "화학교육과 공지", None, ["재학생"]))
    assert brief["주관"].value == "화학교육과 (게시판 기준)"
    assert brief["주관"].method == "board"
    assert brief["대상"].value == "재학생"
    assert brief["대상"].method == "targets"


def test_unrelated_date_range_is_not_taken_as_application_period() -> None:
    """입력: 신청기간 라벨 없이 분할납부 차수 날짜만 있는 본문, 출력: 그 범위를 신청기간으로 쓰지 않음을 검증한다."""
    body = "분할납부 기간\n가. 1차: 2026. 8. 14.(금) ~ 8. 21.(금)"
    brief = _as_dict(build_brief("분할납부 안내", body, "", None, []))
    assert brief["기간"].value == UNKNOWN


def test_only_deadline_known_is_marked_as_such() -> None:
    """입력: 날짜 범위 없이 마감일만 알려진 공지, 출력: 기간 칸에 '마감일만 확인'이라 밝힘을 검증한다."""
    brief = _as_dict(build_brief("신청 안내", "기한 내 신청 바랍니다.", "", "2026-10-01", []))
    assert brief["기간"].value == "~ 2026-10-01 (마감일만 확인)"


def test_llm_value_is_used_only_as_last_resort() -> None:
    """입력: 규칙으로 못 찾은 칸에 대한 LLM 값, 출력: 그 칸만 LLM 값으로 채워짐을 검증한다."""
    brief = _as_dict(
        build_brief("안내", "문의는 학생처로 해주세요.", "", None, [], llm_values={"문의": "학생처", "대상": "전체"})
    )
    assert brief["문의"].value == "학생처" and brief["문의"].method == "llm"
