import { fetchPushKey, removePushSubscription, savePushSubscription } from "@/lib/api";

// 입력: base64url 문자열, 출력: 구독 API가 요구하는 바이트 배열.
function toBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

// 입력 없음, 출력: 이 브라우저가 웹 푸시를 지원하는지 여부.
export function pushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window;
}

// 입력 없음, 출력: 현재 알림 권한 상태.
export function pushPermission(): NotificationPermission | "unsupported" {
  return pushSupported() ? Notification.permission : "unsupported";
}

// 입력: 기기 ID, 출력: 구독 성공 여부; 권한 요청부터 서버 등록까지 처리한다.
export async function enablePush(deviceId: string): Promise<boolean> {
  if (!pushSupported()) return false;
  const { enabled, public_key } = await fetchPushKey();
  if (!enabled || !public_key) return false;
  if ((await Notification.requestPermission()) !== "granted") return false;

  const registration = await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  const subscription =
    existing ??
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: toBytes(public_key),
    }));
  await savePushSubscription(deviceId, subscription.toJSON());
  return true;
}

// 입력: 기기 ID, 출력 없음; 브라우저와 서버 양쪽의 구독을 해지한다.
export async function disablePush(deviceId: string): Promise<void> {
  if (pushSupported()) {
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    if (subscription) await subscription.unsubscribe();
  }
  await removePushSubscription(deviceId);
}
