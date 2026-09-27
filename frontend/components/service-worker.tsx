"use client";

import { useEffect } from "react";

// 입력 없음, 출력 없음; 브라우저에서만 PWA 서비스 워커를 한 번 등록한다.
export function ServiceWorkerRegistration() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return null;
}

