"use client";

import { useEffect, useState } from "react";

import { fetchNotice, fetchNotices, fetchSavedNotices, fetchUnreadCount, setNoticeSaved, type NoticeQuery } from "@/lib/api";
import { disablePush, enablePush, pushPermission, pushSupported } from "@/lib/push";
import type { Notice } from "@/lib/types";

// 목록 탭. mine은 "나에게 해당되는 공지"(추천), school·external은 공지 목록 API의 출처다.
export type FeedView = "mine" | "school" | "external";

// 한 번에 더 불러오는 공지 수.
const PAGE_SIZE = 20;

// 입력 없음, 출력: 공지 목록과 탭·분야·검색·정렬 상태, "더 보기", 불러오기 오류.
// 실패하면 가짜 데모 공지로 덮지 않고, 마지막으로 받은 목록을 둔 채 오류를 드러낸다.
export function useNoticeFeed() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [view, setView] = useState<FeedView>("school");
  const [category, setCategory] = useState("전체");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<NoticeQuery["sort"]>("latest");
  const [due, setDue] = useState<NoticeQuery["due"]>(null);
  const [status, setStatus] = useState<NoticeQuery["status"]>(null);
  // 기본으로 마감 지난 공지는 숨긴다(지금 할 수 있는 것만 보이게). 목록 끝에서 켤 수 있다.
  const [hideClosed, setHideClosed] = useState(true);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  // 첫 응답이 오기 전에는 빈 목록 대신 자리 표시 줄을 보여준다.
  const [loadedOnce, setLoadedOnce] = useState(false);
  // 저장해 둔 탭·필터를 되살린 뒤에 첫 요청을 보낸다(기본값으로 한 번 불렀다가 다시 부르지 않게).
  const [restored, setRestored] = useState(false);
  // 한 번이라도 저장된 탭이 있었는지. 없으면 대시보드가 추천 유무를 보고 첫 탭을 정한다.
  const [hadSavedView, setHadSavedView] = useState(false);

  // 마이페이지·캘린더에 다녀와도 보던 탭·필터가 유지되도록, 탭을 닫기 전까지 세션 저장소에 둔다.
  useEffect(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(FILTER_KEY) || "{}") as Partial<SavedFilters>;
      if (saved.view) {
        setView(saved.view);
        setHadSavedView(true);
      }
      if (saved.category) setCategory(saved.category);
      if (saved.sort) setSort(saved.sort);
    } catch {
      // 저장소를 못 쓰면 기본값으로 둔다.
    }
    setRestored(true);
  }, []);

  useEffect(() => {
    if (!restored) return;
    try {
      const value: SavedFilters = { view, category, sort };
      sessionStorage.setItem(FILTER_KEY, JSON.stringify(value));
    } catch {
      // 무시: 다음 방문 때 기본값.
    }
  }, [restored, view, category, sort]);

  // 입력: 탭, 출력 없음; 탭을 바꾸면 분야·빠른 필터는 풀고, 정렬은 그 탭에 맞는 기본으로 바꾼다.
  // 공모전·시험 일정은 게시일이 없어 최신순이 의미가 없으므로 마감순으로 본다.
  function chooseView(next: FeedView) {
    setView(next);
    setCategory("전체");
    setDue(null);
    setStatus(null);
    setHideClosed(true);
    setSort(next === "external" ? "deadline" : "latest");
  }

  // 입력 없음, 출력 없음; 현재 조건으로 page 쪽을 불러온다. 첫 쪽이면 바꾸고, 다음 쪽이면 이어 붙인다.
  async function reload() {
    if (view === "mine") return;
    setIsLoading(true);
    try {
      const data = await fetchNotices({ category, search, page, perPage: PAGE_SIZE, sort, due, origin: view, hideClosed, status });
      setNotices((current) => (page === 1 ? data.items : [...current, ...data.items]));
      setTotal(data.total);
      setLoadError("");
      setLoadedOnce(true);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "알 수 없는 오류");
    } finally {
      setIsLoading(false);
    }
  }

  // 검색어는 입력 중 과도한 호출을 막기 위해 300ms 디바운스한다.
  useEffect(() => {
    if (!restored) return;
    const timer = window.setTimeout(() => void reload(), page === 1 ? 300 : 0);
    return () => window.clearTimeout(timer);
  }, [restored, view, category, search, page, sort, due, hideClosed, status]);

  // 조건이 바뀌면 첫 쪽부터 다시 본다.
  useEffect(() => {
    setPage(1);
  }, [view, category, search, sort, due, hideClosed, status]);

  const hasMore = notices.length < total;

  return {
    notices, view, chooseView, hadSavedView, category, setCategory, search, setSearch, sort, setSort, due, setDue, status, setStatus,
    hideClosed, setHideClosed, total, hasMore, loadMore: () => setPage((current) => current + 1),
    isLoading, loadedOnce, loadError, reload,
  };
}

