const STORAGE_KEY = "scnu-lens-device";

// 입력 없음, 출력: 임의의 기기 식별자.
// crypto.randomUUID는 보안 컨텍스트(https 또는 localhost)에서만 존재한다.
// http로 접속한 휴대폰에서는 없어서 예외가 나므로 단계적으로 대체 수단을 쓴다.
function randomId(): string {
  const webCrypto = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (typeof webCrypto?.randomUUID === "function") return webCrypto.randomUUID();
  if (typeof webCrypto?.getRandomValues === "function") {
    const bytes = webCrypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }
  return `dev-${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

// 입력 없음, 출력: 브라우저에 유지되는 익명 기기 식별자.
// 시크릿 모드 등에서 localStorage가 막혀도 화면이 죽지 않도록 항상 값을 돌려준다.
export function getDeviceId(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return stored;
    const created = randomId();
    localStorage.setItem(STORAGE_KEY, created);
    return created;
  } catch {
    return randomId();
  }
}
