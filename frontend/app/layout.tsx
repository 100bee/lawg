import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lawg",
  description: "AI 서비스 운영 장애 대응 RAG Copilot",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}

