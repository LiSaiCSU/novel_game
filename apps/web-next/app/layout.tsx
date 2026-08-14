import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";
import "./globals.css";
import "./product.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: { default: "叙界 · 互动叙事平台", template: "%s · 叙界" },
  description: "创作、发布并亲自走进会记住你选择的叙事世界。",
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  openGraph: {
    title: "叙界 · 互动叙事平台",
    description: "把未写完的故事，交还给选择它的人",
    images: ["/og.png"],
  },
  twitter: { card: "summary_large_image", title: "叙界 · 互动叙事平台", images: ["/og.png"] },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
