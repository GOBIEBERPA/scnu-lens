"use client";

import { Check, GraduationCap, Search, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

type Props = {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  autoFocus?: boolean;
};

// 학과 정규화: 공백·가운뎃점·괄호 내용 제거, 소문자.
function normalize(raw: string): string {
  return raw
    .replace(/\([^)]*\)/g, "")
    .replace(/[\s·]/g, "")
    .toLowerCase();
}

// 핵심어: 끝의 "학과|전공|학부|교육과" 제거.
function coreWord(raw: string): string {
  return normalize(raw).replace(/(학과|전공|학부|교육과)$/, "");
}

// 한글 초성 추출.
const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
function chosung(raw: string): string {
  let out = "";
  for (const ch of raw) {
    const code = ch.charCodeAt(0);
    if (code >= 0xac00 && code <= 0xd7a3) {
      out += CHO[Math.floor((code - 0xac00) / 588)];
    }
  }
  return out;
}

function isAllChosung(q: string): boolean {
  if (!q) return false;
  return [...q].every((ch) => CHO.includes(ch));
}

// 부분 포함 구간 찾기(강조용). 못 찾으면 -1.
function indexOf(haystack: string, needle: string): number {
  if (!needle) return -1;
  return haystack.indexOf(needle);
}

// 음절 순서 일치: q의 각 글자가 이름에 순서대로 나타나는 위치들.
function syllableOrderPositions(name: string, q: string): number[] | null {
  if (q.length < 2) return null;
  const positions: number[] = [];
  let cursor = 0;
  for (const ch of q) {
    const found = name.indexOf(ch, cursor);
    if (found === -1) return null;
    positions.push(found);
    cursor = found + 1;
  }
  return positions;
}

type Match = {
  name: string;
  score: number;
  highlight: { start: number; end: number; positions?: number[] } | null;
};

// 입력: 학과 이름 목록과 검색어; 출력: 점수 내림차순·가나다순 정렬된 매치 목록.
function search(options: string[], rawQuery: string): Match[] {
  const q = normalize(rawQuery);
  if (!q) {
    return options
      .slice()
      .sort((a, b) => a.localeCompare(b, "ko"))
      .map((name) => ({ name, score: 0, highlight: null }));
  }

  const allChosung = isAllChosung(rawQuery.trim());
  const results: Match[] = [];

  for (const name of options) {
    const norm = normalize(name);
    const core = coreWord(name);
    let score = 0;
    let highlight: Match["highlight"] = null;

    if (norm === q) {
      score = 100;
      const start = name.indexOf(rawQuery.trim());
      if (start >= 0) highlight = { start, end: start + rawQuery.trim().length };
    } else if (norm.startsWith(q)) {
      score = 80;
      const start = name.indexOf(rawQuery.trim());
      if (start >= 0) highlight = { start, end: start + rawQuery.trim().length };
    } else if (norm.includes(q)) {
      score = 60;
      const start = name.indexOf(rawQuery.trim());
      if (start >= 0) highlight = { start, end: start + rawQuery.trim().length };
    } else if (core.includes(q)) {
      score = 55;
      const start = name.indexOf(rawQuery.trim());
      if (start >= 0) highlight = { start, end: start + rawQuery.trim().length };
    } else {
      const positions = syllableOrderPositions(norm, q);
      if (positions) {
        // 원본 name 기준 위치로 매핑(정규화 시 괄호·공백 제거한 만큼 오차 가능하므로 그대로 사용).
        score = 40;
        // 원본에서 각 글자를 순서대로 찾기
        const rawPositions: number[] = [];
        let cursor = 0;
        for (const ch of rawQuery) {
          const found = name.indexOf(ch, cursor);
          if (found === -1) break;
          rawPositions.push(found);
          cursor = found + 1;
        }
        if (rawPositions.length === rawQuery.length) {
          highlight = { start: 0, end: 0, positions: rawPositions };
        }
      } else if (allChosung) {
        // 초성 문자열의 위치를 원래 이름의 글자 위치로 되돌린다(가운뎃점 등 한글이 아닌 글자는 초성이 없다).
        const syllableIndex = [...name].flatMap((ch, i) => (/[가-힣]/.test(ch) ? [i] : []));
        const at = chosung(name).indexOf(q);
        if (at >= 0) {
          score = 35;
          highlight = { start: 0, end: 0, positions: syllableIndex.slice(at, at + q.length) };
        }
      }
    }

    if (score > 0) results.push({ name, score, highlight });
  }

  results.sort((a, b) => (b.score - a.score) || a.name.localeCompare(b.name, "ko"));
  return results;
}

