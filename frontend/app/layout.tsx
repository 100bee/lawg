import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lawg",
  description: "게임·커뮤니티에서 생긴 온라인 사건을 법령 정보로 정리해 드립니다. 법률 상담이 아닙니다.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;500;600&family=Noto+Serif+KR:wght@500;700&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}

