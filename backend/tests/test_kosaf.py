"""한국장학재단 학자금지원정보 → 교외 장학금 공지 변환 테스트."""

from datetime import date

from app.crawlers.kosaf import homepage, is_current, newest_path, row_notice
from app.services.ai import extract_apply_start, extract_deadline, extract_window

TODAY = date(2026, 9, 29)
ROW = {
    "운영기관명": "광주남구장학회", "상품명": "행복나눔 장학생", "운영기관구분": "지자체(출자출연기관)",
    "상품구분": "장학금", "대학구분": "4년제(5~6년제포함)", "학년구분": "대학2학기대학3학기대학4학기대학신입생",
    "모집시작일": "2026-09-29", "모집종료일": "2026-10-17",
    "성적기준 상세내용": "○ 직전학기 평균 2.75 이상", "소득기준 상세내용": "해당없음",
    "지역거주여부 상세내용": "해당없음", "지원내역 상세내용": "○ 1인당 100만원",
    "제출서류 상세내용": "○ 신청서○ 주민등록표등본", "홈페이지 주소": "https://namgu.gwangju.kr",
}


def test_current_filter() -> None:
    """입력: 모집 중·지난·한 달 뒤 시작·전문대 전용 행, 출력: 모집 중(또는 곧)인 4년제 장학금만 남는다."""
    assert is_current(ROW, TODAY)
    assert not is_current({**ROW, "모집종료일": "2026-09-28"}, TODAY)
    assert not is_current({**ROW, "모집시작일": "2026-12-01", "모집종료일": "2026-12-20"}, TODAY)
    assert not is_current({**ROW, "대학구분": "전문대"}, TODAY)
    assert not is_current({**ROW, "상품구분": "학자금대출"}, TODAY)
    # 지역 연고(거주지 조건) 장학금은 공지 모음의 목적이 아니라서 가져오지 않는다.
    assert not is_current({**ROW, "지역거주여부 상세내용": "○ 보호자 주소지가 광주광역시 남구"}, TODAY)
    assert not is_current({**ROW, "학자금유형구분": "지역연고"}, TODAY)


def test_row_notice_shape() -> None:
    """입력: 전국 대상 장학 행, 출력: 제목·마감·접수 시작이 뽑히고 상세 칸 줄이 있다."""
    notice = row_notice(ROW)
    assert notice.title == "[광주남구장학회] 행복나눔 장학생"
    assert notice.url == "https://namgu.gwangju.kr"
    assert notice.published_at is None  # 모집 시작일을 게시일로 쓰면 오래된 공지로 보고 내린다
    assert extract_deadline(notice.raw_text, None) == "2026-10-17"
    assert extract_window(notice.raw_text)[0] == "2026-09-29"
    assert "지원내용: 1인당 100만원" in notice.raw_text
    assert "제출서류: 신청서 · 주민등록표등본" in notice.raw_text
    assert "소득" not in notice.raw_text.split("지원대상:")[1].split("\n")[0]
    assert extract_apply_start(notice.raw_text, None, "2026-10-17") == "2026-09-29"


def test_newest_path_by_date() -> None:
    """입력: 이름이 바뀐 옛 파일과 새 파일 요약, 출력: 날짜가 가장 최근인 경로."""
    spec = {"paths": {
        "/a": {"get": {"summary": "한국장학재단_학자금지원정보_20230220"}},
        "/b": {"get": {"summary": "한국장학재단_학자금지원정보(대학생)_20260910"}},
        "/c": {"get": {"summary": "한국장학재단_학자금지원정보(대학생)_20260811"}},
    }}
    assert newest_path(spec) == "/b"



def test_homepage_fixes_broken_addresses() -> None:
    """입력: 원본의 깨진 홈페이지 주소들, 출력: 열리는 주소(없으면 기관 이름 검색)."""
    assert homepage("http//www.jiheonsf.or.kr", "삼원장학재단") == "http://www.jiheonsf.or.kr"
    assert homepage("https://www.kosaf.go.kr/ko/scholar.dopg=scholarship05_04_01&naviParam=JH030108", "한국장학재단") ==         "https://www.kosaf.go.kr/ko/scholar.do?pg=scholarship05_04_01&naviParam=JH030108"
    assert homepage("www.dooeul.or.kr", "두을장학재단") == "https://www.dooeul.or.kr"
    assert homepage("해당없음", "동산장학회").startswith("https://search.naver.com/search.naver?query=")
    assert homepage("", "동산장학회").startswith("https://search.naver.com/")
    assert homepage("https://cafe.daum.net/deahamyung/", "대하장학회") == "https://cafe.daum.net/deahamyung/"


def test_school_scholarship_board_is_not_external(client) -> None:
    """입력: 학교 장학공지(parser_type=scholarship)와 교외 장학금(scholar_kosaf) 공지, 출력: 학교 탭·교외 탭에 각각 나온다."""
    from app.models import CrawlerSource
    from helpers import make_notice

    api, factory = client
    with factory() as db:
        school = CrawlerSource(key="sch", name="순천대 장학공지", url="u", parser_type="scholarship", category_hint="장학")
        kosaf = CrawlerSource(key="ks", name="교외 장학금", url="u", parser_type="scholar_kosaf", category_hint="장학")
        db.add_all([school, kosaf])
        db.flush()
        db.add(make_notice("교내 성적장학", source_id=school.id, category="장학"))
        db.add(make_notice("[삼원장학재단] 삼원장학생", source_id=kosaf.id, category="장학"))
        db.commit()
    titles = lambda origin: [n["title"] for n in api.get("/api/notices", params={"origin": origin}).json()["items"]]  # noqa: E731
    assert titles("school") == ["교내 성적장학"]
    assert titles("external") == ["[삼원장학재단] 삼원장학생"]
