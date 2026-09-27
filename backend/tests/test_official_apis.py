"""데이터 자격검정·K-Startup 공식 API 응답을 공지로 바꾸는 규칙의 테스트(실제 응답 모양 사용)."""

from datetime import date

from app.crawlers import CRAWLER_REGISTRY
from app.crawlers.dataq import DataqExamCrawler, latest_path, row_session
from app.crawlers.kstartup import KStartupCrawler, is_for_students, row_notice
from app.crawlers.manual import session_notice
from app.services.ai import extract_deadline

ADSP = {
    "순번": 945, "시험구분": "일반검정", "시험명": "데이터분석 준전문가(ADsP)", "시험시작시간": "10:00:00",
    "시험유형": "필기", "시험일": "2026-10-31", "시험장소": "제51회 데이터분석 준전문가(ADsP)",
    "접수마감일": "2026-10-02", "접수시작일": "2026-09-28", "합격자발표일": "2026-11-20", "회차": 51,
}

KSTARTUP = {
    "pbanc_sn": "179309", "biz_pbanc_nm": "2026 정주영 창업경진대회: 무한(INFINITE)",
    "pbanc_rcpt_bgng_dt": "20260918", "pbanc_rcpt_end_dt": "20261008", "supt_regin": "전국",
    "supt_biz_clsfc": "사업화", "aply_trgt": "대학생,일반인", "aply_trgt_ctnt": "예비창업자",
    "pbanc_ntrp_nm": "서울디지털재단", "biz_prch_dprt_nm": "창업지원팀", "prch_cnpl_no": "02-000-0000",
    "pbanc_ctnt": "창업 아이템 경진대회", "detl_pg_url": "https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179309",
}


def test_new_api_crawlers_are_registered_as_external() -> None:
    """입력 없음, 출력: 두 수집기가 등록되고 '공모전·자격증' 탭 조건(exam_·contest_)에 맞는지 검증한다."""
    assert CRAWLER_REGISTRY["exam_dataq"] is DataqExamCrawler
    assert CRAWLER_REGISTRY["contest_kstartup"] is KStartupCrawler


def test_latest_dataq_file_is_chosen() -> None:
    """입력: 파일이 두 개인 OAS 명세, 출력: 날짜가 최근인 파일 경로를 고른다."""
    spec = {"paths": {
        "/15062838/v1/uddi:old": {"get": {"summary": "데이터 자격검정 시험 정보_20240126"}},
        "/15062838/v1/uddi:new": {"get": {"summary": "데이터 자격검정 시험 정보_20260106"}},
    }}
    assert latest_path(spec) == "/15062838/v1/uddi:new"


def test_dataq_row_becomes_open_registration_notice() -> None:
    """입력: ADsP 회차 행, 출력: 접수 마감이 마감일로 잡힌 원서접수 공지; 접수가 끝나면 만들지 않는다."""
    notice = session_notice(row_session(ADSP), date(2026, 9, 26))
    assert notice is not None
    assert notice.title == "데이터분석 준전문가(ADsP) 제51회 필기 원서접수"
    assert "시험일: 2026-10-31" in notice.raw_text and "합격자 발표: 2026-11-20" in notice.raw_text
    assert extract_deadline(notice.raw_text, None) == "2026-10-02"
    assert session_notice(row_session(ADSP), date(2026, 10, 3)) is None


def test_kstartup_keeps_only_student_openings() -> None:
    """입력: 대학생 대상·기업 대상·마감 지난·다른 지역 공고, 출력: 첫 번째만 남는다."""
    today = "2026-09-26"
    assert is_for_students(KSTARTUP, today)
    assert not is_for_students({**KSTARTUP, "aply_trgt": "일반기업"}, today)
    assert not is_for_students({**KSTARTUP, "supt_biz_clsfc": "시설ㆍ공간ㆍ보육"}, today)
    assert not is_for_students({**KSTARTUP, "pbanc_rcpt_end_dt": "20260920"}, today)
    assert not is_for_students({**KSTARTUP, "supt_regin": "서울"}, today)
    # API가 '전국'으로 적어도 제목에 다른 지역이 있으면 그 지역 한정이다.
    assert not is_for_students({**KSTARTUP, "biz_pbanc_nm": "2026 제10회 G밸리창업경진대회 참가기업 모집"}, today)


def test_kstartup_local_elsewhere() -> None:
    """입력: 실제 공고명·주관, 출력: 다른 지역 한정만 빠지고, 기관만 서울인 전국 대회·전남 공고는 남는다."""
    from app.crawlers.kstartup import local_elsewhere

    assert local_elsewhere("[도봉구청년창업센터] 제6차 스케일업 아카데미", "도봉구 청년창업센터장")
    assert local_elsewhere("2026 마포 청년 창업 아이디어 경진대회(MAPO NEXT STAGE)")
    assert local_elsewhere("2026. 하반기 외식업 창업 교육생 모집공고", "도봉구청")
    assert not local_elsewhere("Midnight Korea Hackathon 2026 & Privacy Night 참가 안내", "서울핀테크랩")
    assert not local_elsewhere("2026 AI 대전환 아이디어 챌린지")
    assert not local_elsewhere("2026 전남 청년 창업 경진대회", "서울창업허브")


def test_kstartup_title_filter() -> None:
    """입력: 실제 공고명들, 출력: 경진대회·청년 교육은 남고 기업용 IR·입주·소상공인 공고는 빠진다."""
    from app.crawlers.kstartup import student_title

    assert student_title("2026 마포 청년 창업 아이디어 경진대회(MAPO NEXT STAGE)")
    assert student_title("2026 제10회 G밸리창업경진대회 참가기업 모집")
    assert student_title("수원대학교 예비창업패키지 2026 Pre-WoW! 창업아카데미")
    assert not student_title("2026-11회 호남권 엔젤투자 피칭룸 in 전남광주")
    assert not student_title("2026년 스마트상점 기술보급사업 참여 소상공인 모집공고(2차)")
    assert not student_title("청년창업 거주지원시설(창업하여家) 입주자 3차 모집(연장)")


def test_kstartup_category_comes_from_title() -> None:
    """입력: K-Startup 소스의 경진대회·교육 공고, 출력: 경진대회·행사로 분류된다(학교 공지 분류기를 쓰지 않음)."""
    from app.models import CrawlerSource, Notice
    from app.services.ai import source_locked_category

    source = CrawlerSource(key="kstartup", name="K", url="u", parser_type="contest_kstartup", category_hint="행사")
    contest = Notice(title="2026 정주영 창업경진대회", crawler_source=source)
    academy = Notice(title="2026년 민간 산림복지 창업 아카데미[2차] 참가자 모집", crawler_source=source)
    assert source_locked_category(contest) == "경진대회"
    assert source_locked_category(academy) == "행사"


def test_kstartup_row_notice() -> None:
    """입력: K-Startup 공고 행, 출력: 마감일·출처·상세 주소가 들어간 공지."""
    notice = row_notice(KSTARTUP)
    assert notice.external_id == "kstartup-179309"
    assert notice.url.endswith("pbancSn=179309")
    assert extract_deadline(notice.raw_text, None) == "2026-10-08"
    assert "출처: 창업진흥원 K-Startup" in notice.raw_text
    assert row_notice({**KSTARTUP, "pbanc_rcpt_end_dt": ""}) is None
