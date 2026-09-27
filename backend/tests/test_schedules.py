"""직접 입력한 시험 일정, 시험일·발표일 추출, 캘린더(.ics·화면 API) 테스트."""

import json
from datetime import date

import pytest

from app.crawlers import manual as manual_module
from app.crawlers.manual import ExamSession, ManualExamCrawler, session_notice
from app.services.ai import extract_schedule
from app.services.calendar import build_calendar
from helpers import make_notice

TODAY = date(2026, 9, 25)


def test_session_uses_extra_window_after_regular_closes() -> None:
    """입력: 정기 접수가 끝나고 추가 접수가 남은 회차, 출력: 추가 접수 마감이 마감일, 시작 시각도 적힌다."""
    session = ExamSession(
        key="adsp", title="ADsP 제50회", org="한국데이터산업진흥원", url="https://www.dataq.or.kr/",
        register=("2026-09-01 10:00", "2026-09-20 18:00"), extra_register=("2026-09-29 10:00", "2026-10-02 17:00"),
        exam_date="2026-10-17", result_date="2026-10-30",
    )
    notice = session_notice(session, TODAY)
    assert notice.title == "ADsP 제50회 원서접수"
    assert notice.raw_text.startswith("접수 마감: 2026-10-02 17:00까지\n접수 시작: 2026-09-29 10:00")
    assert notice.external_id == "adsp-ADsP 제50회-2026-10-02"


def test_closed_session_is_skipped() -> None:
    """입력: 정기·추가 접수가 모두 지난 회차, 출력: 공지를 만들지 않는다."""
    session = ExamSession(key="x", title="시험", org="기관", url="u", register=("2026-08-01", "2026-08-10"))
    assert session_notice(session, TODAY) is None


@pytest.mark.asyncio
async def test_manual_file_is_read_and_bad_entries_skipped(tmp_path, monkeypatch) -> None:
    """입력: 올바른 항목·필수값 빠진 항목이 섞인 파일, 출력: 올바른 항목만 공지가 된다."""
    far = date.today().replace(year=date.today().year + 1).isoformat()
    path = tmp_path / "manual_exams.json"
    path.write_text(json.dumps([
        {"key": "opic", "title": "OPIc 정기시험", "org": "ACTFL", "url": "https://example.com", "register": [far, far]},
        {"title": "키 없음"},
    ]), encoding="utf-8")
    monkeypatch.setattr(manual_module, "MANUAL_FILE", path)
    notices = await ManualExamCrawler("", 10).crawl()
    assert [n.title for n in notices] == ["OPIc 정기시험 원서접수"]


def test_extract_schedule_from_exam_lines() -> None:
    """입력: 큐넷 모양 본문, 출력: 시험일·발표일 일정만 날짜순으로 뽑힌다(마감 줄은 제외)."""
    text = "접수 마감: 2026-09-28까지\n필기 시험일: 2026-10-11 ~ 2026-10-12\n성적발표: 2026-10-20\n합격발표: 2026-11-01"
    items = [(i.date, i.label) for i in extract_schedule(text)]
    assert items == [("2026-10-11", "필기 시험"), ("2026-10-20", "성적발표"), ("2026-11-01", "합격발표")]


def test_ics_has_deadline_exam_and_result_events() -> None:
    """입력: 마감·시험·발표가 있는 시험 공지, 출력: .ics에 일정 세 개, 발표일에는 알림이 없다."""
    notice = make_notice(
        "국가기술자격 기사 제3회 실기 원서접수",
        structured_json={"deadline": "2026-09-28", "schedule": [{"date": "2026-10-11", "label": "실기 시험"}, {"date": "2026-10-20", "label": "합격발표"}]},
    )
    notice.id = 5
    ics = build_calendar([notice])
    assert ics.count("BEGIN:VEVENT") == 3 and ics.count("BEGIN:VALARM") == 2
    assert "SUMMARY:[합격발표] 국가기술자격 기사 제3회 실기\r\n" in ics


def test_calendar_events_api(client) -> None:
    """입력: 마감·시험일이 있는 공지와 기간 밖 공지, 출력: 기간 안 일정만 날짜·종류 순으로 온다."""
    api, factory = client
    with factory() as db:
        db.add(make_notice("기사 3회", category="자격증", structured_json={
            "deadline": "2026-09-28", "schedule": [{"date": "2026-10-11", "label": "시험"}]}))
        db.add(make_notice("지난달 공지", processing_status="archived", structured_json={"deadline": "2026-08-01"}))
        db.commit()
    events = api.get("/api/calendar/events", params={"start": "2026-09-01", "end": "2026-10-31"}).json()
    assert [(e["date"], e["kind"]) for e in events] == [("2026-09-28", "deadline"), ("2026-10-11", "exam")]
    assert api.get("/api/calendar/events", params={"start": "2026-01-01", "end": "2026-06-01"}).status_code == 422
