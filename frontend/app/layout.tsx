import type { Metadata, Viewport } from "next";

import { ServiceWorkerRegistration } from "@/components/service-worker";
import "./globals.css";

const DESCRIPTION = "흩어진 순천대학교 공지를 모아 나에게 필요한 이유까지 알려주는 AI 캠퍼스 브리핑";

export const metadata: Metadata = {
  // 카카오톡·메신저 공유 미리보기의 이미지 주소를 절대 주소로 만들 기준.
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://scnuaram.vercel.app"),
  title: "SCNU Lens | 순천대 AI 통합 알리미",
  description: DESCRIPTION,
  manifest: "/manifest.json",
  openGraph: {
    type: "website",
    locale: "ko_KR",
    siteName: "SCNU Lens",
    title: "SCNU Lens | 순천대 AI 통합 알리미",
    description: DESCRIPTION,
    images: [{ url: "/og-image.png", width: 1200, height: 630, alt: "SCNU Lens 순천대 AI 통합 알리미" }],
  },
  twitter: { card: "summary_large_image", images: ["/og-image.png"] },
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
