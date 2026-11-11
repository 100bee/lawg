import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lawg",
  description: "Lawg: 게임·커뮤니티 온라인 사건 법령 안내 (개발 중)",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}

