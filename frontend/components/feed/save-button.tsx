import { Star } from "lucide-react";

type Props = { saved: boolean; onToggle: () => void; className?: string };

// 입력: 저장 여부·전환 함수, 출력: 별 모양 저장 버튼. 저장한 공지는 매칭과 상관없이 마감 알림을 받는다.
export function SaveButton({ saved, onToggle, className = "" }: Props) {
  return (
    <button
      className={`save-star ${saved ? "on" : ""} ${className}`}
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
      aria-pressed={saved}
      aria-label={saved ? "저장 해제" : "저장하고 마감 알림 받기"}
      title={saved ? "저장됨 — 마감 전에 알려드려요" : "저장하고 마감 알림 받기"}
    >
      <Star size={18} fill={saved ? "currentColor" : "none"} />
    </button>
  );
}
