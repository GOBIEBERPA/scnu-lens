"use client";

import { ArrowLeft, BellOff, BellRing, Check, GraduationCap, LoaderCircle, Send, Star } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { DepartmentPicker } from "@/components/department-picker";
import { InstallHint } from "@/components/install-hint";
import {
  fetchDepartments,
  fetchMatchedNotices,
  fetchProfile,
  fetchSavedNotices,
  saveProfile,
  sendTestPush,
  setNoticeSaved,
} from "@/lib/api";
import { getDeviceId } from "@/lib/device";
import { deadlineLabel, SUGGESTED_INTERESTS } from "@/lib/notice-format";
import { disablePush, enablePush, pushPermission, pushSupported } from "@/lib/push";
import type { AlertPref, MatchedNotice, Notice, Profile } from "@/lib/types";

const ALL_CATEGORIES = ["학사", "장학", "취업", "행사", "경진대회", "자격증", "연구실", "안전", "기타"];

// 휴대폰 알림 종류. 서버(app/services/alarms.py·delivery.py)의 규칙과 같은 설명을 쓴다.
const ALERT_PREFS: { key: AlertPref; title: string; detail: string }[] = [
  { key: "new", title: "새 공지", detail: "나에게 해당되는 공지가 올라오면. 여러 건이면 하나로 묶어요." },
  { key: "deadline", title: "마감 알림", detail: "마감 7일 전 · 3일 전 · 1일 전, 오전 9시" },
  { key: "time", title: "접수 시작·마감 시각", detail: "시작 1시간·5분 전·시작, 마감 1시간·10분 전·마감 (시각이 공개된 일정만)" },
  { key: "quiet", title: "밤에는 조용히", detail: "밤 11시~아침 8시 새 공지 알림은 모았다가 아침에 보내요." },
];

// 입력: 쉼표로 적은 관심사 문자열, 출력: 공백을 정리한 관심사 목록.
function parseInterests(text: string): string[] {
  return text.split(",").map((item) => item.trim()).filter(Boolean);
}

