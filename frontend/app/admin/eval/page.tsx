"use client";

import { ArrowLeft, Check, ClipboardCheck, ExternalLink, LoaderCircle, RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { fetchEvalItems, fetchEvalReport, saveEvalLabel } from "@/lib/api";
import type { EvalItem, EvalReport } from "@/lib/types";

const CATEGORIES = ["학사", "장학", "취업", "행사", "경진대회", "자격증", "연구실", "안전", "기타"];
// 관리자 키는 탭을 닫으면 사라지는 세션 저장소에만 둔다(새로고침할 때 다시 입력하지 않도록).
const KEY_STORAGE = "scnu-admin-key";

// 입력: 0~1 비율 또는 null, 출력: "83.3%" 형태 문자열.
function percent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

// 입력 없음, 출력: 공지마다 정답(분류·마감일)을 확인하고 현재 분류기를 채점하는 관리자 화면.
export default function EvalPage() {
  const [key, setKey] = useState("");
  const [items, setItems] = useState<EvalItem[]>([]);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [onlyTodo, setOnlyTodo] = useState(true);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("관리자 키를 입력하면 정답 입력을 시작할 수 있어요.");

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(KEY_STORAGE);
      if (stored) {
        setKey(stored);
        void load(stored);
      }
    } catch {
      // 저장소를 못 쓰면 매번 입력하면 된다.
    }
  }, []);

  // 입력: 관리자 키, 출력 없음; 정답 입력 목록과 채점 결과를 불러온다.
  async function load(adminKey = key) {
    setLoading(true);
    try {
      const [nextItems, nextReport] = await Promise.all([fetchEvalItems(adminKey), fetchEvalReport(adminKey)]);
      setItems(nextItems);
      setReport(nextReport);
      setMessage("");
      try {
        sessionStorage.setItem(KEY_STORAGE, adminKey);
      } catch {
        // 무시: 다음 방문 때 다시 입력.
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await load();
  }

  // 입력: 공지 ID·정답(없으면 삭제), 출력 없음; 저장 후 목록 표시만 갱신한다(채점은 버튼으로 다시).
  async function save(noticeId: number, label: { category: string; deadline: string | null } | null) {
    try {
      await saveEvalLabel(key, noticeId, label);
      setItems((current) =>
        current.map((item) =>
          item.notice_id === noticeId
            ? { ...item, labeled: Boolean(label), gold_category: label?.category ?? null, gold_deadline: label?.deadline ?? null }
            : item,
        ),
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "저장하지 못했어요.");
    }
  }

  async function rescore() {
    setLoading(true);
    try {
      setReport(await fetchEvalReport(key));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "채점하지 못했어요.");
    } finally {
      setLoading(false);
    }
  }

  const done = items.filter((item) => item.labeled).length;
  const shown = onlyTodo ? items.filter((item) => !item.labeled) : items;

  return (
    <main className="admin-page eval-page">
      <div className="admin-top"><Link href="/admin"><ArrowLeft size={18} /> 수집 관리</Link><span>SCNU LENS / EVAL</span></div>
      <section className="admin-hero">
        <div className="admin-icon"><ClipboardCheck /></div>
        <div>
          <p className="eyebrow">ACCURACY CHECK</p>
          <h1>분류 정확도 채점</h1>
          <p>공지마다 정답 분류와 마감일을 확인해 두면, 규칙을 고칠 때마다 같은 정답지로 몇 점인지 바로 비교할 수 있어요.</p>
        </div>
      </section>

      <form className="admin-key-form" onSubmit={connect}>
        <label>관리자 API 키<input type="password" value={key} onChange={(event) => setKey(event.target.value)} placeholder="ADMIN_API_KEY" /></label>
        <button type="submit" disabled={!key || loading}>{loading ? <LoaderCircle className="spin" size={18} /> : <RefreshCw size={18} />} 불러오기</button>
      </form>
      {message && <div className="admin-message">{message}</div>}

      {report && (
        <section className="eval-report">
          <div className="section-heading">
            <div><p>REPORT · {report.mode}</p><h2>정답 {report.labeled}건 기준 채점</h2></div>
            <button className="run-button" type="button" onClick={() => void rescore()} disabled={loading}><RefreshCw size={16} /> 다시 채점</button>
          </div>
          <div className="eval-metrics">
            <div><span>분류 정확도</span><strong>{percent(report.category_accuracy)}</strong></div>
            <div><span>마감일 정확도</span><strong>{percent(report.deadline_accuracy)}</strong></div>
            <div><span>마감일 정밀도</span><strong>{percent(report.deadline_precision)}</strong><small>알린 마감 중 맞은 비율</small></div>
            <div><span>마감일 재현율</span><strong>{percent(report.deadline_recall)}</strong><small>실제 마감 중 찾은 비율</small></div>
          </div>
          {Object.keys(report.per_category).length > 0 && (
            <p className="eval-per-category">
              {Object.entries(report.per_category).map(([name, value]) => (
                <span key={name}>{name} {percent(value.accuracy)} <small>({value.total})</small></span>
              ))}
            </p>
          )}
          {report.errors.length > 0 && (
            <details className="eval-errors">
              <summary>틀린 사례 {report.errors.length}건</summary>
              <ul>
                {report.errors.map((error, index) => (
                  <li key={`${error.notice_id}-${error.field}-${index}`}>
                    <b>{error.field}</b> {error.title} — 정답 <em>{error.gold}</em> / 예측 <em>{error.predicted}</em>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}

      {items.length > 0 && (
        <section className="source-section">
          <div className="section-heading">
            <div><p>LABELING · {done}/{items.length}</p><h2>정답 입력</h2></div>
            <label className="eval-filter">
              <input type="checkbox" checked={onlyTodo} onChange={(event) => setOnlyTodo(event.target.checked)} /> 아직 안 한 것만
            </label>
          </div>
          {shown.length === 0 ? (
            <div className="admin-empty">모두 입력했어요. 위의 “다시 채점”을 눌러 결과를 확인하세요.</div>
          ) : (
            <div className="eval-list">
              {shown.map((item) => <EvalRow key={item.notice_id} item={item} onSave={save} />)}
            </div>
          )}
        </section>
      )}
    </main>
  );
}

type RowProps = {
  item: EvalItem;
  onSave: (noticeId: number, label: { category: string; deadline: string | null } | null) => Promise<void>;
};

// 입력: 공지 한 건·저장 함수, 출력: 예측을 그대로 인정하거나 고쳐서 저장하는 한 줄.
function EvalRow({ item, onSave }: RowProps) {
  const [category, setCategory] = useState(item.gold_category ?? item.predicted_category);
  const initialDeadline = item.labeled ? item.gold_deadline : item.predicted_deadline;
  const [deadline, setDeadline] = useState(initialDeadline ?? "");
  const [noDeadline, setNoDeadline] = useState(!initialDeadline);
  const [busy, setBusy] = useState(false);

  async function run(label: { category: string; deadline: string | null } | null) {
    setBusy(true);
    await onSave(item.notice_id, label);
    setBusy(false);
  }

  return (
    <article className={`eval-row ${item.labeled ? "done" : ""}`}>
      <div className="eval-title">
        <a href={item.source_url} target="_blank" rel="noreferrer">{item.title} <ExternalLink size={13} /></a>
        <span>{item.source} · 예측: {item.predicted_category} / 마감 {item.predicted_deadline ?? "없음"}</span>
      </div>
      <div className="eval-controls">
        <select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="정답 분류">
          {CATEGORIES.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        <input type="date" value={deadline} disabled={noDeadline} onChange={(event) => setDeadline(event.target.value)} aria-label="정답 마감일" />
        <label><input type="checkbox" checked={noDeadline} onChange={(event) => setNoDeadline(event.target.checked)} /> 마감 없음</label>
        {!item.labeled && (
          <button type="button" disabled={busy} onClick={() => void run({ category: item.predicted_category, deadline: item.predicted_deadline })}>
            <Check size={15} /> 예측이 맞음
          </button>
        )}
        <button type="button" className="primary" disabled={busy || (!noDeadline && !deadline)} onClick={() => void run({ category, deadline: noDeadline ? null : deadline })}>
          {item.labeled ? "고쳐서 저장" : "이대로 저장"}
        </button>
        {item.labeled && (
          <button type="button" disabled={busy} onClick={() => void run(null)} aria-label="정답 삭제"><Trash2 size={15} /></button>
        )}
      </div>
    </article>
  );
}
