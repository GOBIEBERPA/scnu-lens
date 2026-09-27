"""관리자가 직접 적어 둔 시험·공모전 일정(app/crawlers/manual_exams.json)을 공지로 만든다.

공식 API가 없는 일정(예: 토익·OPIc·한국사)은 다른 사이트를 수집하지 않고, 시행기관 공지를 보고 이 파일에 적는다.
큐넷 일정과 같은 모양의 공지로 만들어 마감 D-day·매칭·알림·캘린더가 그대로 동작한다.

파일 예시:
[{"key": "opic", "title": "OPIc 10월 정기시험", "org": "ACTFL·멀티캠퍼스", "url": "https://www.opic.or.kr/",
  "register": ["2026-09-29 10:00", "2026-10-03 18:00"], "exam_date": "2026-11-01", "result_date": "2026-11-25"}]
날짜에 "HH:MM"을 붙이면 접수 시작·마감 1시간 전·몇 분 전 알림까지 걸린다.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.crawlers.base import BaseCrawler, CrawledNotice

MANUAL_FILE = Path(__file__).with_name("manual_exams.json")


@dataclass(slots=True)
class ExamSession:
    """시험 한 회차. 날짜는 "YYYY-MM-DD" 또는 시각까지 "YYYY-MM-DD HH:MM"."""

    key: str
    title: str
    org: str
    url: str
    register: tuple[str, str] | None = None
    extra_register: tuple[str, str] | None = None
    extra_label: str = "추가 접수"
    exam_date: str | None = None
    result_date: str | None = None
    result_label: str = "성적발표"


def session_notice(session: ExamSession, today: date | None = None) -> CrawledNotice | None:
    """입력: 시험 회차·기준일, 출력: 아직 접수할 수 있는 회차면 공지 한 건, 접수가 모두 끝났으면 None.

    정기 접수가 끝났어도 추가 접수가 남아 있으면 추가 접수 마감을 마감일로 쓴다.
    """
    today_iso = (today or date.today()).isoformat()
    windows = [window for window in (session.register, session.extra_register) if window]
    # 날짜 앞 10자리로 비교해야 "2026-09-28 10:00"도 날짜 기준으로 판단된다.
    current = next((window for window in windows if window[1][:10] >= today_iso), None)
    if current is None:
        return None
    opens, deadline = current
    lines = [
        # 마감일 추출 규칙이 "까지"를 먼저 보므로 마감 줄을 맨 앞에 둔다.
        f"접수 마감: {deadline}까지",
        f"접수 시작: {opens}",
        f"정기 접수: {session.register[0]} ~ {session.register[1]}" if session.register else None,
        f"{session.extra_label}: {session.extra_register[0]} ~ {session.extra_register[1]}" if session.extra_register else None,
        f"시험일: {session.exam_date}" if session.exam_date else None,
        f"{session.result_label}: {session.result_date}" if session.result_date else None,
        f"시행기관: {session.org}" if session.org else None,
        f"출처: {session.url}" if session.url else None,
    ]
    return CrawledNotice(
        # 시각을 빼고 날짜만 넣어야 같은 회차를 다시 읽어도 새 공지로 중복 저장되지 않는다.
        external_id=f"{session.key}-{session.title}-{deadline[:10]}",
        title=f"{session.title} 원서접수",
        url=session.url,
        raw_text="\n".join(line for line in lines if line),
        published_at=None,
    )


class ManualExamCrawler(BaseCrawler):
    """manual_exams.json에 적힌 회차 중 아직 접수 가능한 것을 공지로 돌려준다(네트워크를 쓰지 않는다)."""

    async def crawl(self) -> list[CrawledNotice]:
        """입력 없음, 출력: 접수 가능한 회차 공지; 파일이 없거나 형식이 틀리면 빈 목록."""
        try:
            entries = json.loads(MANUAL_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        notices = []
        for entry in entries if isinstance(entries, list) else []:
            try:
                session = ExamSession(
                    key=str(entry["key"]),
                    title=str(entry["title"]),
                    org=str(entry.get("org", "")),
                    url=str(entry.get("url", "")),
                    register=tuple(entry["register"]) if entry.get("register") else None,
                    extra_register=tuple(entry["extra_register"]) if entry.get("extra_register") else None,
                    exam_date=entry.get("exam_date"),
                    result_date=entry.get("result_date"),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if notice := session_notice(session):
                notices.append(notice)
        return notices[: self.limit]
