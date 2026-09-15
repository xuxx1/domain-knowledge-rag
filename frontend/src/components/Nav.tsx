"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "知识库" },
  { href: "/chat", label: "智能问答" },
  { href: "/stats", label: "知识分析" },
  { href: "/settings", label: "参数设置" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <header className="nav">
      <div className="nav-inner">
        <Link href="/" className="brand">
          <span className="brand-mark">知</span>
          <span className="brand-name">垂直领域知识智能服务平台</span>
        </Link>
        <nav className="nav-links">
          {LINKS.map((l) => {
            const active = l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
            return (
              <Link key={l.href} href={l.href} className={`nav-link${active ? " active" : ""}`}>
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <style jsx>{`
        .nav {
          background: var(--paper);
          border-bottom: 1px solid var(--line);
          position: sticky;
          top: 0;
          z-index: 50;
        }
        .nav-inner {
          max-width: 1200px;
          margin: 0 auto;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 24px;
          height: 58px;
        }
        .brand {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .brand-mark {
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--accent);
          color: #fff;
          border-radius: 8px;
          font-family: "SimSun", "Songti SC", serif;
          font-size: 18px;
        }
        .brand-name {
          font-family: "SimSun", "Songti SC", serif;
          font-size: 17px;
          letter-spacing: 1px;
        }
        .nav-links {
          display: flex;
          gap: 4px;
        }
        .nav-link {
          padding: 6px 16px;
          border-radius: 6px;
          color: var(--ink-soft);
          font-size: 14px;
        }
        .nav-link:hover {
          color: var(--ink);
          background: #efe9de;
        }
        .nav-link.active {
          color: var(--accent);
          background: #f3e3df;
          font-weight: 600;
        }
      `}</style>
    </header>
  );
}
