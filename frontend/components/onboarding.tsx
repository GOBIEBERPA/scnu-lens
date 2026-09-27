"use client";

import { BellRing, Check, LoaderCircle, X } from "lucide-react";
import { useEffect, useState } from "react";

import { DepartmentPicker } from "@/components/department-picker";
import { fetchDepartments, saveProfile } from "@/lib/api";
import { SUGGESTED_INTERESTS } from "@/lib/notice-format";
import { enablePush, pushPermission, pushSupported } from "@/lib/push";
import type { Profile } from "@/lib/types";

type Props = {
  profile: Profile;
  deviceId: string;
  onDone: (profile: Profile) => void;
  onClose: () => void;
};

// 입력: 현재 프로필·기기 ID·완료/닫기 동작, 출력: 처음 온 학생이 학과·관심사·알림을 한 화면에서 정하는 시트.
// 마이페이지의 긴 설정 화면까지 가지 않고, 저장하자마자 메인에서 "나에게 해당되는 공지"를 보게 한다.
export function Onboarding({ profile, deviceId, onDone, onClose }: Props) {
  const [department, setDepartment] = useState(profile.department === "미설정" ? "" : profile.department);
  const [interests, setInterests] = useState<string[]>(profile.interests);
  const [departments, setDepartments] = useState<string[]>([]);
  const [wantPush, setWantPush] = useState(false);
  const [canPush, setCanPush] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetchDepartments().then(setDepartments).catch(() => setDepartments([]));
    try {
      const supported = pushSupported();
      setCanPush(supported);
      setWantPush(supported && pushPermission() !== "denied");
    } catch {
      setCanPush(false);
    }
  }, []);

  function toggle(word: string) {
    setInterests((current) => (current.includes(word) ? current.filter((item) => item !== word) : [...current, word]));
  }

  // 입력 없음, 출력 없음; 프로필을 저장하고 원하면 알림 권한을 요청한 뒤 닫는다.
  async function finish() {
    setBusy(true);
    setError("");
    try {
      const saved = await saveProfile({
        ...profile,
        web_device_id: deviceId,
        // 목록에서 고른 이름만 저장한다. 그 밖의 값(옛 자유 입력 등)은 "미설정"으로 둔다.
        department: departments.includes(department) ? department : "미설정",
        interests,
      });
      // 알림 권한 창은 사용자가 버튼을 누른 이 순간에만 띄울 수 있다(브라우저 정책).
      if (wantPush && canPush) await enablePush(deviceId).catch(() => false);
      onDone(saved);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "저장하지 못했어요.");
    } finally {
      setBusy(false);
    }
  }

  const hasDepartment = departments.includes(department);
  const ready = hasDepartment || interests.length > 0;

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="detail-modal onboarding" role="dialog" aria-modal="true" aria-labelledby="onboarding-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="나중에 하기"><X /></button>
        <p className="eyebrow">30초 설정</p>
        <h2 id="onboarding-title">나에게 해당되는 공지만 골라드릴게요</h2>

        <div className="onboarding-field">
          <span>학과·전공</span>
          <DepartmentPicker value={department} options={departments} onChange={setDepartment} />
        </div>

        <div className="onboarding-field">
          <span>관심 있는 것 <small>여러 개 골라도 돼요</small></span>
          <div className="interest-chips">
            {SUGGESTED_INTERESTS.map((word) => {
              const on = interests.includes(word);
              return (
                <button type="button" key={word} className={`check-chip ${on ? "on" : ""}`} aria-pressed={on} onClick={() => toggle(word)}>
                  {on && <Check size={13} />} {word}
                </button>
              );
            })}
          </div>
        </div>

        {canPush && (
          <button type="button" className={`pref-row ${wantPush ? "on" : ""}`} role="switch" aria-checked={wantPush} onClick={() => setWantPush(!wantPush)}>
            <span>
              <strong><BellRing size={14} /> 휴대폰 알림 받기</strong>
              <small>마감 7·3·1일 전과 접수 시각에 알려드려요. 밤에는 조용히 모았다가 아침에 보내요.</small>
            </span>
            <i className="toggle-knob" aria-hidden="true" />
          </button>
        )}

        {error && <p className="onboarding-error">{error}</p>}
        {!ready && <p className="onboarding-need">학과를 고르거나 관심 있는 것을 하나 이상 눌러 주세요</p>}
        <div className="detail-actions">
          <button type="button" className="primary-link" onClick={() => void finish()} disabled={!ready || busy}>
            {busy ? <LoaderCircle className="spin" size={17} /> : null} 시작하기
          </button>
          <button type="button" className="text-button" onClick={onClose}>나중에 할게요</button>
        </div>
      </section>
    </div>
  );
}
