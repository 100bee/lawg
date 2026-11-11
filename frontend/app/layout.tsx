import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lawg",
  description: "Lawg v1 엔진 데모: 운영 장애 문서 RAG",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}

