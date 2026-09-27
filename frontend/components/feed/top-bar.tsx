import { Bell, CalendarDays, UserRound } from "lucide-react";
import Link from "next/link";

// 입력: 안 읽은 알림 수, 출력: 이름과 알림함·캘린더·마이페이지 아이콘만 있는 상단 바.
// 연결 상태는 끊겼을 때만 목록 위 안내로 보여준다.
export function TopBar({ unread }: { unread: number }) {
  return (
    <header className="topbar">
      <Link href="/" className="brand">
        {/* 순천대 로고(홈 화면 아이콘과 같은 파일). 장식이라 대체 텍스트는 비운다. */}
        <img src="/favicon-32.png" alt="" width={24} height={24} className="brand-logo" />
        SCNU Lens
      </Link>
      <nav className="top-actions" aria-label="메뉴">
        <Link className="icon-button" href="/alerts" aria-label={unread ? `알림함, 안 읽은 알림 ${unread}건` : "알림함"}>
          <Bell size={19} />
          {unread > 0 && <span className="badge">{unread > 99 ? "99+" : unread}</span>}
        </Link>
        <Link className="icon-button" href="/calendar" aria-label="캘린더"><CalendarDays size={19} /></Link>
        <Link className="icon-button" href="/me" aria-label="마이페이지"><UserRound size={19} /></Link>
      </nav>
    </header>
  );
}
