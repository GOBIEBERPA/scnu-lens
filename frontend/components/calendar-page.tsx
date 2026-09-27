"use client";

import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { CategoryTag } from "@/components/category-tag";
import { fetchCalendarEvents } from "@/lib/api";
import { getDeviceId } from "@/lib/device";
import type { CalendarEvent } from "@/lib/types";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
// 한 칸에 점으로 보여줄 최대 일정 수. 넘치면 "+n"으로 줄인다.
const MAX_DOTS = 3;
// 전체/내 공지 선택은 기기별 편의 설정이라 브라우저 저장소에만 둔다.
const SCOPE_KEY = "scnu-calendar-scope";

// 입력: Date, 출력: 현지 기준 YYYY-MM-DD(UTC로 바꾸면 한국 시간 새벽에 날짜가 하루 밀린다).
function iso(day: Date): string {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}

// 입력: 그 달의 아무 날, 출력: 일요일부터 시작하는 6주(42칸) 날짜 목록.
function monthGrid(month: Date): Date[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = new Date(first);
  start.setDate(first.getDate() - first.getDay());
  return Array.from({ length: 42 }, (_, index) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + index));
}

// 입력: 마감일·오늘(YYYY-MM-DD), 출력: 배지 글자와 지났는지 여부.
// "마감"만 쓰면 이미 끝난 것으로 읽혀서 남은 날짜를 붙인다.
function deadlineBadge(date: string, today: string): { text: string; past: boolean } {
  const days = Math.round((Date.parse(date) - Date.parse(today)) / 86_400_000);
  if (days < 0) return { text: "마감됨", past: true };
  if (days === 0) return { text: "오늘 마감", past: false };
  return { text: `D-${days} 마감`, past: false };
}

