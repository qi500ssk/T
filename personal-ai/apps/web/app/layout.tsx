import type { Metadata } from "next";
import AppearanceController from "@/components/AppearanceController";
import "./globals.css";

export const metadata: Metadata = {
  title: "Personal AI",
  description: "可扩展的个人 AI 助手",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="zh-CN"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col"><AppearanceController />{children}</body>
    </html>
  );
}
