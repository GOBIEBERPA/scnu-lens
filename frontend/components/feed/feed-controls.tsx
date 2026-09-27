import { Search, X } from "lucide-react";

import type { FeedView } from "@/components/feed/hooks";
import { CATEGORY_ORDER } from "@/lib/notice-format";

// recommend는 "나에게" 탭에서만(추천 점수 순).
export type FeedSort = "recommend" | "latest" | "deadline" | "opening" | "roomy";
export type ApplyFilter = "open" | "upcoming" | null;

type Props = {
  view: FeedView;
  onView: (view: FeedView) => void;
  // 탭 옆 숫자: 나에게 해당되는 공지 수, 학교·외부 공지 수.
  tabCounts: Record<FeedView, number>;
  search: string;
  onSearch: (value: string) => void;
  // 지금 탭의 분야별 공지 수.
  counts: Record<string, number>;
  category: string;
  onCategory: (category: string) => void;
  urgentCount: number;
  urgentOnly: boolean;
  onUrgent: (on: boolean) => void;
  // 접수중·접수 예정 칩과 그 숫자.
  status: ApplyFilter;
  onStatus: (status: ApplyFilter) => void;
  statusCounts: { open: number; upcoming: number };
  sort: FeedSort;
  onSort: (sort: FeedSort) => void;
};

const TABS: { value: FeedView; label: string }[] = [
  { value: "mine", label: "나에게" },
  { value: "school", label: "학교" },
  { value: "external", label: "공모전·자격증" },
];

const SORT_LABELS: Record<FeedSort, string> = {
  recommend: "추천순",
  latest: "최신순",
  deadline: "마감 임박순",
  opening: "접수 시작순",
  roomy: "마감 여유순",
};

// 입력: 탭·검색·분야·접수 상태·정렬 상태와 변경 함수, 출력: 탭 한 줄, 검색창, 칩 한 줄(마감임박·접수중·접수 예정·분야)과 정렬 선택.
export function FeedControls(props: Props) {
  const { view, onView, tabCounts, search, onSearch, counts, category, onCategory } = props;
  const { urgentCount, urgentOnly, onUrgent, status, onStatus, statusCounts, sort, onSort } = props;
  const mine = view === "mine";
  const categories = mine ? [] : CATEGORY_ORDER.filter((name) => counts[name]);
  const sorts: FeedSort[] = mine ? ["recommend", "deadline", "opening", "roomy"] : ["latest", "deadline", "opening", "roomy"];
  const plain = category === "전체" && !urgentOnly && !status;
  return (
    <div className="feed-controls">
      <div className="tabs" role="tablist" aria-label="공지 보기">
        {TABS.map((tab) => (
          <button
            type="button"
            role="tab"
            key={tab.value}
            aria-selected={view === tab.value}
            className={view === tab.value ? "active" : ""}
            onClick={() => onView(tab.value)}
          >
            {tab.label}
            {tabCounts[tab.value] > 0 && <span className="count">{tabCounts[tab.value]}</span>}
          </button>
        ))}
      </div>

      {!mine && (
        <label className="search">
          <Search size={16} />
          <input
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="검색"
            enterKeyHint="search"
            aria-label="제목·본문·첨부파일 검색"
          />
          {search && <button type="button" onClick={() => onSearch("")} aria-label="검색어 지우기"><X size={14} /></button>}
        </label>
      )}
      <div className="chips" role="toolbar" aria-label="접수 상태·분야와 정렬">
        <div className="chips-scroll">
          <button type="button" className={plain ? "active" : ""} onClick={() => { onCategory("전체"); onUrgent(false); onStatus(null); }}>
            전체
          </button>
          {urgentCount > 0 && (
            <button type="button" className={`urgent ${urgentOnly ? "active" : ""}`} aria-pressed={urgentOnly} onClick={() => onUrgent(!urgentOnly)}>
              마감임박 {urgentCount}
            </button>
          )}
          {statusCounts.open > 0 && (
            <button type="button" className={`status-open ${status === "open" ? "active" : ""}`} aria-pressed={status === "open"}
              onClick={() => onStatus(status === "open" ? null : "open")}>
              접수중 {statusCounts.open}
            </button>
          )}
          {statusCounts.upcoming > 0 && (
            <button type="button" className={`status-upcoming ${status === "upcoming" ? "active" : ""}`} aria-pressed={status === "upcoming"}
              onClick={() => onStatus(status === "upcoming" ? null : "upcoming")}>
              접수 예정 {statusCounts.upcoming}
            </button>
          )}
          {categories.map((name) => (
            <button type="button" key={name} className={category === name ? "active" : ""} aria-pressed={category === name} onClick={() => onCategory(category === name ? "전체" : name)}>
              {name}
            </button>
          ))}
        </div>
        <label className="sort">
          <select value={sort} onChange={(event) => onSort(event.target.value as FeedSort)} aria-label="정렬">
            {sorts.map((value) => <option key={value} value={value}>{SORT_LABELS[value]}</option>)}
          </select>
        </label>
      </div>
    </div>
  );
}
