"use client";

import {
  BookOpenText,
  Compass,
  Gauge,
  LogIn,
  PenTool,
  Settings,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";
import { api } from "@/lib/api";

type CurrentUser = {
  display_name: string;
  email: string;
  roles: string[];
};

const primaryNavigation = [
  { href: "/library", label: "作品库", icon: Compass },
  { href: "/play", label: "我的故事", icon: BookOpenText },
  { href: "/creator", label: "创作台", icon: PenTool },
] as const;

function isCurrent(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

function displayName(user: CurrentUser) {
  return user.display_name.trim() || user.email.split("@")[0];
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [user, setUser] = useState<CurrentUser>();
  const [authReady, setAuthReady] = useState(false);
  const immersive = /^\/(play|creator)\/[^/]+/.test(pathname);

  useEffect(() => {
    let active = true;
    api<CurrentUser>("/auth/me")
      .then((current) => {
        if (active) setUser(current);
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setAuthReady(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const roleNavigation = [
    user?.roles.includes("reviewer")
      ? { href: "/review", label: "审核台", icon: ShieldCheck }
      : undefined,
    user?.roles.includes("admin") ? { href: "/admin", label: "管理", icon: Gauge } : undefined,
  ].filter(Boolean) as Array<{ href: string; label: string; icon: typeof Gauge }>;

  return (
    <div className={immersive ? "appFrame immersive" : "appFrame"}>
      <a className="skip" href="#content">
        跳到主要内容
      </a>
      <header className="topbar">
        <Link className="brand" href="/" aria-label="叙界首页">
          <span className="seal" aria-hidden="true">
            叙
          </span>
          <span>
            叙界<small>Narrative Studio</small>
          </span>
        </Link>
        <nav className="primaryNav" aria-label="主导航">
          {primaryNavigation.map(({ href, label, icon: Icon }) => (
            <Link
              href={href}
              key={href}
              className={isCurrent(pathname, href) ? "active" : undefined}
              aria-current={isCurrent(pathname, href) ? "page" : undefined}
            >
              <Icon size={18} />
              <span>{label}</span>
            </Link>
          ))}
          {roleNavigation.map(({ href, label, icon: Icon }) => (
            <Link
              href={href}
              key={href}
              className={`roleNav ${isCurrent(pathname, href) ? "active" : ""}`}
              aria-current={isCurrent(pathname, href) ? "page" : undefined}
            >
              <Icon size={18} />
              <span>{label}</span>
            </Link>
          ))}
        </nav>
        {user ? (
          <Link
            className={`account ${isCurrent(pathname, "/settings") ? "active" : ""}`}
            href="/settings"
            title={`${user.email} · 账户设置`}
          >
            <span className="accountAvatar" aria-hidden="true">
              {displayName(user).slice(0, 1).toUpperCase()}
            </span>
            <span className="accountCopy">
              <b>{displayName(user)}</b>
              <small>账户与隐私</small>
            </span>
            <Settings className="accountSettings" size={16} aria-hidden="true" />
          </Link>
        ) : (
          <Link className="account accountGuest" href="/login" aria-label="登录叙界">
            {authReady ? <LogIn size={18} /> : <UserRound className="authPulse" size={18} />}
            <span>{authReady ? "登录" : "账户"}</span>
          </Link>
        )}
      </header>
      <main id="content">{children}</main>
      {!immersive && (
        <footer>
          <span>叙界 · Narrative Studio</span>
          <span>尊重创作、隐私与每一次明确选择</span>
        </footer>
      )}
    </div>
  );
}
