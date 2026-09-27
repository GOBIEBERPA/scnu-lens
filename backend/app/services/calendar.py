"""공지 마감일을 iCalendar(.ics)로 만든다. 구글·애플·삼성 캘린더가 모두 읽는 표준 형식이다."""

from datetime import date, datetime, timedelta, timezone

from app.models import Notice

CALENDAR_NAME = "SCNU Lens 마감 일정"
# 하루 종일 일정의 알림 시각. 마감 전날 오전 9시(자정 기준 15시간 전)에 울린다.
ALARM_TRIGGER = "-PT15H"


def _escape(text: str) -> str:
    """입력: 일반 문자열, 출력: iCalendar TEXT 규칙(\\ ; , 줄바꿈)에 맞게 이스케이프한 문자열."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """입력: 한 줄, 출력: 75바이트마다 접은 줄. 한글은 3바이트라 글자 수가 아니라 바이트로 센다."""
    parts: list[str] = []
    current = ""
    for char in line:
        limit = 75 if not parts else 74  # 이어지는 줄은 맨 앞 공백 한 칸을 차지한다.
        if len((current + char).encode("utf-8")) > limit:
            parts.append(current)
            current = char
        else:
            current += char
    parts.append(current)
    return "\r\n ".join(parts)


def _deadline(notice: Notice) -> date | None:
    """입력: 공지, 출력: 구조화 결과의 마감일 또는 None."""
    raw = (notice.structured_json or {}).get("deadline")
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def _description(notice: Notice) -> str:
    """입력: 공지, 출력: 확인된 상세 칸과 원문 주소를 담은 일정 설명."""
    lines = [
        f"{field['label']}: {field['value']}"
        for field in (notice.structured_json or {}).get("brief", [])
        if field.get("found")
    ]
    lines.append(f"원문: {notice.source_url}")
    return "\n".join(lines)


def notice_dates(notice: Notice) -> list[tuple[date, str, str]]:
    """입력: 공지, 출력: (날짜, 종류, 라벨) 목록. 종류는 deadline(마감)·exam(시험)·result(발표).

    마감일과, 시험 일정 공지의 시험일·발표일을 한데 모은다. 캘린더 화면과 .ics가 같이 쓴다.
    """
    found: list[tuple[date, str, str]] = []
    deadline = _deadline(notice)
    if deadline:
        found.append((deadline, "deadline", "마감"))
    for item in (notice.structured_json or {}).get("schedule", []):
        try:
            day = date.fromisoformat(item["date"])
        except (KeyError, TypeError, ValueError):
            continue
        label = str(item.get("label", "일정"))
        found.append((day, "exam" if "시험" in label else "result", label))
    return found


def notice_event(notice: Notice, stamp: datetime | None = None) -> list[str]:
    """입력: 공지·생성 시각, 출력: 마감·시험일·발표일마다 VEVENT를 이루는 줄 목록; 날짜가 없으면 빈 목록."""
    stamp = stamp or datetime.now(timezone.utc)
    lines: list[str] = []
    for day, kind, label in notice_dates(notice):
        lines += [
            "BEGIN:VEVENT",
            # 종류·날짜를 넣어야 한 공지의 마감·시험·발표가 서로 덮어쓰지 않는다.
            f"UID:notice-{notice.id}-{kind}-{day.strftime('%Y%m%d')}@scnu-lens",
            f"DTSTAMP:{stamp.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
            # 시험일·발표일 일정에서 "원서접수"는 틀린 말이라 뗀다.
            f"SUMMARY:{_escape(f'[{label}] ' + (notice.title if kind == 'deadline' else notice.title.removesuffix(' 원서접수')))}",
            f"DESCRIPTION:{_escape(_description(notice))}",
            f"URL:{notice.source_url}",
        ]
        # 발표일은 놓쳐도 되지만 마감·시험일은 전날 알려준다.
        if kind != "result":
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(f'내일 {label}: {notice.title}')}",
                f"TRIGGER:{ALARM_TRIGGER}",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    return lines


def build_calendar(notices: list[Notice]) -> str:
    """입력: 공지 목록, 출력: 마감일 있는 공지만 담은 .ics 문서 문자열(CRLF 줄바꿈)."""
    stamp = datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SCNU Lens//Notice Deadlines//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CALENDAR_NAME}",
        "X-WR-TIMEZONE:Asia/Seoul",
        # 구독 캘린더가 몇 시간마다 새로 받아 가도록 권장 주기를 알린다.
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for notice in notices:
        lines.extend(notice_event(notice, stamp))
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