const FILTER_KEY = "scnu-feed-view";
type SavedFilters = { view: FeedView; category: string; sort: NoticeQuery["sort"] };

// 입력 없음, 출력: 선택된 공지와 열기·닫기 함수.
// 상세 창을 열 때 기록을 하나 쌓아 두면, 휴대폰 뒤로가기가 페이지 이동 대신 창을 닫는다.
export function useNoticeDetail() {
  const [selected, setSelected] = useState<Notice | null>(null);

  useEffect(() => {
    const onBack = () => setSelected(null);
    window.addEventListener("popstate", onBack);
    return () => window.removeEventListener("popstate", onBack);
  }, []);

  // 알림·공유 링크(/?notice=12)로 들어오면 그 공지를 바로 연다.
  // 주소를 먼저 "/"로 바꿔 두어야 창을 닫았을 때 같은 공지가 다시 열리지 않는다.
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("notice"));
    if (!id) return;
    window.history.replaceState(null, "", window.location.pathname);
    void fetchNotice(id).then(open).catch(() => undefined);
  }, []);

  function open(notice: Notice) {
    setSelected(notice);
    window.history.pushState({ scnuDetail: true }, "");
  }

  // X·바깥 클릭으로 닫을 때도 쌓아 둔 기록을 함께 되돌린다.
  function close() {
    if (window.history.state?.scnuDetail) window.history.back();
    else setSelected(null);
  }

  return { selected, open, close };
}

// 입력: 기기 ID, 출력: 저장한 공지 ID 집합과 저장/해제 전환 함수.
// 누르자마자 별을 바꾸고, 서버가 실패하면 원래대로 되돌린다.
export function useSavedNotices(deviceId: string) {
  const [savedIds, setSavedIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!deviceId) return;
    void fetchSavedNotices(deviceId)
      .then((items) => setSavedIds(new Set(items.map((item) => item.id))))
      .catch(() => undefined);
  }, [deviceId]);

  async function toggle(noticeId: number) {
    const next = !savedIds.has(noticeId);
    const previous = savedIds;
    setSavedIds((current) => {
      const copy = new Set(current);
      if (next) copy.add(noticeId);
      else copy.delete(noticeId);
      return copy;
    });
    try {
      setSavedIds(new Set(await setNoticeSaved(noticeId, deviceId, next)));
    } catch {
      setSavedIds(previous);
    }
  }

  return { isSaved: (id: number) => savedIds.has(id), toggle: (id: number) => void toggle(id) };
}

// 입력: 기기 ID, 출력: 안 읽은 알림 수. 앱으로 돌아올 때와 1분마다 다시 센다.
export function useUnreadCount(deviceId: string) {
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    if (!deviceId) return;
    const load = () => void fetchUnreadCount(deviceId).then(setUnread).catch(() => undefined);
    // 반복 확인은 화면이 보일 때만 한다(백그라운드 탭에서 서버를 계속 부르지 않게). 처음 한 번은 무조건 센다.
    const refresh = () => {
      if (document.visibilityState === "visible") load();
    };
    load();
    const timer = window.setInterval(refresh, 60_000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [deviceId]);

  return unread;
}

// 입력: 기기 ID, 출력: 알림 지원 여부·켜짐·처리 중 상태와 전환 함수.
export function usePushToggle(deviceId: string) {
  const [on, setOn] = useState(false);
  const [busy, setBusy] = useState(false);
  // 서버 렌더에서는 브라우저 기능을 알 수 없으므로, 확인된 뒤에만 버튼을 그린다.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      setReady(pushSupported());
      setOn(pushPermission() === "granted");
    } catch {
      setReady(false);
    }
  }, []);

  async function toggle() {
    setBusy(true);
    try {
      if (on) {
        await disablePush(deviceId);
        setOn(false);
      } else {
        setOn(await enablePush(deviceId));
      }
    } catch {
      setOn(false);
    } finally {
      setBusy(false);
    }
  }

  return { ready, on, busy, toggle: () => void toggle() };
}
