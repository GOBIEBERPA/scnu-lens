import type {
  CalendarEvent,
  EvalItem,
  EvalReport,
  InboxEntry,
  MatchedNotice,
  Notice,
  NoticeList,
  Profile,
  UpcomingAlarm,
} from "@/lib/types";

// 배포 시에는 NEXT_PUBLIC_API_URL을 쓰고, 그 외에는 접속한 호스트를 그대로 따라간다.
// 그래야 PC에서 localhost로 열든 휴대폰에서 Tailscale 주소로 열든 같은 코드가 동작한다.
const API_PORT = 8001;

// 입력 없음, 출력: 현재 접속 주소에 맞춘 API 기본 경로.
function apiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined") {
    // https로 열렸다면 tailscale serve나 배포 환경이라 리버스 프록시가 /api를 넘겨준다.
    if (window.location.protocol === "https:") return "/api";
    return `http://${window.location.hostname}:${API_PORT}/api`;
  }
  return `http://localhost:${API_PORT}/api`;
}

// 입력 없음, 출력: 지금 실제로 호출 중인 API 주소; 연결 실패 원인을 화면에 보여줄 때 쓴다.
export function apiBaseForDisplay(): string {
  return apiBase();
}

// 입력: API 경로·fetch 옵션, 출력: JSON 타입 T; 비정상 응답은 한국어 오류로 변환한다.
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "요청을 처리하지 못했습니다." }));
    throw new Error(payload.detail || "요청을 처리하지 못했습니다.");
  }
  return response.json() as Promise<T>;
}

export type NoticeQuery = {
  category: string;
  search: string;
  page: number;
  perPage: number;
  // latest: 최신순, deadline: 마감 전 공지만 마감 가까운 순
  sort: "latest" | "deadline";
  // today: 오늘 올라온 공지, urgent: 3일 안에 마감
  due: "today" | "urgent" | null;
  // school: 학교 게시판, external: 공모전·시험 일정, null: 전체
  origin: "school" | "external" | null;
  // 마감일이 지난 공지를 뺀다(마감일 없는 공지는 남김).
  hideClosed: boolean;
};

export type NoticeStats = {
  total: number;
  today: number;
  urgent: number;
  categories: Record<string, number>;
  categories_by_origin: { school: Record<string, number>; external: Record<string, number> };
  urgent_by_origin: { school: number; external: number };
};

// 입력: 분야·검색어·페이지·정렬·빠른 필터·출처, 출력: 조건에 맞는 공지 한 페이지와 전체 개수.
export async function fetchNotices(query: NoticeQuery): Promise<NoticeList> {
  const params = new URLSearchParams({ page: String(query.page), per_page: String(query.perPage), sort: query.sort });
  if (query.category !== "전체") params.set("category", query.category);
  if (query.search) params.set("search", query.search);
  if (query.due) params.set("due", query.due);
  if (query.origin) params.set("origin", query.origin);
  if (query.hideClosed) params.set("hide_closed", "true");
  return request<NoticeList>(`/notices?${params}`);
}

// 입력 없음, 출력: 전체 공지 기준 오늘 올라온 수·3일 안 마감 수·분야별 공지 수.
export async function fetchNoticeStats(): Promise<NoticeStats> {
  return request<NoticeStats>("/notices/stats");
}

// 입력: 공지 ID, 출력: 공지 한 건(알림·공유 링크로 들어왔을 때 상세 창을 바로 열기 위해).
export async function fetchNotice(noticeId: number): Promise<Notice> {
  return request<Notice>(`/notices/${noticeId}`);
}

// 입력: 기기 ID, 출력: 알림함 항목(새것 먼저)과 안 읽은 수.
export async function fetchInbox(deviceId: string): Promise<{ items: InboxEntry[]; unread: number }> {
  return request<{ items: InboxEntry[]; unread: number }>(`/inbox?web_device_id=${encodeURIComponent(deviceId)}`);
}

