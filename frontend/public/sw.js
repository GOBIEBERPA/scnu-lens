// 버전을 올리면 activate에서 이전 캐시를 지우므로, 화면을 바꿀 때마다 올린다.
const CACHE_NAME = "scnu-lens-v15";
const APP_SHELL = ["/", "/manifest.json", "/favicon.ico", "/icon-192.png"];

// 입력: install 이벤트, 출력: 앱 셸을 캐시에 저장해 기본 오프라인 진입을 보장한다.
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

// 입력: activate 이벤트, 출력: 현재 버전 외의 오래된 캐시를 제거한다.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))),
  );
  self.clients.claim();
});

// 입력: 서버가 보낸 푸시 이벤트, 출력: 기기 알림 표시.
self.addEventListener("push", (event) => {
  let data = { title: "SCNU Lens", body: "새로운 공지가 있어요.", url: "/" };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch (error) {
    if (event.data) data.body = event.data.text();
  }
  event.waitUntil(
    Promise.all([
      self.registration.showNotification(data.title, {
        body: data.body,
        icon: "/icon-192.png",
        // 안드로이드 상태바용: 투명 배경의 흰색 실루엣이어야 제대로 보인다.
        badge: "/badge-96.png",
        data: { url: data.url },
        tag: data.url,
      }),
      // 홈 화면 앱 아이콘에 새 알림 표시를 단다(지원하는 기기만). 알림함을 열면 지운다.
      self.navigator && self.navigator.setAppBadge ? self.navigator.setAppBadge().catch(() => undefined) : Promise.resolve(),
    ]),
  );
});

// 입력: 알림 클릭, 출력: 앱을 보고 있으면 그 화면을 알림의 공지로 이동시키고, 아니면 앱(설치했으면 앱)으로 새로 연다.
// 예전에는 열린 탭에 초점만 줘서, 앱이 켜져 있으면 알림을 눌러도 해당 공지가 안 열렸다.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      // 지금 화면에 보이는 창(앱을 보고 있는 중)만 그 자리에서 이동한다.
      // 뒤에 숨은 브라우저 탭을 고르면 설치한 앱 대신 브라우저가 열리므로, 그때는 openWindow에 맡긴다.
      // 안드로이드는 앱(WebAPK)이 설치돼 있으면 범위 안 주소를 앱으로 연다.
      const visible = windows.find(
        (client) => client.url.startsWith(self.location.origin) && client.visibilityState === "visible" && "navigate" in client,
      );
      if (visible) return visible.navigate(target).then((client) => (client || visible).focus());
      return self.clients.openWindow(target);
    }),
  );
});

// 오프라인용으로 남겨 둘 공지 API 응답 수. 넘치면 오래된 것부터 지운다.
const MAX_API_ENTRIES = 30;

// 입력: 캐시, 출력 없음; 공지 API 응답이 MAX_API_ENTRIES를 넘으면 먼저 넣은 것부터 지운다.
async function trimApiCache(cache) {
  const keys = (await cache.keys()).filter((request) => request.url.includes("/api/notices"));
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_API_ENTRIES)).map((request) => cache.delete(request)));
}

// 입력: GET fetch 이벤트, 출력: 공지 API는 네트워크 우선·화면 자원은 캐시 우선으로 응답한다.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  // 개인화 응답은 기기별로 달라지므로 캐시에 남기지 않는다.
  if (url.pathname.includes("/api/notices/for-me") || url.pathname.includes("/api/notices/saved")) return;
  // 알림함은 기기마다 다르고 항상 최신이어야 한다.
  if (url.pathname.includes("/api/inbox")) return;
  // 캘린더 파일·관리자 API는 항상 최신이어야 하므로 캐시하지 않는다.
  if (url.pathname.endsWith(".ics") || url.pathname.includes("/api/admin/")) return;
  if (url.pathname.includes("/api/notices")) {
    // 검색 결과는 매번 달라 오프라인용으로 남길 가치가 없고, 남기면 검색어마다 캐시가 끝없이 늘어난다.
    const cacheable = !url.searchParams.get("search");
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (cacheable && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy).then(() => trimApiCache(cache)));
          }
          return response;
        })
        .catch(() => caches.match(event.request)),
    );
    return;
  }
  if (url.origin !== self.location.origin) return;
  // 화면(HTML)은 네트워크 우선이어야 배포 후에도 최신 앱 셸을 받는다. 오프라인일 때만 캐시를 쓴다.
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put("/", copy));
          return response;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});

