export type BriefField = {
  label: string;
  value: string;
  found: boolean;
  method?: string | null;
};

export type StructuredNotice = {
  title: string;
  category: string;
  summary: string;
  brief?: BriefField[];
  deadline?: string | null;
  target_departments?: string[];
  target_students?: string[];
  keywords?: string[];
  action_required?: string | null;
  topics?: string[];
  schedule?: { date: string; label: string }[];
  // 접수 시작·마감. 시각까지 알면 "YYYY-MM-DDTHH:MM"(한국 시간), 날짜만 알면 "YYYY-MM-DD".
  open_at?: string | null;
  close_at?: string | null;
};

export type Notice = {
  id: number;
  source: string;
  source_url: string;
  title: string;
  structured_json: StructuredNotice | null;
  category: string;
  published_at: string | null;
  crawled_at: string;
  // 같은 공지가 함께 올라온 다른 게시판 이름.
  also_in?: string[];
};

export type InboxEntry = {
  id: number;
  // new: 새 공지, deadline: 마감 7·3·1일 전, time: 접수 시작·마감 시각, test: 테스트
  kind: "new" | "deadline" | "time" | "test";
  title: string;
  body: string;
  url: string;
  notice_id: number | null;
  created_at: string;
  read: boolean;
};

export type UpcomingAlarm = {
  // 한국 시간 "YYYY-MM-DD HH:MM"
  when: string;
  label: string;
  notice_id: number;
  title: string;
  saved: boolean;
};

export type CalendarEvent = {
  date: string;
  // deadline: 마감, exam: 시험일, result: 성적·합격 발표
  kind: "deadline" | "exam" | "result";
  label: string;
  notice_id: number;
  title: string;
  category: string;
};

export type EvalItem = {
  notice_id: number;
  title: string;
  source: string;
  source_url: string;
  predicted_category: string;
  predicted_deadline: string | null;
  gold_category: string | null;
  gold_deadline: string | null;
  labeled: boolean;
};

export type EvalReport = {
  mode: string;
  labeled: number;
  category_accuracy: number | null;
  deadline_accuracy: number | null;
  deadline_precision: number | null;
  deadline_recall: number | null;
  per_category: Record<string, { total: number; accuracy: number | null }>;
  errors: { notice_id: number; title: string; field: string; gold: string; predicted: string }[];
};

export type NoticeList = {
  items: Notice[];
  total: number;
  categories: string[];
};

export type MatchedNotice = {
  notice: Notice;
  relevance_reason: string;
  score: number;
  days_left: number | null;
};

// new: 새 공지, deadline: 마감 7·3·1일 전, time: 접수 시작·마감 시각, quiet: 밤 11시~아침 8시 방해 금지
export type AlertPref = "new" | "deadline" | "time" | "quiet";

export type Profile = {
  id?: number;
  web_device_id: string;
  display_name?: string;
  department: string;
  interests: string[];
  notify_categories?: string[];
  // 휴대폰 알림 종류별 켜기/끄기. 없는 키는 켜짐.
  alert_prefs?: Partial<Record<AlertPref, boolean>> | null;
  created_at?: string;
};