// 입력: 기기 ID, 출력: 안 읽은 알림 수(상단 종 배지).
export async function fetchUnreadCount(deviceId: string): Promise<number> {
  const data = await request<{ unread: number }>(`/inbox/unread-count?web_device_id=${encodeURIComponent(deviceId)}`);
  return data.unread;
}

// 입력: 기기 ID·읽음 처리할 ID(없으면 전부), 출력: 남은 안 읽은 수.
export async function markInboxRead(deviceId: string, ids?: number[]): Promise<number> {
  const data = await request<{ unread: number }>("/inbox/read", {
    method: "POST",
    body: JSON.stringify({ web_device_id: deviceId, ids: ids ?? null }),
  });
  return data.unread;
}

// 입력: 기기 ID, 출력: 앞으로 2주 안에 울릴 알림.
export async function fetchUpcomingAlarms(deviceId: string): Promise<UpcomingAlarm[]> {
  return request<UpcomingAlarm[]>(`/inbox/upcoming?web_device_id=${encodeURIComponent(deviceId)}`);
}

// 입력: 기간(YYYY-MM-DD)·범위·기기 ID, 출력: 그 기간의 마감·시험·발표 일정.
export async function fetchCalendarEvents(start: string, end: string, scope: "all" | "mine", deviceId: string): Promise<CalendarEvent[]> {
  const params = new URLSearchParams({ start, end, scope });
  if (scope === "mine") params.set("web_device_id", deviceId);
  return request<CalendarEvent[]>(`/calendar/events?${params}`);
}

// 입력 없음, 출력: 수집 중인 학과·전공 게시판 이름(마이페이지 학과 자동완성).
export async function fetchDepartments(): Promise<string[]> {
  return request<string[]>("/departments");
}

// 입력: 웹 기기 ID, 출력: 학과·관심사와 매칭된 공지와 그 근거 목록.
export async function fetchMatchedNotices(deviceId: string): Promise<MatchedNotice[]> {
  return request<MatchedNotice[]>(`/notices/for-me?web_device_id=${encodeURIComponent(deviceId)}`);
}

// 입력: 기기 ID, 출력: 별표로 저장한 공지(최근 저장 순).
export async function fetchSavedNotices(deviceId: string): Promise<Notice[]> {
  return request<Notice[]>(`/notices/saved?web_device_id=${encodeURIComponent(deviceId)}`);
}

// 입력: 공지 ID·기기 ID·저장 여부, 출력: 바뀐 뒤의 저장 공지 ID 목록.
export async function setNoticeSaved(noticeId: number, deviceId: string, saved: boolean): Promise<number[]> {
  const result = await request<{ ids: number[] }>(
    `/notices/${noticeId}/save?web_device_id=${encodeURIComponent(deviceId)}`,
    { method: saved ? "PUT" : "DELETE" },
  );
  return result.ids;
}

// 입력: API 경로, 출력: 캘린더 앱에 넘길 절대 주소(상대 경로 /api도 현재 주소 기준으로 바꾼다).
function absoluteApi(path: string): string {
  const base = apiBase();
  const absolute = base.startsWith("http") ? base : `${window.location.origin}${base}`;
  return `${absolute}${path}`;
}

// 입력: 공지 ID, 출력: 그 공지 마감일 하나를 담은 .ics 내려받기 주소.
export function noticeCalendarUrl(noticeId: number): string {
  return absoluteApi(`/notices/${noticeId}/calendar.ics`);
}

// 입력: 기기 ID, 출력: 내 마감 일정 구독 주소(https)와 캘린더 앱이 바로 여는 webcal 주소.
export function myCalendarUrls(deviceId: string): { https: string; webcal: string } {
  const https = absoluteApi(`/calendar/${encodeURIComponent(deviceId)}.ics`);
  return { https, webcal: https.replace(/^https?:/, "webcal:") };
}

