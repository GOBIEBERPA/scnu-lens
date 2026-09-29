"""한국장학재단 학자금지원정보 → 교외 장학금 공지 변환 테스트."""

from datetime import date

from app.crawlers.kosaf import is_current, newest_path, row_notice
from app.services.ai import extract_apply_start, extract_deadline, extract_window

TODAY = date(2026, 9, 29)
ROW = {
    "운영기관명": "광주남구장학회", "상품명": "행복나눔 장학생", "운영기관구분": "지자체(출자출연기관)",
    "상품구분": "장학금", "대학구분": "4년제(5~6년제포함)", "학년구분": "대학2학기대학3학기대학4학기대학신입생",
    "모집시작일": "2026-09-29", "모집종료일": "2026-10-17",
    "성적기준 상세내용": "○ 직전학기 평균 2.75 이상", "소득기준 상세내용": "해당없음",
    "지역거주여부 상세내용": "○ 보호자 주소지가 광주광역시 남구", "지원내역 상세내용": "○ 1인당 100만원",
    "제출서류 상세내용": "○ 신청서○ 주민등록표등본", "홈페이지 주소": "https://namgu.gwangju.kr",
}


def test_current_filter() -> None:
    """입력: 모집 중·지난·한 달 뒤 시작·전문대 전용 행, 출력: 모집 중(또는 곧)인 4년제 장학금만 남는다."""
    assert is_current(ROW, TODAY)
    assert not is_current({**ROW, "모집종료일": "2026-09-28"}, TODAY)
    assert not is_current({**ROW, "모집시작일": "2026-12-01", "모집종료일": "2026-12-20"}, TODAY)
    assert not is_current({**ROW, "대학구분": "전문대"}, TODAY)
    assert not is_current({**ROW, "상품구분": "학자금대출"}, TODAY)


def test_row_notice_shape() -> None:
    """입력: 지역 연고 장학 행, 출력: 제목에 (지역 연고), 마감·접수 시작이 뽑히고 상세 칸 줄이 있다."""
    notice = row_notice(ROW)
    assert notice.title == "[광주남구장학회] 행복나눔 장학생 (지역 연고)"
    assert notice.url == "https://namgu.gwangju.kr"
    assert notice.published_at is None  # 모집 시작일을 게시일로 쓰면 오래된 공지로 보고 내린다
    assert extract_deadline(notice.raw_text, None) == "2026-10-17"
    assert extract_window(notice.raw_text)[0] == "2026-09-29"
    assert "지원내용: 1인당 100만원" in notice.raw_text
    assert "제출서류: 신청서 · 주민등록표등본" in notice.raw_text
    assert "소득" not in notice.raw_text.split("지원대상:")[1].split("\n")[0]
    assert row_notice({**ROW, "지역거주여부 상세내용": "해당없음"}).title == "[광주남구장학회] 행복나눔 장학생"
    assert extract_apply_start(notice.raw_text, None, "2026-10-17") == "2026-09-29"


def test_newest_path_by_date() -> None:
    """입력: 이름이 바뀐 옛 파일과 새 파일 요약, 출력: 날짜가 가장 최근인 경로."""
    spec = {"paths": {
        "/a": {"get": {"summary": "한국장학재단_학자금지원정보_20230220"}},
        "/b": {"get": {"summary": "한국장학재단_학자금지원정보(대학생)_20260910"}},
        "/c": {"get": {"summary": "한국장학재단_학자금지원정보(대학생)_20260811"}},
    }}
    assert newest_path(spec) == "/b"


def test_elsewhere_regional_not_recommended() -> None:
    """입력: 대구 연고·광주 연고·전국 장학금, 출력: 다른 지역 연고만 추천 점수 0."""
    from app.models import Notice, UserProfile
    from app.services.ai import relevance_score

    user = UserProfile(web_device_id="u", department="미설정", interests=["장학금"], notify_categories=[])

    def make(row: dict) -> Notice:
        crawled = row_notice(row)
        return Notice(title=crawled.title, raw_text=crawled.raw_text, source="교외 장학금", category="장학", structured_json={})

    daegu = make({**ROW, "운영기관명": "달서인재육성장학재단", "지역거주여부 상세내용": "○ 대구 달서구 거주"})
    gwangju = make(ROW)
    national = make({**ROW, "운영기관명": "삼원장학재단", "지역거주여부 상세내용": "해당없음"})
    assert relevance_score(user, daegu) == 0
    assert relevance_score(user, gwangju) > 0
    assert relevance_score(user, national) > 0
