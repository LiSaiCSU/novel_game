"use client";

import { ArrowRight, BookOpenText, PenTool, ShieldCheck, Sparkles, WalletCards } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type CurrentUser = {
  display_name: string;
  email: string;
};

const promises = [
  {
    icon: BookOpenText,
    title: "故事会记住选择",
    description: "每次开局固定在一个发布版本；存档、关系与世界状态都属于你的这段旅程。",
    href: "/library",
    action: "浏览作品库",
  },
  {
    icon: Sparkles,
    title: "模型为叙事服务",
    description: "可选择平台托管模型或自带密钥。失败与降级结果不应悄悄消耗你的平台权益。",
    href: "/pricing",
    action: "查看权益规则",
  },
  {
    icon: PenTool,
    title: "创作者有自己的工作台",
    description: "从草稿到审核、发布，再到不可变版本，让每一次更新都可追溯。",
    href: "/creator",
    action: "进入创作台",
  },
] as const;

export function LandingPage() {
  const [user, setUser] = useState<CurrentUser>();

  useEffect(() => {
    let active = true;
    api<CurrentUser>("/auth/me")
      .then((current) => active && setUser(current))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const name = user?.display_name.trim() || user?.email.split("@")[0];
  const primaryHref = user ? "/play" : "/register";

  return (
    <div className="landingPage">
      <section className="landingHero">
        <div className="landingGlow landingGlowOne" aria-hidden="true" />
        <div className="landingGlow landingGlowTwo" aria-hidden="true" />
        <div className="landingHeroCopy">
          <p className="eyebrow">INTERACTIVE NARRATIVE STUDIO</p>
          <h1>
            让每一次选择，
            <br />都成为世界的一部分。
          </h1>
          <p>
            进入可持续生长的文字冒险：探索正式发布的作品、保存属于你的故事，并在需要时亲手创作新的世界。
          </p>
          <div className="landingActions">
            <Link className="button primary" href={primaryHref}>
              {user ? `${name ?? "继续"}，继续故事` : "免费开始一段故事"} <ArrowRight size={17} />
            </Link>
            <Link className="button landingSecondary" href="/library">
              先浏览作品
            </Link>
          </div>
          <div className="landingTrust" aria-label="平台承诺">
            <span>
              <ShieldCheck size={16} /> 独立存档与版本保护
            </span>
            <span>
              <WalletCards size={16} /> 权益和价格公开可查
            </span>
          </div>
        </div>
        <aside className="landingStoryCard" aria-label="体验方式">
          <p>从一个选择开始</p>
          <blockquote>“雨停之后，旧车站的广播再次报出了你的名字。”</blockquote>
          <div>
            <span>沉浸式文字叙事</span>
            <span>可随时保存、继续与回望</span>
          </div>
        </aside>
      </section>

      <section className="landingPathways" aria-labelledby="landing-pathways-title">
        <div className="landingSectionHead">
          <p className="eyebrow">一座值得长期停留的叙事世界</p>
          <h2 id="landing-pathways-title">从发现到沉浸，每一步都有明确去处。</h2>
        </div>
        <div className="landingPathwayGrid">
          {promises.map(({ icon: Icon, title, description, href, action }) => (
            <article key={title}>
              <Icon size={22} aria-hidden="true" />
              <h3>{title}</h3>
              <p>{description}</p>
              <Link href={href}>
                {action} <ArrowRight size={15} />
              </Link>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
