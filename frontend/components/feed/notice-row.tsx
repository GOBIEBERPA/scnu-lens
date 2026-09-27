import { SaveButton } from "@/components/feed/save-button";
import { applyStatus, categoryClass, formatDate } from "@/lib/notice-format";
import type { Notice } from "@/lib/types";

type Props = {
  notice: Notice;
  onOpen: (notice: Notice) => void;
  saved: boolean;
  onToggleSave: () => void;
  // "나에게" 탭에서만: 왜 나에게 해당되는지 한 줄.
  reason?: string;
};

// 입력: 공지·열기 동작·저장 상태·매칭 이유, 출력: 제목·분야·출처·날짜와 D-day·별표만 있는 목록 한 줄.
// 기간·대상 같은 자세한 칸은 상세 창에서 본다(목록은 훑어보기용으로 짧게).
export function NoticeRow({ notice, onOpen, saved, onToggleSave, reason }: Props) {
  const status = applyStatus(notice.structured_json);
  const others = notice.also_in?.length ?? 0;
  return (
    <li className="row">
      <button className="row-hit" type="button" onClick={() => onOpen(notice)} aria-label={`${notice.title} 자세히 보기`} />
      <div className="row-main">
        <h3>{notice.title}</h3>
        {reason && <p className="row-reason">{reason}</p>}
        <p className="row-meta">
          <span className={`row-category ${categoryClass(notice.category)}`}>{notice.category}</span>
          <span>{notice.source.replace(/ 공지$/, "")}{others > 0 && ` 외 ${others}`}</span>
          {notice.published_at && <span>{formatDate(notice.published_at)}</span>}
        </p>
      </div>
      <div className="row-side">
        {status && <span className={`row-dday ${status.tone}`}>{status.text}</span>}
        <SaveButton saved={saved} onToggle={onToggleSave} />
      </div>
    </li>
  );
}
