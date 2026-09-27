import type { Metadata, Viewport } from "next";

import { ServiceWorkerRegistration } from "@/components/service-worker";
import "./globals.css";

export const metadata: Metadata = {
  title: "SCNU Lens | 순천대 AI 통합 알리미",
  description: "흩어진 순천대학교 공지를 모아 나에게 필요한 이유까지 알려주는 AI 캠퍼스 브리핑",
  manifest: "/manifest.json",
  // 순천대 로고 아이콘. 파비콘은 .ico(16~64px), 아이폰 홈 화면은 흰 배경 180px.
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icon-192.png", type: "image/png", sizes: "192x192" },
    ],
    apple: "/apple-touch-icon.png",
  },
};

// 휴대폰 주소창 색을 바탕색과 맞춘다.
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#fafaf8" };

// 입력: 페이지 children, 출력: 한국어 메타데이터와 PWA 등록을 포함한 루트 문서.
// 본문 글꼴 Pretendard를 불러온다. 오프라인이면 시스템 글꼴로 대신한다.
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <head>
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
        />
      </head>
      <body>
        <ServiceWorkerRegistration />
        {children}
      </body>
    </html>
  );
}