type HighlightedNameProps = {
  name: string;
  match: Match | null;
  query: string;
};

// 입력: 이름·매치 정보·검색어; 출력: 매치된 글자를 <mark>로 감싼 이름.
function HighlightedName({ name, match, query }: HighlightedNameProps) {
  if (!match?.highlight) return <>{name}</>;
  const { start, end, positions } = match.highlight;

  if (positions && positions.length > 0) {
    const set = new Set(positions);
    return (
      <>
        {[...name].map((ch, i) =>
          set.has(i) ? <mark key={i}>{ch}</mark> : <span key={i}>{ch}</span>
        )}
      </>
    );
  }

  if (end > start) {
    return (
      <>
        {name.slice(0, start)}
        <mark>{name.slice(start, end)}</mark>
        {name.slice(end)}
      </>
    );
  }

  void query;
  return <>{name}</>;
}

type View =
  | { kind: "selected" }
  | { kind: "search" }
  | { kind: "none" };

// 입력: 현재 학과 value·학과 목록·변경 콜백; 출력: 목록에서만 학과를 고르게 하는 픽커.
export function DepartmentPicker({ value, options, onChange, autoFocus }: Props) {
  const inList = Boolean(value) && value !== "미설정" && options.includes(value);
  const legacy = Boolean(value) && value !== "미설정" && options.length > 0 && !options.includes(value);

  const [view, setView] = useState<View>(() => {
    if (value === "미설정") return { kind: "none" };
    if (inList) return { kind: "selected" };
    return { kind: "search" };
  });
  const [query, setQuery] = useState(() => (legacy ? value : ""));
  const [activeIndex, setActiveIndex] = useState(0);
  const [composing, setComposing] = useState(false);
  // 사용자가 직접 만지기 전까지는 늦게 도착한 프로필·학과 목록에 맞춰 보기를 다시 정한다.
  const [touched, setTouched] = useState(false);
  // 사용자가 "바꾸기"를 눌렀을 때만 입력창에 포커스한다(시트가 열리자마자 휴대폰 키보드가 올라오지 않게).
  const [focusWanted, setFocusWanted] = useState(Boolean(autoFocus));
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const prevSelectionRef = useRef<string>(inList ? value : "");
  const listboxId = useId();

  useEffect(() => {
    if (touched) return;
    if (value === "미설정") setView({ kind: "none" });
    else if (inList) setView({ kind: "selected" });
    else {
      setView({ kind: "search" });
      if (legacy) setQuery(value);
    }
  }, [value, inList, legacy, touched]);

  useEffect(() => {
    if (view.kind !== "search" || !focusWanted) return;
    const el = inputRef.current;
    if (el) {
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }
    setFocusWanted(false);
  }, [view.kind, focusWanted]);

  const matches = useMemo(() => search(options, query), [options, query]);
  const showAll = !query.trim();

  // 활성 항목 보이게 스크롤.
  useEffect(() => {
    if (view.kind !== "search") return;
    const list = listRef.current;
    if (!list) return;
    const el = list.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`);
    if (el) el.scrollIntoView({ block: "nearest" });
  }, [activeIndex, view.kind, matches.length]);

  function startSearch() {
    prevSelectionRef.current = inList ? value : "";
    setTouched(true);
    setFocusWanted(true);
    setQuery("");
    setActiveIndex(0);
    setView({ kind: "search" });
  }

  function pick(name: string) {
    setTouched(true);
    onChange(name);
    setQuery("");
    setView({ kind: "selected" });
  }

  function cancel() {
    if (prevSelectionRef.current && options.includes(prevSelectionRef.current)) {
      setView({ kind: "selected" });
    } else if (value && options.includes(value)) {
      setView({ kind: "selected" });
    } else {
      setView({ kind: "search" });
    }
    setQuery("");
  }

  function skip() {
    setTouched(true);
    onChange("미설정");
    setView({ kind: "none" });
    setQuery("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (composing || event.nativeEvent.isComposing) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (matches.length) setActiveIndex((i) => Math.min(i + 1, matches.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const item = matches[activeIndex];
      if (item) pick(item.name);
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  }

  const canCancel = Boolean(prevSelectionRef.current) || (value && options.includes(value));

  // 1) 선택됨 보기
  if (view.kind === "selected" && inList) {
    return (
      <div className="dept-picker">
        <div className="dept-selected">
          <GraduationCap size={20} aria-hidden="true" />
          <span className="dept-selected-name">{value}</span>
          <button type="button" className="dept-change" onClick={startSearch}>
            바꾸기
          </button>
        </div>
        <p className="dept-help">이 학과 게시판에 올라온 공지를 ‘나에게’에 모아드려요.</p>
      </div>
    );
  }

  // 3) 학과 없음 보기
  if (view.kind === "none") {
    return (
      <div className="dept-picker">
        <div className="dept-none">
          <span>학과를 고르지 않았어요 · 학과 게시판 공지는 빠져요</span>
          <button type="button" className="dept-change" onClick={startSearch}>
            학과 고르기
          </button>
        </div>
      </div>
    );
  }

  // 2) 찾기
  const activeId = matches.length ? `${listboxId}-${activeIndex}` : undefined;

  return (
    <div className="dept-picker">
      {legacy && (
        <p className="dept-warn">
          ‘{value}’은(는) 목록에 없어요. 아래에서 골라 주세요.
        </p>
      )}
      <div className="dept-search">
        <Search size={18} aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          placeholder="학과 이름으로 찾기 (예: 컴퓨터, 간호)"
          autoComplete="off"
          role="combobox"
          aria-expanded="true"
          aria-controls={listboxId}
          aria-activedescendant={activeId}
          aria-autocomplete="list"
          onChange={(event) => {
            setTouched(true);
            setQuery(event.target.value);
            setActiveIndex(0);
          }}
          onCompositionStart={() => setComposing(true)}
          onCompositionEnd={() => setComposing(false)}
          onKeyDown={onKeyDown}
        />
        {query && (
          <button
            type="button"
            className="dept-clear"
            aria-label="입력 지우기"
            onClick={() => {
              setQuery("");
              setActiveIndex(0);
              inputRef.current?.focus();
            }}
          >
            <X size={16} />
          </button>
        )}
        {canCancel && (
          <button type="button" className="dept-cancel" onClick={cancel}>
            취소
          </button>
        )}
      </div>

      <div className="dept-panel" id={listboxId} role="listbox" ref={listRef}>
        {options.length === 0 ? (
          <p className="dept-empty">학과 목록을 불러오는 중…</p>
        ) : (
          <>
            <div className="dept-panel-head">
              {showAll
                ? `전체 ${options.length}개`
                : `‘${query}’ 검색 결과 ${matches.length}개`}
            </div>
            {matches.length === 0 ? (
              <p className="dept-empty">
                ‘{query}’에 맞는 학과가 없어요. ‘컴퓨터’, ‘전자’처럼 줄여서 찾아보세요.
              </p>
            ) : (
              matches.map((match, index) => {
                const current = value && value === match.name;
                const active = index === activeIndex;
                return (
                  <button
                    key={match.name}
                    type="button"
                    id={`${listboxId}-${index}`}
                    data-index={index}
                    className={`dept-option ${active ? "active" : ""} ${current ? "current" : ""}`}
                    role="option"
                    aria-selected={current || active}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => pick(match.name)}
                  >
                    <span>
                      <HighlightedName name={match.name} match={match} query={query} />
                    </span>
                    {current && <Check size={16} aria-hidden="true" />}
                  </button>
                );
              })
            )}
            <button type="button" className="dept-skip" onClick={skip}>
              목록에 내 학과가 없어요 · 학과 없이 계속
            </button>
          </>
        )}
      </div>
    </div>
  );
}