// 입력: 관리자 키, 출력: 정답 입력용 공지 목록과 현재 예측.
export async function fetchEvalItems(adminKey: string): Promise<EvalItem[]> {
  return request<EvalItem[]>("/admin/eval/items", { headers: { "X-Admin-Key": adminKey } });
}

// 입력: 관리자 키·공지 ID·정답(없으면 삭제), 출력 없음.
export async function saveEvalLabel(
  adminKey: string,
  noticeId: number,
  label: { category: string; deadline: string | null } | null,
) {
  return request(`/admin/eval/${noticeId}`, {
    method: label ? "PUT" : "DELETE",
    headers: { "X-Admin-Key": adminKey },
    body: label ? JSON.stringify(label) : undefined,
  });
}

// 입력: 관리자 키, 출력: 정답지 기준 정확도 보고서.
export async function fetchEvalReport(adminKey: string): Promise<EvalReport> {
  return request<EvalReport>("/admin/eval/report", { headers: { "X-Admin-Key": adminKey } });
}

// 입력: 웹 기기 프로필, 출력: 생성 또는 갱신된 프로필.
export async function saveProfile(profile: Profile): Promise<Profile> {
  return request<Profile>("/profiles", { method: "POST", body: JSON.stringify(profile) });
}

// 입력: 웹 기기 ID, 출력: 저장된 프로필; 없으면 오류를 던진다.
export async function fetchProfile(deviceId: string): Promise<Profile> {
  return request<Profile>(`/profiles?web_device_id=${encodeURIComponent(deviceId)}`);
}

// 입력 없음, 출력: 웹 푸시 사용 가능 여부와 VAPID 공개키.
export async function fetchPushKey(): Promise<{ enabled: boolean; public_key: string }> {
  return request<{ enabled: boolean; public_key: string }>("/push/key");
}

// 입력: 기기 ID·브라우저 구독 정보, 출력 없음; 서버에 구독을 등록한다.
export async function savePushSubscription(deviceId: string, subscription: PushSubscriptionJSON) {
  return request("/push/subscribe", {
    method: "POST",
    body: JSON.stringify({ web_device_id: deviceId, subscription }),
  });
}

// 입력: 기기 ID, 출력: 서버가 실제로 테스트 알림을 보냈는지와 그 이유.
export async function sendTestPush(deviceId: string): Promise<{ ok: boolean; reason: string }> {
  return request<{ ok: boolean; reason: string }>(`/push/test?web_device_id=${encodeURIComponent(deviceId)}`, {
    method: "POST",
  });
}

// 입력: 기기 ID, 출력 없음; 서버에 저장된 구독을 삭제한다.
export async function removePushSubscription(deviceId: string) {
  return request(`/push/subscribe?web_device_id=${encodeURIComponent(deviceId)}`, { method: "DELETE" });
}

// 입력: 관리자 키, 출력: 현재 크롤러 소스 목록.
export async function fetchSources(adminKey: string) {
  return request<Array<{
    id: number;
    name: string;
    url: string;
    category_hint: string;
    is_active: boolean;
    last_crawled_at: string | null;
    last_fetched: number | null;
    last_error: string | null;
  }>>(
    "/admin/sources",
    { headers: { "X-Admin-Key": adminKey } },
  );
}

// 입력: 관리자 키·소스 ID·활성값, 출력: 갱신된 소스.
export async function toggleSource(adminKey: string, sourceId: number, isActive: boolean) {
  return request(`/admin/sources/${sourceId}`, {
    method: "PATCH",
    headers: { "X-Admin-Key": adminKey },
    body: JSON.stringify({ is_active: isActive }),
  });
}

// 입력: 관리자 키, 출력: 전체 배치 실행 집계.
export async function runCrawl(adminKey: string) {
  return request<{ fetched: number; inserted: number; structured: number; briefings_created: number; sent: number; errors: string[] }>(
    "/admin/crawl",
    { method: "POST", headers: { "X-Admin-Key": adminKey } },
  );
}

