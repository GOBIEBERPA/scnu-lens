"use client";

import { Download, Share, X } from "lucide-react";
import { useEffect, useState } from "react";

// 닫은 뒤 다시 보여주지 않을 기간. 기기별 편의 설정이라 브라우저 저장소에만 둔다.
const DISMISS_KEY = "scnu-install-hint-dismissed-at";
const DISMISS_DAYS = 14;

type InstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

// 입력 없음, 출력: 이미 홈 화면 앱으로 실행 중인지 여부.
function isStandalone(): boolean {
  const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return iosStandalone || window.matchMedia("(display-mode: standalone)").matches;
}

// 입력 없음, 출력: 아이폰·아이패드 여부(데스크톱 모드 아이패드는 터치 지원 Mac으로 보인다).
function isIos(): boolean {
  const ua = navigator.userAgent;
  return /iphone|ipad|ipod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

// 입력 없음, 출력: 최근에 사용자가 배너를 닫았는지 여부. 저장소를 못 쓰면 닫지 않은 것으로 본다.
function recentlyDismissed(): boolean {
  try {
    const at = Number(localStorage.getItem(DISMISS_KEY) || 0);
    return Date.now() - at < DISMISS_DAYS * 86_400_000;
  } catch {
    return false;
  }
}

// 입력 없음, 출력: 홈 화면 설치 안내. 아이폰은 홈 화면에 추가해야만 푸시 알림이 오므로 방법을 알려준다.
export function InstallHint() {
  const [mode, setMode] = useState<"ios" | "android" | null>(null);
  const [installEvent, setInstallEvent] = useState<InstallPromptEvent | null>(null);

  useEffect(() => {
    if (isStandalone() || recentlyDismissed()) return;
    if (isIos()) {
      setMode("ios");
      return;
    }
    // 안드로이드 크롬은 설치 가능할 때 이 이벤트를 준다. 받아 뒀다가 버튼을 누를 때 띄운다.
    const onPrompt = (event: Event) => {
      event.preventDefault();
      setInstallEvent(event as InstallPromptEvent);
      setMode("android");
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  function dismiss() {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      // 저장소를 못 쓰면 이번 방문 동안만 숨긴다.
    }
    setMode(null);
  }

  async function install() {
    if (!installEvent) return;
    await installEvent.prompt();
    await installEvent.userChoice.catch(() => undefined);
    setMode(null);
  }

  if (!mode) return null;
  return (
    <div className="install-hint" role="note">
      {mode === "ios" ? (
        <p>
          <strong>아이폰은 홈 화면에 추가해야 알림을 받을 수 있어요.</strong>
          <span>사파리 아래쪽 <Share size={14} aria-label="공유" /> 공유 → <b>홈 화면에 추가</b> → 추가한 아이콘으로 열어 알림을 켜 주세요.</span>
        </p>
      ) : (
        <p>
          <strong>앱으로 설치하면 알림과 바로가기가 편해져요.</strong>
          <button type="button" onClick={() => void install()}><Download size={15} /> 앱으로 설치</button>
        </p>
      )}
      <button className="install-close" type="button" onClick={dismiss} aria-label="안내 닫기"><X size={16} /></button>
    </div>
  );
}
