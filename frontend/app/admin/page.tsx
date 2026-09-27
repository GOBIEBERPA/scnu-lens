"use client";

import { ArrowLeft, Database, LoaderCircle, Play, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";

import { fetchSources, runCrawl, toggleSource } from "@/lib/api";

type Source = Awaited<ReturnType<typeof fetchSources>>[number];

// 입력: 소스, 출력: "3시간 전 · 2건" 또는 "오류: …" 형태의 마지막 수집 결과 문구.
function crawlStatus(source: Source): string {
  if (!source.last_crawled_at) return "아직 수집 전";
  // 서버는 UTC를 시간대 표기 없이 저장하므로 Z를 붙여 해석한다.
  const minutes = Math.round((Date.now() - new Date(`${source.last_crawled_at}Z`).getTime()) / 60_000);
  const when = minutes < 60 ? `${Math.max(minutes, 0)}분 전` : minutes < 1440 ? `${Math.round(minutes / 60)}시간 전` : `${Math.round(minutes / 1440)}일 전`;
  return source.last_error ? `${when} · 오류: ${source.last_error}` : `${when} · 최근 ${source.last_fetched ?? 0}건`;
}

// 입력 없음, 출력: 관리자 키로 소스 상태와 수동 배치를 다루는 최소 관리 화면.
export default function AdminPage() {
  const [key, setKey] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("관리자 키를 입력하면 등록된 수집 소스를 확인할 수 있어요.");

  // 입력: 인증 폼 제출, 출력 없음; 관리자 키로 크롤러 소스를 불러온다.
  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    try {
      setSources(await fetchSources(key));
      setMessage("소스 연결이 완료됐어요.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "연결하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  // 입력: 소스 레코드, 출력 없음; 활성 상태를 반전하고 성공 결과를 화면에 반영한다.
  async function changeSource(source: Source) {
    try {
      await toggleSource(key, source.id, !source.is_active);
      setSources((current) => current.map((item) => item.id === source.id ? { ...item, is_active: !item.is_active } : item));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "소스를 변경하지 못했습니다.");
    }
  }

  // 입력 없음, 출력 없음; 크롤링부터 브리핑 발송까지 전체 배치를 수동 실행한다.
  async function executePipeline() {
    setLoading(true);
    setMessage("공지 수집과 AI 구조화를 실행하고 있어요…");
    try {
      const result = await runCrawl(key);
      setMessage(`완료: ${result.fetched}건 수집 · ${result.inserted}건 신규 · ${result.structured}건 구조화 · ${result.sent}건 발송 · 오류 ${result.errors.length}곳`);
      setSources(await fetchSources(key));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "배치를 실행하지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="admin-page">
      <div className="admin-top"><Link href="/"><ArrowLeft size={18} /> 대시보드</Link><Link href="/admin/eval">정확도 채점 →</Link></div>
      <section className="admin-hero">
        <div className="admin-icon"><ShieldCheck /></div>
        <div><p className="eyebrow">PIPELINE CONTROL</p><h1>공지 수집 관리</h1><p>공식 게시판 연결 상태를 확인하고 필요할 때 전체 파이프라인을 다시 실행합니다.</p></div>
      </section>
      <form className="admin-key-form" onSubmit={connect}>
        <label>관리자 API 키<input type="password" value={key} onChange={(event) => setKey(event.target.value)} placeholder="ADMIN_API_KEY" /></label>
        <button type="submit" disabled={!key || loading}>{loading ? <LoaderCircle className="spin" size={18} /> : <Database size={18} />} 소스 연결</button>
      </form>
      <div className="admin-message"><RefreshCw size={16} className={loading ? "spin" : ""} /> {message}</div>
      <section className="source-section">
        <div className="section-heading"><div><p>CRAWLER SOURCES</p><h2>수집 소스</h2></div>{sources.length > 0 && <button className="run-button" type="button" onClick={executePipeline} disabled={loading}><Play size={17} /> 지금 전체 실행</button>}</div>
        {sources.length > 0 && (
          <p className="source-summary">
            전체 {sources.length}곳 · 켜짐 {sources.filter((s) => s.is_active).length}곳 ·{" "}
            <strong className={sources.some((s) => s.last_error) ? "has-error" : ""}>오류 {sources.filter((s) => s.last_error).length}곳</strong>
          </p>
        )}
        {sources.length === 0 ? <div className="admin-empty">연결 후 공식 공지 소스가 여기에 표시됩니다.</div> : (
          <div className="source-list">
            {/* 오류 난 게시판을 맨 위로 올려 바로 보이게 한다. */}
            {[...sources].sort((a, b) => Number(Boolean(b.last_error)) - Number(Boolean(a.last_error))).map((source) => (
              <article key={source.id}>
                <div>
                  <span className="category-tag tag-gray">{source.category_hint}</span><h3>{source.name}</h3><p>{source.url}</p>
                  <p className={`source-status ${source.last_error ? "has-error" : ""}`}>{crawlStatus(source)}</p>
                </div>
                <button className={`toggle ${source.is_active ? "on" : ""}`} type="button" onClick={() => changeSource(source)} aria-label={`${source.name} ${source.is_active ? "비활성화" : "활성화"}`}><i /></button>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