// 입력 없음, 출력: 학과·관심사·알림 카테고리를 관리하는 마이페이지 화면.
export function MyPage() {
  const [deviceId, setDeviceId] = useState("");
  const [profile, setProfile] = useState<Profile>({
    web_device_id: "",
    display_name: "",
    department: "",
    interests: [],
    notify_categories: [],
  });
  const [interestInput, setInterestInput] = useState("");
  const [matched, setMatched] = useState<MatchedNotice[]>([]);
  const [pushReady, setPushReady] = useState(false);
  const [pushOn, setPushOn] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; reason: string } | null>(null);
  const [saved, setSaved] = useState<Notice[]>([]);
  const [departments, setDepartments] = useState<string[]>([]);
  // 저장하지 않은 변경이 있으면 아래 저장 막대를 강조한다.
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    void fetchDepartments().then(setDepartments).catch(() => setDepartments([]));
  }, []);

  // 입력: 키워드, 출력 없음; 관심 키워드 칸에 넣거나 뺀다.
  function toggleInterest(word: string) {
    const current = parseInterests(interestInput);
    const next = current.includes(word) ? current.filter((item) => item !== word) : [...current, word];
    setInterestInput(next.join(", "));
    setDirty(true);
  }

  useEffect(() => {
    const id = getDeviceId();
    setDeviceId(id);
    try {
      setPushReady(pushSupported());
      setPushOn(pushPermission() === "granted");
    } catch {
      setPushReady(false);
    }
    void (async () => {
      try {
        const saved = await fetchProfile(id);
        setProfile(saved);
        setInterestInput((saved.interests || []).join(", "));
      } catch {
        setProfile((current) => ({ ...current, web_device_id: id }));
      }
      try {
        setMatched(await fetchMatchedNotices(id));
      } catch {
        setMatched([]);
      }
      try {
        setSaved(await fetchSavedNotices(id));
      } catch {
        setSaved([]);
      }
    })();
  }, []);

  // 입력: 공지 ID, 출력 없음; 저장 목록에서 빼고 서버에도 반영한다.
  async function unsave(noticeId: number) {
    const previous = saved;
    setSaved((current) => current.filter((item) => item.id !== noticeId));
    try {
      await setNoticeSaved(noticeId, deviceId, false);
    } catch {
      setSaved(previous);
    }
  }

  // 입력: 알림 종류, 출력 없음; 켜고 끈다(저장 버튼을 눌러야 적용).
  function togglePref(key: AlertPref) {
    setDirty(true);
    setProfile((current) => ({
      ...current,
      alert_prefs: { ...(current.alert_prefs || {}), [key]: !(current.alert_prefs?.[key] ?? true) },
    }));
  }

  // 입력: 카테고리 이름, 출력 없음; 알림 수신 목록에서 켜고 끈다.
  function toggleCategory(category: string) {
    setDirty(true);
    setProfile((current) => {
      const picked = current.notify_categories || [];
      return {
        ...current,
        notify_categories: picked.includes(category)
          ? picked.filter((item) => item !== category)
          : [...picked, category],
      };
    });
  }

  // 입력: 알림 버튼 클릭, 출력 없음; 브라우저 알림 권한과 구독을 전환한다.
  async function togglePush() {
    setBusy(true);
    try {
      if (pushOn) {
        await disablePush(deviceId);
        setPushOn(false);
      } else {
        const ok = await enablePush(deviceId);
        setPushOn(ok);
        if (!ok) setStatus("브라우저에서 알림을 허용해야 받을 수 있어요.");
      }
    } finally {
      setBusy(false);
    }
  }

  // 입력: 테스트 버튼 클릭, 출력 없음; 서버가 이 기기로 실제 푸시를 보내게 하고 결과를 보여준다.
  async function runTestPush() {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await sendTestPush(deviceId));
    } catch (error) {
      setTestResult({ ok: false, reason: error instanceof Error ? error.message : "서버에 연결하지 못했어요." });
    } finally {
      setTesting(false);
    }
  }

  // 입력: 폼 제출, 출력 없음; 프로필과 알림 설정을 저장하고 매칭 결과를 갱신한다.
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setStatus("저장 중...");
    const next = {
      ...profile,
      web_device_id: deviceId,
      // 목록에서 고른 이름만 저장한다(옛 자유 입력 값은 "미설정"으로). 목록을 못 불러왔으면 기존 값을 그대로 둔다.
      department: departments.length === 0 || departments.includes(profile.department) ? profile.department : "미설정",
      interests: parseInterests(interestInput),
    };
    try {
      setProfile(await saveProfile(next));
      const nextMatched = await fetchMatchedNotices(deviceId);
      setMatched(nextMatched);
      setDirty(false);
      setStatus(`저장했어요. 나에게 해당되는 공지 ${nextMatched.length}건`);
    } catch {
      setStatus("저장하지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  const picked = profile.notify_categories || [];

  return (
    <main className="me-page">
      <div className="admin-top">
        <Link href="/"><ArrowLeft size={18} /> 대시보드</Link>
        <span>SCNU LENS / MY</span>
      </div>

      <InstallHint />

      <section className="admin-hero">
        <div className="admin-icon"><GraduationCap /></div>
        <div>
          <p className="eyebrow">MY NOTICE PROFILE</p>
          <h1>마이페이지</h1>
          <p>학과와 관심 키워드로 공지를 골라주고, 알림 받을 분야를 직접 정할 수 있어요.</p>
        </div>
      </section>

      <form className="me-form" onSubmit={submit}>
        <section className="me-card">
          <h2>내 정보</h2>
          <label>이름 또는 별명
            <input
              value={profile.display_name || ""}
              onChange={(event) => {
                setProfile({ ...profile, display_name: event.target.value });
                setDirty(true);
              }}
              placeholder="예: 순천대 새내기"
              autoComplete="nickname"
            />
          </label>
          <div className="me-field">
            <span className="me-field-label">학과</span>
            <DepartmentPicker
              value={profile.department}
              options={departments}
              onChange={(name) => {
                setProfile({ ...profile, department: name });
                setDirty(true);
              }}
            />
          </div>
          <label>관심 키워드 <span className="hint">눌러서 넣거나, 쉼표로 직접 입력</span>
            <input
              value={interestInput}
              onChange={(event) => {
                setInterestInput(event.target.value);
                setDirty(true);
              }}
              placeholder="장학금, 인턴, AI"
            />
          </label>
          <div className="interest-chips">
            {SUGGESTED_INTERESTS.map((word) => {
              const on = parseInterests(interestInput).includes(word);
              return (
                <button type="button" key={word} className={`check-chip ${on ? "on" : ""}`} aria-pressed={on} onClick={() => toggleInterest(word)}>
                  {on && <Check size={13} />} {word}
                </button>
              );
            })}
          </div>
        </section>

        <section className="me-card">
          <h2>알림 받을 분야</h2>
          <p className="me-help">
            {picked.length === 0
              ? "아무것도 고르지 않으면 모든 분야의 공지를 받아요."
              : `선택한 ${picked.length}개 분야만 알림으로 받아요.`}
          </p>
          <div className="check-grid">
            {ALL_CATEGORIES.map((category) => {
              const on = picked.includes(category);
              return (
                <button
                  className={`check-chip ${on ? "on" : ""}`}
                  type="button"
                  key={category}
                  onClick={() => toggleCategory(category)}
                  aria-pressed={on}
                >
                  <span className="check-box">{on && <Check size={13} />}</span>
                  {category}
                </button>
              );
            })}
          </div>
        </section>

        <section className="me-card">
          <h2>알림 방법</h2>
          <div className="pref-list">
            {ALERT_PREFS.map((pref) => {
              const on = profile.alert_prefs?.[pref.key] ?? true;
              return (
                <button
                  type="button"
                  key={pref.key}
                  className={`pref-row ${on ? "on" : ""}`}
                  role="switch"
                  aria-checked={on}
                  onClick={() => togglePref(pref.key)}
                >
                  <span><strong>{pref.title}</strong><small>{pref.detail}</small></span>
                  <i className="toggle-knob" aria-hidden="true" />
                </button>
              );
            })}
          </div>
          <p className="me-help small">꺼도 앱 알림함에는 그대로 쌓여요. 휴대폰으로만 울리지 않아요.</p>
          {pushReady ? (
            <button
              className={`push-row ${pushOn ? "on" : ""}`}
              type="button"
              onClick={togglePush}
              disabled={busy}
              aria-pressed={pushOn}
            >
              {pushOn ? <BellRing size={19} /> : <BellOff size={19} />}
              <span>
                <strong>휴대폰·브라우저 알림</strong>
                <small>{pushOn ? "켜짐 — 마감 임박 공지를 보내드려요" : "꺼짐 — 눌러서 켜기"}</small>
              </span>
            </button>
          ) : (
            <p className="me-help">이 브라우저는 알림을 지원하지 않아요. 홈 화면에 추가한 뒤 다시 확인해 주세요.</p>
          )}
          {pushReady && (
            <div className="push-test">
              <button type="button" onClick={runTestPush} disabled={!pushOn || testing}>
                {testing ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />} 테스트 알림 보내기
              </button>
              <p className={testResult?.ok === false ? "fail" : ""}>
                {testResult?.reason ?? (pushOn ? "서버에서 이 기기로 실제 알림을 한 번 보내봐요." : "알림을 켜면 테스트할 수 있어요.")}
              </p>
            </div>
          )}
        </section>

        <div className={`me-actions ${dirty ? "dirty" : ""}`}>
          <span>{dirty ? "바뀐 내용이 있어요. 저장해야 적용돼요." : status}</span>
          <button className="save-button" type="submit" disabled={busy}>
            {busy ? <LoaderCircle className="spin" size={17} /> : null} 저장
          </button>
        </div>
      </form>

      <section className="me-card">
        <h2>저장한 공지 {saved.length > 0 && <em>{saved.length}건</em>}</h2>
        {saved.length === 0 ? (
          <p className="me-help">공지 카드의 <Star size={13} /> 별을 누르면 여기에 모이고, 마감 3일·1일 전과 당일에 알려드려요.</p>
        ) : (
          <ul className="me-matched">
            {saved.map((notice) => {
              const deadline = deadlineLabel(notice.structured_json?.deadline);
              return (
                <li key={notice.id} className="saved-row">
                  <a href={`/?notice=${notice.id}`}>
                    <strong>{notice.title}</strong>
                    <span>{notice.source}</span>
                    {deadline && <em>{deadline}</em>}
                  </a>
                  <button type="button" onClick={() => void unsave(notice.id)} aria-label={`${notice.title} 저장 해제`}>
                    <Star size={17} fill="currentColor" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="me-card">
        <h2>나에게 해당되는 공지 {matched.length > 0 && <em>{matched.length}건</em>}</h2>
        {matched.length === 0 ? (
          <p className="me-help">아직 매칭된 공지가 없어요. 학과와 관심 키워드를 저장하면 골라드려요.</p>
        ) : (
          <ul className="me-matched">
            {matched.map((item) => (
              <li key={item.notice.id}>
                <a href={`/?notice=${item.notice.id}`}>
                  <strong>{item.notice.title}</strong>
                  <span>{item.relevance_reason}</span>
                  {item.days_left !== null && item.days_left >= 0 && (
                    <em>{item.days_left === 0 ? "오늘 마감" : `D-${item.days_left}`}</em>
                  )}
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
