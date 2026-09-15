import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "垂直领域知识智能服务平台",
  description: "基于 RAG 的大模型知识应用系统：知识库管理 / 智能检索问答 / 知识分析",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        <Nav />
        <main className="page-container">{children}</main>
      </body>
    </html>
  );
}
