"use client";

import { ArrowLeft, BellOff, BellRing, CalendarClock, CheckCheck, Clock, Megaphone, Star } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { usePushToggle } from "@/components/feed/hooks";
import { fetchInbox, fetchUpcomingAlarms, markInboxRead } from "@/lib/api";
import { getDeviceId } from "@/lib/device";
import type { InboxEntry, UpcomingAlarm } from "@/lib/types";

const KIND_ICON = { new: Megaphone, deadline: CalendarClock, time: Clock, test: BellRing } as const;
const KIND_LABEL = { new: "새 공지", deadline: "마감 알림", time: "접수 시각", test: "테스트" } as const;

// 입력: 날짜 키(YYYY-MM-DD), 출력: "오늘"·"어제"·"내일"·"9월 28일 (일)".
function dayLabel(key: string): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = new Date(`${key}T00:00:00`);
  const diff = Math.round((day.getTime() - today.getTime()) / 86_400_000);
  if (diff === 0) return "오늘";
  if (diff === -1) return "어제";
  if (diff === 1) return "내일";
  return `${day.getMonth() + 1}월 ${day.getDate()}일 (${"일월화수목금토"[day.getDay()]})`;
}

// 입력: Date, 출력: 이 기기 기준 YYYY-MM-DD.
function localKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

// 입력: 서버 시각(UTC, 시간대 표기 없음), 출력: 이 기기 시간대의 Date.
function fromServer(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
}

// 입력: 목록·날짜 키 함수, 출력: [날짜 키, 항목들] 묶음(순서 유지).
function groupBy<T>(items: T[], key: (item: T) => string): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const item of items) groups.set(key(item), [...(groups.get(key(item)) || []), item]);
  return [...groups.entries()];
}

