import { BellRing, CalendarClock, CalendarPlus, ExternalLink, Share2, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { CategoryTag } from "@/components/category-tag";
import { SaveButton } from "@/components/feed/save-button";
import { noticeCalendarUrl } from "@/lib/api";
import { alarmPlan, applyPeriod, applyStatus, deadlineLabel, formatDate } from "@/lib/notice-format";
import type { Notice } from "@/lib/types";

type Props = { notice: Notice; onClose: () => void; saved: boolean; onToggleSave: () => void };

// 주소(1) · 메일(2) · 전화번호(3). 메일·전화는 괄호나 조사("…@scnu.ac.kr)로")가 붙어도 주소만 잡는다.
const LINK_RE = /(https?:\/\/[^\s\]\)]+)|([\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})|(0\d{1,2}[-)\s]?\d{3,4}-\d{4})/g;

// 입력: 칸 값, 출력: 안에 든 주소(신청 폼 등)·메일·전화번호를 바로 누를 수 있는 링크로 바꾼 내용.
// 메일은 메일 앱, 전화번호는 전화 앱으로 열리고, 휴대폰에서 중간에 줄바꿈되지 않게 한 덩어리로 둔다.
function Linkified({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(LINK_RE)) {
    const [whole, url, mail, phone] = match;
    const at = match.index ?? 0;
    if (at > last) parts.push(text.slice(last, at));
    if (url) parts.push(<a key={at} href={url} target="_blank" rel="noreferrer">{url}</a>);
    else if (mail) parts.push(<a key={at} className="nowrap" href={`mailto:${mail}`}>{mail}</a>);
    else if (phone) parts.push(<a key={at} className="nowrap" href={`tel:${phone.replace(/[^\d]/g, "")}`}>{phone}</a>);
    last = at + whole.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

// 입력: 원문 주소, 출력: 원문 버튼 문구(학교 공지가 아닌데 "학교 원문"이라고 하지 않게).
function originLabel(url: string): string {
  if (url.includes("q-net.or.kr")) return "큐넷 시험일정에서 확인";
  if (url.includes("k-startup.go.kr")) return "K-Startup 공고에서 확인";
  if (url.includes("dataq.or.kr")) return "데이터자격검정에서 확인";
  if (url.includes("scnu.ac.kr")) return "학교 원문에서 확인";
  return "원문에서 확인";
}

// 입력: 선택된 공지·닫기 동작·저장 상태, 출력: 정해진 칸(대상·기간·신청방법…)과 원문·캘린더 버튼이 있는 상세 창.
export function NoticeDetail({ notice, onClose, saved, onToggleSave }: Props) {
  const deadline = deadlineLabel(notice.structured_json?.deadline);
  const status = applyStatus(notice.structured_json);
  const period = applyPeriod(notice.structured_json);
  const brief = notice.structured_json?.brief || [];
  const found = brief.filter((field) => field.found);
  const missing = brief.filter((field) => !field.found);
  const [shared, setShared] = useState(false);
  const plan = alarmPlan(notice);

  // 입력: 공지, 출력 없음; 휴대폰 공유 시트(카톡 등)를 열고, 없으면 링크를 복사한다.
  // 링크는 앱 안 상세 창으로 열리므로 받은 사람도 정리된 칸을 먼저 본다.
  async function share(target: Notice) {
    const url = `${window.location.origin}/?notice=${target.id}`;
    try {
      if (navigator.share) {
        await navigator.share({ title: target.title, text: `[${target.category}] ${target.title}`, url });
        return;
      }
      await navigator.clipboard.writeText(url);
      setShared(true);
      window.setTimeout(() => setShared(false), 2000);
    } catch {
      // 사용자가 공유 시트를 닫은 경우 등은 조용히 넘어간다.
    }
  }
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <article className="detail-modal" role="dialog" aria-modal="true" aria-labelledby="notice-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="닫기"><X /></button>
        <div className="detail-tags">
          <CategoryTag category={notice.category} />
          <SaveButton saved={saved} onToggle={onToggleSave} />
          <button className="save-star" type="button" onClick={() => void share(notice)} aria-label="공유하기" title="친구에게 공유">
            <Share2 size={18} />
          </button>
          {shared && <span className="share-toast">링크를 복사했어요</span>}
        </div>
        <h2 id="notice-title">{notice.title}</h2>
        <div className="detail-meta">
          <span>{notice.source}</span>
          {/* 시험 일정·교외 장학금은 게시일이 없다. "날짜 미상"을 띄우지 않고 뺀다. */}
          {notice.published_at && <span>{formatDate(notice.published_at)}</span>}
          {status && <span className={`detail-deadline ${status.tone}`}><CalendarClock size={13} /> {status.text}</span>}
          {period && <span>신청 {period}</span>}
        </div>
        {notice.also_in && notice.also_in.length > 0 && (
          <p className="also-in">같은 공지가 {notice.also_in.join(", ")}에도 올라왔어요.</p>
        )}
        {brief.length ? (
          <dl className="brief-list">
            {found.map((field) => (
              <div className="brief-row" key={field.label}>
                <dt>{field.label}</dt>
                <dd><Linkified text={field.value} /></dd>
              </div>
            ))}
            {/* 못 찾은 칸마다 같은 문구를 반복하지 않고 한 줄로 모은다. */}
            {missing.length > 0 && (
              <div className="brief-row unknown">
                <dt>그 외</dt>
                <dd>{missing.map((field) => field.label).join(" · ")} 정보는 원문에서 확인해 주세요</dd>
              </div>
            )}
          </dl>
        ) : (
          <p className="brief-empty">정리된 정보가 아직 없어요. 원문에서 확인해 주세요.</p>
        )}
        {plan.length > 0 && (
          <section className="alarm-plan">
            <h3><BellRing size={15} /> 알림 예정</h3>
            <ul>
              {plan.slice(0, 6).map((item) => (
                <li key={`${item.when}-${item.label}`}><span>{item.when}</span>{item.label}</li>
              ))}
            </ul>
            <p>{saved ? "저장한 공지라 이 시각에 알려드려요." : "별표로 저장하면 이 시각에 알려드려요. 나에게 해당되는 공지는 저장하지 않아도 알려드려요."}</p>
          </section>
        )}
        <div className="detail-actions">
          {notice.structured_json?.deadline && deadline !== "마감됨" && (
            <a className="secondary-link" href={noticeCalendarUrl(notice.id)} download>
              <CalendarPlus size={16} /> 캘린더에 마감 추가
            </a>
          )}
          <a className="primary-link" href={notice.source_url} target="_blank" rel="noreferrer">
            {originLabel(notice.source_url)} <ExternalLink size={16} />
          </a>
        </div>
      </article>
    </div>
  );
}