// 입력 없음, 출력: 공지 마감·시험일·발표일을 달력으로 보여주고, 날짜를 누르면 그날 일정을 나열하는 화면.
export function CalendarPage() {
  const today = iso(new Date());
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [selected, setSelected] = useState(today);
  const [scope, setScope] = useState<"all" | "mine">("all");
  const [deviceId, setDeviceId] = useState("");
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    try {
      setDeviceId(getDeviceId());
    } catch {
      setDeviceId("");
    }
    try {
      if (localStorage.getItem(SCOPE_KEY) === "mine") setScope("mine");
    } catch {
      // 저장소를 못 쓰면 기본값(전체)으로 둔다.
    }
  }, []);

  const grid = useMemo(() => monthGrid(month), [month]);

  // 달·범위가 바뀌면 화면에 보이는 42칸 기간의 일정을 불러온다.
  useEffect(() => {
    if (scope === "mine" && !deviceId) return;
    setLoading(true);
    fetchCalendarEvents(iso(grid[0]), iso(grid[grid.length - 1]), scope, deviceId)
      .then((items) => {
        setEvents(items);
        setError("");
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "일정을 불러오지 못했어요."))
      .finally(() => setLoading(false));
  }, [grid, scope, deviceId]);

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>();
    for (const event of events) {
      if (event.kind !== "period") map.set(event.date, [...(map.get(event.date) || []), event]);
    }
    return map;
  }, [events]);

  function chooseScope(next: "all" | "mine") {
    setScope(next);
    try {
      localStorage.setItem(SCOPE_KEY, next);
    } catch {
      // 무시: 다음 방문 때 기본값.
    }
  }

  function moveMonth(delta: number) {
    setMonth((current) => new Date(current.getFullYear(), current.getMonth() + delta, 1));
  }

  function goToday() {
    setMonth(new Date(new Date().getFullYear(), new Date().getMonth(), 1));
    setSelected(today);
  }

  const selectedEvents = byDay.get(selected) || [];
  const monthCount = events.filter((event) => event.kind !== "period" && event.date.startsWith(iso(month).slice(0, 7))).length;
  // 고른 날에 신청 기간 안인 공지. 그날 시작·마감이라 위에 이미 나온 공지는 뺀다.
  const shownIds = new Set(selectedEvents.map((event) => event.notice_id));
  const ongoing = events
    .filter((event) => event.kind === "period" && event.date <= selected && selected <= (event.end ?? "") && !shownIds.has(event.notice_id))
    .sort((a, b) => (a.end ?? "").localeCompare(b.end ?? ""));
  const selectedDate = new Date(`${selected}T00:00:00`);

  return (
    <main className="calendar-page">
      <div className="admin-top">
        <Link href="/"><ArrowLeft size={18} /> 공지</Link>
      </div>

      <header className="calendar-head">
        <div>
          <p className="eyebrow">CALENDAR</p>
          <h1>{month.getFullYear()}년 {month.getMonth() + 1}월</h1>
          <p className="calendar-sub">{loading ? "불러오는 중…" : `이번 달 일정 ${monthCount}건`}</p>
        </div>
        <div className="calendar-nav">
          <button type="button" onClick={() => moveMonth(-1)} aria-label="이전 달"><ChevronLeft size={20} /></button>
          <button type="button" className="today" onClick={goToday}>오늘</button>
          <button type="button" onClick={() => moveMonth(1)} aria-label="다음 달"><ChevronRight size={20} /></button>
        </div>
      </header>

      <div className="calendar-toolbar">
        <div className="segmented" role="tablist" aria-label="일정 범위">
          <button type="button" role="tab" aria-selected={scope === "all"} className={scope === "all" ? "active" : ""} onClick={() => chooseScope("all")}>전체</button>
          <button type="button" role="tab" aria-selected={scope === "mine"} className={scope === "mine" ? "active" : ""} onClick={() => chooseScope("mine")}>내 공지·저장</button>
        </div>
        <p className="calendar-legend">
          <span><i className="dot open" />접수 시작</span>
          <span><i className="dot deadline" />마감일</span>
          <span><i className="dot exam" />시험</span>
          <span><i className="dot result" />발표</span>
        </p>
      </div>
      {error && <div className="admin-message">{error}</div>}

      <div className={`month-grid ${loading ? "is-loading" : ""}`} role="grid" aria-label="월간 일정">
        {WEEKDAYS.map((name, index) => (
          <div className={`weekday ${index === 0 ? "sun" : index === 6 ? "sat" : ""}`} key={name} role="columnheader">{name}</div>
        ))}
        {grid.map((day) => {
          const key = iso(day);
          const items = byDay.get(key) || [];
          const outside = day.getMonth() !== month.getMonth();
          const classes = [
            "day",
            outside ? "outside" : "",
            key === today ? "today" : "",
            key === selected ? "selected" : "",
            day.getDay() === 0 ? "sun" : day.getDay() === 6 ? "sat" : "",
          ].join(" ");
          return (
            <button
              type="button"
              role="gridcell"
              key={key}
              className={classes}
              onClick={() => {
                setSelected(key);
                if (outside) setMonth(new Date(day.getFullYear(), day.getMonth(), 1));
              }}
              aria-label={`${day.getMonth() + 1}월 ${day.getDate()}일 일정 ${items.length}건`}
              aria-selected={key === selected}
            >
              <span className="day-number">{day.getDate()}</span>
              <span className="day-dots">
                {items.slice(0, MAX_DOTS).map((event, index) => <i className={`dot ${event.kind}`} key={index} />)}
                {items.length > MAX_DOTS && <em>+{items.length - MAX_DOTS}</em>}
              </span>
            </button>
          );
        })}
      </div>

      <section className="day-agenda" aria-live="polite">
        <h2>
          {selectedDate.getMonth() + 1}월 {selectedDate.getDate()}일 ({WEEKDAYS[selectedDate.getDay()]})
          {selected === today && <span className="today-badge">오늘</span>}
        </h2>
        {selectedEvents.length === 0 ? (
          ongoing.length === 0 && <p className="me-help">{scope === "mine" ? "이날은 내 공지·저장한 공지 일정이 없어요." : "이날은 일정이 없어요."}</p>
        ) : (
          <ul>
            {selectedEvents.map((event) => (
              <li key={`${event.notice_id}-${event.kind}-${event.label}`}>
                <Link href={`/?notice=${event.notice_id}`}>
                  {event.kind === "deadline" ? (() => {
                    const badge = deadlineBadge(event.date, today);
                    return <span className={`kind-badge deadline${badge.past ? " past" : ""}`}>{badge.text}</span>;
                  })() : <span className={`kind-badge ${event.kind}`}>{event.label}</span>}
                  <span className="agenda-title">
                    {/* 시험일·발표일 항목에서 "원서접수"는 틀린 말이라 뗀다. */}
                    <strong>{event.kind === "deadline" || event.kind === "open" ? event.title : event.title.replace(/\s*원서접수$/, "")}</strong>
                    <CategoryTag category={event.category} />
                  </span>
                  <ChevronRight size={16} />
                </Link>
              </li>
            ))}
          </ul>
        )}
        {ongoing.length > 0 && (
          <>
            <h3 className="ongoing-head">{selected === today ? "지금 접수중" : "이날 접수중"} <em>{ongoing.length}건</em></h3>
            <ul>
              {ongoing.map((event) => {
                const badge = deadlineBadge(event.end ?? event.date, selected);
                return (
                  <li key={`${event.notice_id}-period`}>
                    <Link href={`/?notice=${event.notice_id}`}>
                      <span className="kind-badge open">{badge.text}</span>
                      <span className="agenda-title">
                        <strong>{event.title}</strong>
                        <CategoryTag category={event.category} />
                      </span>
                      <ChevronRight size={16} />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </section>
    </main>
  );
}
