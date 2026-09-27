import { Search, X } from "lucide-react";

import type { FeedView } from "@/components/feed/hooks";
import { CATEGORY_ORDER } from "@/lib/notice-format";

type Sort = "latest" | "deadline";

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
  sort: Sort;
  onSort: (sort: Sort) => void;
};

const TABS: { value: FeedView; label: string }[] = [
  { value: "mine", label: "나에게" },
  { value: "school", label: "학교" },
  { value: "external", label: "공모전·자격증" },
];

// 입력: 탭·검색·분야·정렬 상태와 변경 함수, 출력: 탭 한 줄, 검색창, 분야 칩 한 줄(마감임박·정렬 포함).
// 예전의 지표 타일·출처 탭·정렬/개수 선택·상태 줄을 이 세 줄로 합쳤다.
export function FeedControls(props: Props) {
  const { view, onView, tabCounts, search, onSearch, counts, category, onCategory } = props;
  const { urgentCount, urgentOnly, onUrgent, sort, onSort } = props;
  const categories = CATEGORY_ORDER.filter((name) => counts[name]);
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

      {view !== "mine" && (
        <>
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
          <div className="chips" role="toolbar" aria-label="분야와 정렬">
            <div className="chips-scroll">
              <button type="button" className={category === "전체" && !urgentOnly ? "active" : ""} onClick={() => { onCategory("전체"); onUrgent(false); }}>
                전체
              </button>
              {urgentCount > 0 && (
                <button type="button" className={`urgent ${urgentOnly ? "active" : ""}`} aria-pressed={urgentOnly} onClick={() => onUrgent(!urgentOnly)}>
                  마감임박 {urgentCount}
                </button>
              )}
              {categories.map((name) => (
                <button type="button" key={name} className={category === name ? "active" : ""} aria-pressed={category === name} onClick={() => onCategory(category === name ? "전체" : name)}>
                  {name}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="sort"
              onClick={() => onSort(sort === "latest" ? "deadline" : "latest")}
              aria-label={`정렬: ${sort === "latest" ? "최신순" : "마감순"} (누르면 바뀜)`}
            >
              {sort === "latest" ? "최신순" : "마감순"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