// 입력 없음, 출력: 받은 알림(읽음/안 읽음)과 앞으로 울릴 알림을 앱 안에서 확인하는 화면.
// 휴대폰 푸시를 못 받는 사람(아이폰 미설치, 알림 거부)도 여기서 같은 알림을 본다.
export function InboxPage() {
  const router = useRouter();
  const [deviceId, setDeviceId] = useState("");
  const [tab, setTab] = useState<"received" | "upcoming">("received");
  const [items, setItems] = useState<InboxEntry[]>([]);
  const [unread, setUnread] = useState(0);
  const [upcoming, setUpcoming] = useState<UpcomingAlarm[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const push = usePushToggle(deviceId);

  useEffect(() => {
    let id = "";
    try {
      id = getDeviceId();
    } catch {
      setLoading(false);
      return;
    }
    setDeviceId(id);
    Promise.all([fetchInbox(id), fetchUpcomingAlarms(id)])
      .then(([inbox, next]) => {
        setItems(inbox.items);
        setUnread(inbox.unread);
        setUpcoming(next);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "알림을 불러오지 못했어요."))
      .finally(() => setLoading(false));
    // 앱 아이콘에 붙은 숫자 표시는 알림함을 열면 지운다(지원하는 기기만).
    const nav = navigator as Navigator & { clearAppBadge?: () => Promise<void> };
    void nav.clearAppBadge?.().catch(() => undefined);
  }, []);

  const received = useMemo(() => groupBy(items, (item) => localKey(fromServer(item.created_at))), [items]);
  const planned = useMemo(() => groupBy(upcoming, (item) => item.when.slice(0, 10)), [upcoming]);

  // 입력: 알림, 출력 없음; 읽음으로 표시하고 그 공지(또는 화면)로 이동한다.
  async function open(item: InboxEntry) {
    if (!item.read) {
      setItems((current) => current.map((entry) => (entry.id === item.id ? { ...entry, read: true } : entry)));
      setUnread((count) => Math.max(0, count - 1));
      void markInboxRead(deviceId, [item.id]).then(setUnread).catch(() => undefined);
    }
    router.push(item.url || "/");
  }

  async function readAll() {
    setItems((current) => current.map((entry) => ({ ...entry, read: true })));
    setUnread(0);
    try {
      setUnread(await markInboxRead(deviceId));
    } catch {
      // 다음에 열 때 서버 기준으로 다시 맞춰진다.
    }
  }

  return (
    <main className="inbox-page">
      <div className="admin-top">
        <Link href="/"><ArrowLeft size={18} /> 공지</Link>
        {tab === "received" && unread > 0 && (
          <button type="button" className="text-button" onClick={() => void readAll()}><CheckCheck size={16} /> 모두 읽음</button>
        )}
      </div>

      <header className="inbox-head">
        <p className="eyebrow">NOTIFICATIONS</p>
        <h1>알림함</h1>
      </header>

      {push.ready && !push.on && (
        <button type="button" className="push-banner" onClick={push.toggle} disabled={push.busy}>
          <BellOff size={18} />
          <span><strong>휴대폰 알림이 꺼져 있어요</strong><small>켜면 마감·접수 시각에 휴대폰으로도 알려드려요. 꺼져 있어도 여기에는 쌓여요.</small></span>
          <em>켜기</em>
        </button>
      )}

      <div className="segmented inbox-tabs" role="tablist" aria-label="알림 종류">
        <button type="button" role="tab" aria-selected={tab === "received"} className={tab === "received" ? "active" : ""} onClick={() => setTab("received")}>
          받은 알림{unread > 0 && <span className="badge inline">{unread}</span>}
        </button>
        <button type="button" role="tab" aria-selected={tab === "upcoming"} className={tab === "upcoming" ? "active" : ""} onClick={() => setTab("upcoming")}>
          예정된 알림{upcoming.length > 0 && <span className="chip-count">{upcoming.length}</span>}
        </button>
      </div>
      {error && <div className="admin-message">{error}</div>}

      {loading ? (
        <div className="inbox-list">{[0, 1, 2].map((index) => <div className="inbox-item skeleton" key={index} />)}</div>
      ) : tab === "received" ? (
        received.length === 0 ? (
          <div className="empty-state">
            <h3>아직 받은 알림이 없어요</h3>
            <p>나에게 해당되는 새 공지가 올라오거나 저장한 공지의 마감이 다가오면 여기로 알려드려요. 앞으로 받을 알림은 ‘예정된 알림’에서 볼 수 있어요.</p>
          </div>
        ) : (
          received.map(([day, entries]) => (
            <section className="inbox-group" key={day}>
              <h2>{dayLabel(day)}</h2>
              <ul className="inbox-list">
                {entries.map((item) => {
                  const Icon = KIND_ICON[item.kind] ?? BellRing;
                  const at = fromServer(item.created_at);
                  return (
                    <li key={item.id}>
                      <button type="button" className={`inbox-item ${item.read ? "" : "unread"} kind-${item.kind}`} onClick={() => void open(item)}>
                        <span className="inbox-icon"><Icon size={17} /></span>
                        <span className="inbox-text">
                          <span className="inbox-meta">{KIND_LABEL[item.kind] ?? "알림"} · {String(at.getHours()).padStart(2, "0")}:{String(at.getMinutes()).padStart(2, "0")}</span>
                          <strong>{item.title}</strong>
                          {item.body && <span className="inbox-body">{item.body}</span>}
                        </span>
                        {!item.read && <i className="unread-dot" aria-label="안 읽음" />}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))
        )
      ) : planned.length === 0 ? (
        <div className="empty-state">
          <h3>2주 안에 울릴 알림이 없어요</h3>
          <p>마감일이 있는 공지에 별표를 누르면 7·3·1일 전에 알려드려요.</p>
        </div>
      ) : (
        planned.map(([day, entries]) => (
          <section className="inbox-group" key={day}>
            <h2>{dayLabel(day)}</h2>
            <ul className="inbox-list">
              {entries.map((item) => (
                <li key={`${item.when}-${item.notice_id}-${item.label}`}>
                  <Link className="inbox-item planned" href={`/?notice=${item.notice_id}`}>
                    <span className="planned-time">{item.when.slice(11)}</span>
                    <span className="inbox-text">
                      <span className="inbox-meta">{item.label}{item.saved && <> · <Star size={11} fill="currentColor" /> 저장</>}</span>
                      <strong>{item.title}</strong>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </main>
  );
}
