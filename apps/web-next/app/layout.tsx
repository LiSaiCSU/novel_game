import type { Metadata } from "next";
import Link from "next/link";
import { BookOpenText, Compass, Gauge, PenTool, ShieldCheck, UserRound } from "lucide-react";
import "./globals.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: "叙界 Narrative Studio", template: "%s · 叙界" },
  description: "创作、发布并亲自走进会记住你选择的叙事世界。",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  openGraph: { title: "叙界 Narrative Studio", description: "把未写完的故事，交还给选择它的人", images: ["/og.png"] },
  twitter: { card: "summary_large_image", title: "叙界 Narrative Studio", images: ["/og.png"] },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <a className="skip" href="#content">跳到主要内容</a>
        <header className="topbar">
          <Link className="brand" href="/"><span className="seal">叙</span><span>叙界<small>Narrative Studio</small></span></Link>
          <nav aria-label="主导航">
            <Link href="/library"><Compass size={18} />作品库</Link>
            <Link href="/play"><BookOpenText size={18} />我的故事</Link>
            <Link href="/creator"><PenTool size={18} />创作台</Link>
            <Link href="/review"><ShieldCheck size={18} />审核台</Link>
            <Link href="/admin"><Gauge size={18} />管理</Link>
          </nav>
          <Link className="account" href="/login"><UserRound size={18} /><span>登录</span></Link>
        </header>
        <main id="content">{children}</main>
        <footer><span>叙界 · Narrative Studio</span><span>尊重创作、隐私与每一次明确选择</span></footer>
      </body>
    </html>
  );
}
