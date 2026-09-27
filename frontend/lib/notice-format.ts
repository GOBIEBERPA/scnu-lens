import type { Notice } from "@/lib/types";

// 눌러서 넣는 관심 키워드. 서버의 동의어 사전(INTEREST_SYNONYMS)에 있는 말이라 비슷한 표현까지 잡힌다.
export const SUGGESTED_INTERESTS = ["장학금", "취업", "인턴", "AI", "코딩", "공모전", "창업", "해외", "대학원", "봉사", "수강신청"];

// 분야 칩 순서. 학생이 자주 찾는 것부터, '기타'는 맨 뒤.
export const CATEGORY_ORDER = ["학사", "장학", "취업", "경진대회", "자격증", "행사", "연구실", "안전", "기타"];

// 입력: 카테고리 문자열, 출력: 카테고리별 CSS 색상 토큰 클래스.
export function categoryClass(category: string): string {
  const classes: Record<string, string> = {
    학사: "tag-blue",
    장학: "tag-lime",
    취업: "tag-orange",
    행사: "tag-purple",
    경진대회: "tag-pink",
    자격증: "tag-indigo",
    연구실: "tag-teal",
    안전: "tag-red",
  };
  return classes[category] || "tag-gray";
}

// 입력: ISO 날짜 또는 null, 출력: 학생이 읽기 쉬운 월·일 문자열.
export function formatDate(value: string | null): string {
  if (!value) return "날짜 미상";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

// 서버(app/services/alarms.py)와 같은 알림 규칙. 화면에 "알림 예정"을 보여줄 때만 쓴다.
const DAY_ALARMS = [7, 3, 1];
const DAY_ALARM_HOUR = 9;
const TIME_ALARMS: { field: "open_at" | "close_at"; minutes: number; label: string }[] = [
  { field: "open_at", minutes: 60, label: "접수 시작 1시간 전" },
  { field: "open_at", minutes: 5, label: "접수 시작 5분 전" },
  { field: "open_at", minutes: 0, label: "접수 시작" },
  { field: "close_at", minutes: 60, label: "마감 1시간 전" },
  { field: "close_at", minutes: 10, label: "마감 10분 전" },
  { field: "close_at", minutes: 0, label: "접수 마감" },
];

// 입력: 한국 시간 "YYYY-MM-DDTHH:MM"과 분, 출력: 그만큼 앞선 시각의 Date(이 기기 시간대 기준 표시용).
function minus(value: string, minutes: number): Date {
  return new Date(new Date(`${value}:00+09:00`).getTime() - minutes * 60_000);
}

// 입력: Date, 출력: "10월 7일 09:00".
function formatStamp(date: Date): string {
  const two = (n: number) => String(n).padStart(2, "0");
  return `${date.getMonth() + 1}월 ${date.getDate()}일 ${two(date.getHours())}:${two(date.getMinutes())}`;
}

// 입력: 공지, 출력: 앞으로 울릴 알림 (언제, 무엇) 목록. 시각을 모르는 공지는 날짜 알림만 나온다.
export function alarmPlan(notice: Notice): { when: string; label: string }[] {
  const structured = notice.structured_json;
  if (!structured) return [];
  const now = Date.now();
  const plan: { at: Date; label: string }[] = [];
  if (structured.deadline) {
    for (const days of DAY_ALARMS) {
      const at = new Date(`${structured.deadline}T${String(DAY_ALARM_HOUR).padStart(2, "0")}:00:00+09:00`);
      at.setDate(at.getDate() - days);
      plan.push({ at, label: `마감 ${days}일 전` });
    }
  }
  for (const alarm of TIME_ALARMS) {
    const value = structured[alarm.field];
    if (value && value.includes("T")) plan.push({ at: minus(value, alarm.minutes), label: alarm.label });
  }
  return plan
    .filter((item) => item.at.getTime() > now)
    .sort((a, b) => a.at.getTime() - b.at.getTime())
    .map((item) => ({ when: formatStamp(item.at), label: item.label }));
}

// 입력: 마감일 문자열, 출력: 오늘 기준 D-day 라벨; 파싱 불가 시 원문 날짜.
export function deadlineLabel(deadline?: string | null): string | null {
  if (!deadline) return null;
  // "YYYY-MM-DD"만 넘기면 UTC 자정(한국 오전 9시)으로 읽혀 하루가 더 붙으므로 현지 자정으로 읽는다.
  const date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(deadline) ? `${deadline}T00:00:00` : deadline);
  if (Number.isNaN(date.getTime())) return `마감 ${deadline}`;
  date.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((date.getTime() - today.getTime()) / 86_400_000);
  if (days < 0) return "마감됨";
  if (days === 0) return "오늘 마감";
  return `D-${days}`;
}

export type ApplyTone = "before" | "open" | "plain" | "urgent" | "closed";

// 입력: "YYYY-MM-DD…", 출력: "10/12".
function shortDay(value: string): string {
  const [, month, day] = value.slice(0, 10).split("-").map(Number);
  return `${month}/${day}`;
}

// 입력: 구조화 결과(마감일·접수 시작), 출력: 접수 상태 글자와 색 종류.
// 신청기간이 "10.12 ~ 10.16"이면 시작 전에는 D-day 대신 "10/12 접수 시작"을 보여준다(열리기 전에 들어가 헛걸음하지 않게).
export function applyStatus(structured?: { deadline?: string | null; open_at?: string | null } | null): { text: string; tone: ApplyTone } | null {
  const deadline = deadlineLabel(structured?.deadline);
  const opens = structured?.open_at?.slice(0, 10);
  if (opens && (!structured?.deadline || opens < structured.deadline)) {
    const start = new Date(`${opens}T00:00:00`);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (start.getTime() > today.getTime()) return { text: `${shortDay(opens)} 접수 시작`, tone: "before" };
  }
  if (!deadline) return null;
  if (deadline === "마감됨") return { text: "마감", tone: "closed" };
  const urgent = deadline === "오늘 마감" || /^D-[0-3]$/.test(deadline);
  if (opens) return { text: `접수중 ${deadline}`, tone: urgent ? "urgent" : "open" };
  return { text: deadline, tone: urgent ? "urgent" : "plain" };
}

// 입력: 구조화 결과, 출력: "9/22 ~ 9/29" 같은 신청기간(시작일을 모르면 null).
export function applyPeriod(structured?: { deadline?: string | null; open_at?: string | null } | null): string | null {
  const opens = structured?.open_at;
  const deadline = structured?.deadline;
  return opens && deadline && opens.slice(0, 10) < deadline ? `${shortDay(opens)} ~ ${shortDay(deadline)}` : null;
}

// 입력: 구조화 결과, 출력: 접수 상태(upcoming 접수 예정·open 접수중·closed 마감·null 모름). "나에게" 탭 필터에 쓴다.
export function applyState(structured?: { deadline?: string | null; open_at?: string | null } | null): "upcoming" | "open" | "closed" | null {
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const opens = structured?.open_at?.slice(0, 10);
  if (opens && opens > today) return "upcoming";
  if (structured?.deadline) return structured.deadline >= today ? "open" : "closed";
  return null;
}
