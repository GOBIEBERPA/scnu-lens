"""첨부파일 읽기·중복 묶기·캘린더·저장·정답지 평가 테스트."""

import io
import struct
import zipfile
from datetime import datetime

import pytest

from app.config import Settings
from app.crawlers.attachments import _hwp_paragraphs, attachment_links, body_only, extract_text
from app.models import UserProfile
from app.services.ai import relevance_score
from app.services.calendar import build_calendar
from app.services.dedup import mark_duplicates, normalize_title, same_notice
from helpers import make_notice as _notice, memory_db as _memory_db




# ---------- 첨부파일 ----------


def _zip(members: dict[str, str]) -> bytes:
    """입력: {경로: 내용}, 출력: 메모리에서 만든 zip 바이트."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_hwpx_paragraphs_become_lines() -> None:
    """입력: 문단 두 개짜리 HWPX, 출력: 문단마다 한 줄, 글자 조각은 이어 붙음을 검증한다."""
    xml = (
        '<hs:sec><hp:p id="1"><hp:run><hp:t>신청기간: 2026.</hp:t></hp:run><hp:run><hp:t>9.30.</hp:t></hp:run></hp:p>'
        "<hp:p><hp:run><hp:t>문의 &amp; 접수: 학생지원과</hp:t></hp:run></hp:p></hs:sec>"
    )
    data = _zip({"Contents/section0.xml": xml, "mimetype": "application/hwp+zip"})
    assert extract_text("안내.hwpx", data) == "신청기간: 2026.9.30.\n문의 & 접수: 학생지원과"


def test_docx_paragraphs_become_lines() -> None:
    """입력: 문단 두 개짜리 DOCX, 출력: 문단마다 한 줄을 검증한다."""
    xml = "<w:document><w:body><w:p><w:r><w:t>대상: 재학생</w:t></w:r></w:p><w:p><w:r><w:t xml:space=\"preserve\">마감 10월 2일</w:t></w:r></w:p></w:body></w:document>"
    assert extract_text("a.docx", _zip({"word/document.xml": xml})) == "대상: 재학생\n마감 10월 2일"


def test_hwp_record_parser_skips_controls() -> None:
    """입력: 컨트롤 문자가 섞인 HWP 문단 레코드, 출력: 글자만 남고 한자(서로게이트 포함)도 보존됨을 검증한다."""
    text = "마감 9월 30일 𠀀"
    chars = text.encode("utf-16-le")
    control = struct.pack("<H", 11) + b"\x00" * 14  # 표 같은 확장 컨트롤: 8칸 차지
    record = control + chars + struct.pack("<H", 13)  # 13 = 문단 끝
    header = struct.pack("<I", 67 | (len(record) << 20))
    assert _hwp_paragraphs(header + record) == [text]


def test_attachment_links_only_readable_files() -> None:
    """입력: 이미지·HWP·PDF 첨부가 있는 상세 페이지, 출력: 읽을 수 있는 형식만 절대 주소로 고름을 검증한다."""
    html = (
        '<a href="/common/nttFileDownload.do?fileKey=a">포스터.jpg</a>'
        '<a href="/common/nttFileDownload.do?fileKey=b">1. 계획안.hwp</a>'
        '<a href="/common/nttFileDownload.do?fileKey=c">안내.PDF</a>'
    )
    links = attachment_links(html, "https://www.scnu.ac.kr/elec/na/ntt/selectNttInfo.do?nttSn=1")
    assert links == [
        ("1. 계획안.hwp", "https://www.scnu.ac.kr/common/nttFileDownload.do?fileKey=b"),
        ("안내.PDF", "https://www.scnu.ac.kr/common/nttFileDownload.do?fileKey=c"),
    ]


def test_body_deadline_wins_over_attachment() -> None:
    """입력: 본문에 모집 마감, 첨부에 서류 제출기한이 있는 공지, 출력: 본문 마감을 쓴다(실제 기숙사 사례)."""
    from app.services.ai import LocalNoticeClassifier

    raw = "관생 모집 신청기간: 2026. 9. 29.까지\n\n[첨부파일: 안내.hwp]\n건강진단서 제출기간: 2026. 10. 8.까지"
    notice = _notice("글로컬기숙사 관생모집 안내", raw_text=raw)
    assert body_only(raw) == "관생 모집 신청기간: 2026. 9. 29.까지\n"
    assert LocalNoticeClassifier(Settings())._structure_notice_sync(notice).deadline == "2026-09-29"


# ---------- 중복 ----------


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("2026학년도 2학기 등록 휴학 신청 『일시적 제한』 안내",
         "2026학년도 2학기 등록 휴학 신청 『일시적 제한』 안내에 대한 상세정보 2026학년도 2학기", True),
        ("[학생상담센터] 공모전 수상자 발표", "공모전 수상자 발표", True),
        ("2026학년도 2학기 국가장학금 1차 신청 안내", "2026학년도 2학기 국가장학금 2차 신청 안내", False),
        ("SUMTECH 해커톤 2026, 참가 신청 안내", "도서관 이용자 만족도 조사 실시", False),
    ],
)
def test_same_notice(a: str, b: str, same: bool) -> None:
    """입력: 실제로 본 제목 쌍, 출력: 같은 공지 판정이 맞는지 검증한다(1차/2차는 다른 공지)."""
    assert same_notice(normalize_title(a), normalize_title(b)) is same




def test_mark_duplicates_prefers_central_board() -> None:
    """입력: 학과 게시판이 먼저, 학사공지가 나중에 수집된 같은 공지, 출력: 본부 게시판 글이 대표가 된다."""
    with _memory_db()() as db:
        dept = _notice("등록 휴학 신청 일시적 제한 안내", source="식품공학전공 공지")
        central = _notice("등록 휴학 신청 『일시적 제한』 안내", source="순천대 학사공지")
        db.add_all([dept, central])
        db.commit()
        assert mark_duplicates(db) == 1
        assert central.duplicate_of is None and dept.duplicate_of == central.id


# ---------- 캘린더 ----------


def test_calendar_has_all_day_event_and_folds_lines() -> None:
    """입력: 마감일 있는 공지와 없는 공지, 출력: 있는 것만 종일 일정으로, 긴 줄은 75바이트로 접힘을 검증한다."""
    with_deadline = _notice("국가장학금, 2차; 신청 " + "안내" * 30, structured_json={"deadline": "2026-10-02"})
    with_deadline.id = 7
    without = _notice("휴관 안내", structured_json={})
    ics = build_calendar([with_deadline, without])
    assert ics.count("BEGIN:VEVENT") == 1
    assert "DTSTART;VALUE=DATE:20261002" in ics and "DTEND;VALUE=DATE:20261003" in ics
    assert "국가장학금\\, 2차\\; 신청" in ics
    assert all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n"))


# ---------- API: 저장·캘린더·정답지 ----------




def test_save_notice_flow(client) -> None:
    """입력: 저장→조회→해제, 출력: 저장 목록·마감 알림 대상이 함께 바뀜을 검증한다."""
    api, factory = client
    with factory() as db:
        notice = _notice("NOVA 장학 신청", structured_json={"deadline": "2026-10-02", "brief": []})
        db.add(notice)
        db.commit()
        notice_id = notice.id
    assert api.put(f"/api/notices/{notice_id}/save", params={"web_device_id": "dev"}).json()["ids"] == [notice_id]
    assert [n["id"] for n in api.get("/api/notices/saved", params={"web_device_id": "dev"}).json()] == [notice_id]
    assert "raw_text" not in api.get("/api/notices").json()["items"][0]
    api.delete(f"/api/notices/{notice_id}/save", params={"web_device_id": "dev"})
    assert api.get("/api/notices/saved", params={"web_device_id": "dev"}).json() == []


def test_list_hides_duplicates_and_reports_other_boards(client) -> None:
    """입력: 대표 공지와 중복 공지, 출력: 목록엔 대표만, 다른 게시판 이름은 also_in으로 보임을 검증한다."""
    api, factory = client
    with factory() as db:
        leader = _notice("휴학 제한 안내", source="순천대 학사공지")
        db.add(leader)
        db.commit()
        db.add(_notice("휴학 제한 안내 ", source="식품공학전공 공지", duplicate_of=leader.id))
        db.commit()
    items = api.get("/api/notices").json()["items"]
    assert len(items) == 1 and items[0]["also_in"] == ["식품공학전공 공지"]


def test_eval_label_and_report(client) -> None:
    """입력: 정답 두 건(하나는 분류가 틀린 정답), 출력: 보고서 정확도와 틀린 사례를 검증한다."""
    api, factory = client
    with factory() as db:
        a = _notice("2026학년도 국가장학금 신청", raw_text="신청기간: 2026.10.02까지")
        b = _notice("휴관 안내", raw_text="도서관 휴관")
        db.add_all([a, b])
        db.commit()
        ids = (a.id, b.id)
    headers = {"X-Admin-Key": "k"}
    assert api.put(f"/api/admin/eval/{ids[0]}", json={"category": "장학", "deadline": "2026-10-02"}, headers=headers).status_code == 200
    assert api.put(f"/api/admin/eval/{ids[1]}", json={"category": "안전", "deadline": None}, headers=headers).status_code == 200
    assert api.put(f"/api/admin/eval/{ids[1]}", json={"category": "없는분류"}, headers=headers).status_code == 422
    report = api.get("/api/admin/eval/report", headers=headers).json()
    assert report["labeled"] == 2 and report["mode"] == "규칙"
    assert report["category_accuracy"] == 0.5
    assert report["deadline_accuracy"] == 1.0
    assert report["errors"][0]["field"] == "분류" and report["errors"][0]["gold"] == "안전"
    assert api.get("/api/admin/eval/report").status_code == 401


# ---------- 사용성: 정렬·빠른 필터·학과 목록·알림 링크 ----------


def test_deadline_sort_and_quick_filters(client) -> None:
    """입력: 마감 지남·D-2·D-10·마감 없음 공지, 출력: 임박순은 마감 전만 가까운 순, urgent는 D-3 이내만."""
    from datetime import date, timedelta

    from app.models import CrawlerSource

    api, factory = client
    today = date.today()
    with factory() as db:
        for title, days in (("지난 것", -1), ("이틀 뒤", 2), ("열흘 뒤", 10), ("마감 없음", None)):
            deadline = (today + timedelta(days=days)).isoformat() if days is not None else None
            db.add(_notice(title, deadline_date=deadline, published_at=datetime.combine(today, datetime.min.time())))
        db.add(CrawlerSource(key="k1", name="전자공학전공 공지", url="u", parser_type="scnu", category_hint="학과"))
        db.add(CrawlerSource(key="k2", name="학생생활관 공지", url="u", parser_type="scnu", category_hint="기타"))
        db.commit()
    titles = lambda **params: [n["title"] for n in api.get("/api/notices", params=params).json()["items"]]  # noqa: E731
    assert titles(sort="deadline") == ["이틀 뒤", "열흘 뒤"]
    assert titles(due="urgent") == ["이틀 뒤"]
    assert len(titles(due="today")) == 4
    stats = api.get("/api/notices/stats").json()
    assert stats["urgent"] == 1 and stats["today"] == 4 and stats["categories"] == {"기타": 4}
    assert api.get("/api/departments").json() == ["전자공학전공"]


def test_push_opens_notice_inside_app() -> None:
    """입력: 공지, 출력: 알림 링크가 학교 원문이 아니라 앱 안 상세 창 주소임을 검증한다."""
    from app.services.pipeline import notice_link

    notice = _notice("모집")
    notice.id = 42
    assert notice_link(notice) == "/?notice=42"


def test_origin_tabs_and_hide_closed(client) -> None:
    """입력: 학교 공지·공모전 소스 공지·마감 지난 학교 공지, 출력: 출처별로 나뉘고 hide_closed가 지난 것을 뺀다."""
    from datetime import date, timedelta

    from app.models import CrawlerSource

    api, factory = client
    with factory() as db:
        school = CrawlerSource(key="s", name="순천대 학사공지", url="u", parser_type="academic", category_hint="학사")
        exam = CrawlerSource(key="q", name="국가자격 시험일정(큐넷)", url="u", parser_type="exam_qnet", category_hint="자격증")
        db.add_all([school, exam])
        db.flush()
        future = (date.today() + timedelta(days=5)).isoformat()
        past = (date.today() - timedelta(days=2)).isoformat()
        db.add(_notice("학사 안내", source_id=school.id, category="학사", deadline_date=future))
        db.add(_notice("지난 학사 안내", source_id=school.id, category="학사", deadline_date=past))
        db.add(_notice("기사 실기 원서접수", source_id=exam.id, category="자격증", deadline_date=future, published_at=None))
        db.commit()
    titles = lambda **p: sorted(n["title"] for n in api.get("/api/notices", params=p).json()["items"])  # noqa: E731
    assert titles(origin="external") == ["기사 실기 원서접수"]
    assert titles(origin="school") == ["지난 학사 안내", "학사 안내"]
    assert titles(origin="school", hide_closed="true") == ["학사 안내"]
    stats = api.get("/api/notices/stats").json()
    assert stats["categories_by_origin"] == {"school": {"학사": 2}, "external": {"자격증": 1}}


def test_apply_status_filter_and_sorts(client) -> None:
    """입력: 접수중·접수 예정·마감 지난 공지, 출력: status 필터·접수 시작순·마감 여유순·칩 숫자가 맞다."""
    from datetime import date, timedelta

    api, factory = client
    day = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731
    with factory() as db:
        db.add(_notice("지금 접수중", category="학사", deadline_date=day(3), open_date=day(-2)))
        db.add(_notice("시작일 모름", category="학사", deadline_date=day(9)))
        db.add(_notice("다음 주 시작", category="학사", deadline_date=day(12), open_date=day(7)))
        db.add(_notice("모레 시작", category="학사", deadline_date=day(6), open_date=day(2)))
        db.add(_notice("이미 마감", category="학사", deadline_date=day(-1), open_date=day(-9)))
        db.commit()
    titles = lambda **p: [n["title"] for n in api.get("/api/notices", params=p).json()["items"]]  # noqa: E731
    assert sorted(titles(status="open")) == ["시작일 모름", "지금 접수중"]
    assert sorted(titles(status="upcoming")) == ["다음 주 시작", "모레 시작"]
    assert titles(sort="opening") == ["모레 시작", "다음 주 시작"]
    assert titles(sort="roomy") == ["다음 주 시작", "시작일 모름", "모레 시작", "지금 접수중"]
    stats = api.get("/api/notices/stats").json()["status_by_origin"]["school"]
    assert stats == {"open": 2, "upcoming": 2}
