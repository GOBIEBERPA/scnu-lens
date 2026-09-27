"use client";

import { CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { FeedControls, type ApplyFilter, type FeedSort } from "@/components/feed/feed-controls";
import { useNoticeDetail, useNoticeFeed, useSavedNotices, useUnreadCount } from "@/components/feed/hooks";
import { NoticeDetail } from "@/components/feed/notice-detail";
import { NoticeRow } from "@/components/feed/notice-row";
import { TopBar } from "@/components/feed/top-bar";
import { Onboarding } from "@/components/onboarding";
import { apiBaseForDisplay, fetchMatchedNotices, fetchNoticeStats, fetchProfile, type NoticeQuery, type NoticeStats } from "@/lib/api";
import { applyState } from "@/lib/notice-format";
import { getDeviceId } from "@/lib/device";
import type { MatchedNotice, Profile } from "@/lib/types";

// 첫 응답 전에 보여줄 자리 표시 줄 수.
const SKELETON_ROWS = 6;
// 빠른 설정 창을 이미 봤는지(기기별 편의 설정).
const ONBOARDING_KEY = "scnu-onboarding-seen";
const EMPTY_STATS: NoticeStats = {
  total: 0,
  today: 0,
  urgent: 0,
  categories: {},
  categories_by_origin: { school: {}, external: {} },
  urgent_by_origin: { school: 0, external: 0 },
  status_by_origin: { school: { open: 0, upcoming: 0 }, external: { open: 0, upcoming: 0 } },
};

// 입력 없음, 출력: 탭(나에게·학교·공모전·자격증) 하나와 공지 목록으로 된 메인 화면.
// 인사말·지표 타일·추천 카드 줄을 따로 두지 않고, 추천은 "나에게" 탭으로 합쳤다.
export function Dashboard() {
  const [deviceId, setDeviceId] = useState("");
  const [profile, setProfile] = useState<Profile>({
    web_device_id: "",
    display_name: "",
    department: "미설정",
    interests: [],
  });
  const [profileLoaded, setProfileLoaded] = useState(false);
  const [matched, setMatched] = useState<MatchedNotice[]>([]);
  const [stats, setStats] = useState<NoticeStats>(EMPTY_STATS);
  const feed = useNoticeFeed();
  const detail = useNoticeDetail();
  const saved = useSavedNotices(deviceId);
  const unread = useUnreadCount(deviceId);
  const [onboarding, setOnboarding] = useState(false);
  // "나에게" 탭은 추천 목록을 한 번에 받으므로 거르기·정렬을 화면에서 한다.
  const [mineSort, setMineSort] = useState<FeedSort>("recommend");
  const [mineStatus, setMineStatus] = useState<ApplyFilter>(null);
  const [mineUrgent, setMineUrgent] = useState(false);
  const unset = profile.department === "미설정" && profile.interests.length === 0;

  // 브라우저 최초 진입 시 기기 ID·프로필·추천 공지를 준비한다. 실패해도 공지 목록은 막지 않는다.
  useEffect(() => {
    let id = "";
    try {
      id = getDeviceId();
    } catch {
      return;
    }
    setDeviceId(id);
    setProfile((current) => ({ ...current, web_device_id: id }));
    void fetchProfile(id)
      .then(setProfile)
      .catch(() => undefined)
      .finally(() => setProfileLoaded(true));
    void fetchMatchedNotices(id).then(setMatched).catch(() => setMatched([]));
    void fetchNoticeStats().then(setStats).catch(() => undefined);
  }, []);

  // 첫 탭: 저장해 둔 탭이 없으면, 추천이 있을 때 "나에게"로 연다. 처음 온 사람은 설정 창을 한 번 띄운다.
  useEffect(() => {
    if (!profileLoaded) return;
    if (!feed.hadSavedView && !unset) feed.chooseView("mine");
    let seen = false;
    try {
      seen = localStorage.getItem(ONBOARDING_KEY) === "1";
    } catch {
      seen = false;
    }
    if (unset && !seen) setOnboarding(true);
  }, [profileLoaded]);

  function closeOnboarding() {
    setOnboarding(false);
    try {
      localStorage.setItem(ONBOARDING_KEY, "1");
    } catch {
      // 저장소를 못 쓰면 다음 방문 때 한 번 더 뜬다.
    }
  }

  // 입력: 저장된 프로필, 출력 없음; 설정을 반영하고 추천을 새로 받아 "나에게" 탭으로 보여준다.
  function finishOnboarding(next: Profile) {
    setProfile(next);
    closeOnboarding();
    feed.chooseView("mine");
    void fetchMatchedNotices(deviceId).then(setMatched).catch(() => setMatched([]));
  }

  const isOffline = Boolean(feed.loadError);
  const external = feed.view === "external";
  const counts = feed.view === "mine" ? {} : stats.categories_by_origin[external ? "external" : "school"];
  const sum = (values: Record<string, number>) => Object.values(values).reduce((total, count) => total + count, 0);
  const mine = feed.view === "mine";

  // "나에게" 탭: 접수 상태·마감임박으로 거르고 고른 순서로 정렬한다.
  const todayIso = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
  const soonIso = new Date(Date.now() + 3 * 86_400_000 - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
  const deadlineOf = (item: MatchedNotice) => item.notice.structured_json?.deadline ?? "";
  const isUrgent = (item: MatchedNotice) => deadlineOf(item) >= todayIso && deadlineOf(item) <= soonIso;
  const mineCounts = {
    open: matched.filter((item) => applyState(item.notice.structured_json) === "open").length,
    upcoming: matched.filter((item) => applyState(item.notice.structured_json) === "upcoming").length,
  };
  const mineList = matched
    .filter((item) => !mineStatus || applyState(item.notice.structured_json) === mineStatus)
    .filter((item) => !mineUrgent || isUrgent(item))
    .filter((item) => mineSort === "recommend" || mineSort === "latest" || (mineSort === "opening"
      ? applyState(item.notice.structured_json) === "upcoming"
      : deadlineOf(item) >= todayIso))
    .sort((a, b) => {
      if (mineSort === "deadline") return deadlineOf(a).localeCompare(deadlineOf(b));
      if (mineSort === "roomy") return deadlineOf(b).localeCompare(deadlineOf(a));
      if (mineSort === "opening") return (a.notice.structured_json?.open_at ?? "").localeCompare(b.notice.structured_json?.open_at ?? "");
      return 0;
    });

  return (
    <div className="app-shell">
      <TopBar unread={unread} />

      <main className="workspace">
        {isOffline && (
          <div className="notice-banner" role="alert">
            <CircleAlert size={16} />
            <span>서버에 연결하지 못했어요 · {apiBaseForDisplay()}</span>
            <button type="button" onClick={() => void feed.reload()}>다시 시도</button>
          </div>
        )}

        <FeedControls
          view={feed.view}
          onView={feed.chooseView}
          tabCounts={{
            mine: matched.length,
            school: sum(stats.categories_by_origin.school),
            external: sum(stats.categories_by_origin.external),
          }}
          search={feed.search}
          onSearch={feed.setSearch}
          counts={counts}
          category={feed.category}
          onCategory={feed.setCategory}
          urgentCount={mine ? matched.filter(isUrgent).length : stats.urgent_by_origin[external ? "external" : "school"]}
          urgentOnly={mine ? mineUrgent : feed.due === "urgent"}
          onUrgent={(on) => (mine ? setMineUrgent(on) : feed.setDue(on ? "urgent" : null))}
          status={mine ? mineStatus : feed.status}
          onStatus={(next) => (mine ? setMineStatus(next) : feed.setStatus(next))}
          statusCounts={mine ? mineCounts : stats.status_by_origin?.[external ? "external" : "school"] ?? { open: 0, upcoming: 0 }}
          sort={mine ? mineSort : feed.sort}
          onSort={(next) => (mine ? setMineSort(next) : feed.setSort(next as NoticeQuery["sort"]))}
        />

        {feed.view === "mine" ? (
          !profileLoaded ? null : unset ? (
            <div className="empty">
              <p>학과와 관심사를 알려주시면 나에게 해당되는 공지만 모아 드려요.</p>
              <button type="button" className="button-primary" onClick={() => setOnboarding(true)}>30초 설정하기</button>
            </div>
          ) : matched.length === 0 ? (
            <div className="empty"><p>지금은 나에게 해당되는 공지가 없어요. 새 공지가 오면 알려 드릴게요.</p></div>
          ) : mineList.length === 0 ? (
            <div className="empty"><p>조건에 맞는 공지가 없어요.</p></div>
          ) : (
            <ul className="rows">
              {mineList.map((item) => (
                <NoticeRow
                  key={item.notice.id}
                  notice={item.notice}
                  reason={item.relevance_reason}
                  onOpen={detail.open}
                  saved={saved.isSaved(item.notice.id)}
                  onToggleSave={() => saved.toggle(item.notice.id)}
                />
              ))}
            </ul>
          )
        ) : !feed.loadedOnce && !isOffline ? (
          <ul className="rows" aria-hidden="true">
            {Array.from({ length: SKELETON_ROWS }, (_, index) => <li className="row skeleton" key={index} />)}
          </ul>
        ) : feed.notices.length === 0 && !feed.isLoading ? (
          <div className="empty"><p>조건에 맞는 공지가 없어요.</p></div>
        ) : (
          <>
            <ul className={`rows ${feed.isLoading ? "is-loading" : ""}`} aria-busy={feed.isLoading}>
              {feed.notices.map((notice) => (
                <NoticeRow
                  key={notice.id}
                  notice={notice}
                  onOpen={detail.open}
                  saved={saved.isSaved(notice.id)}
                  onToggleSave={() => saved.toggle(notice.id)}
                />
              ))}
            </ul>
            <div className="list-foot">
              {feed.hasMore && (
                <button type="button" className="button-ghost" onClick={feed.loadMore} disabled={feed.isLoading}>
                  더 보기 <span>{feed.notices.length}/{feed.total}</span>
                </button>
              )}
              {!feed.hasMore && feed.sort === "latest" && feed.hideClosed && (
                <button type="button" className="text-button" onClick={() => feed.setHideClosed(false)}>마감 지난 공지도 보기</button>
              )}
            </div>
          </>
        )}
      </main>

      {onboarding && !detail.selected && (
        <Onboarding profile={profile} deviceId={deviceId} onDone={finishOnboarding} onClose={closeOnboarding} />
      )}

      {detail.selected && (
        <NoticeDetail
          notice={detail.selected}
          onClose={detail.close}
          saved={saved.isSaved(detail.selected.id)}
          onToggleSave={() => detail.selected && saved.toggle(detail.selected.id)}
        />
      )}
    </div>
  );
}
