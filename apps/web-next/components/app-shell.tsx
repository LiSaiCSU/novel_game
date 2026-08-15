"use client";

import {
  BookOpenText,
  ChevronUp,
  Compass,
  Gauge,
  LogIn,
  LogOut,
  PenTool,
  Settings,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";
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
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser>();
  const [authReady, setAuthReady] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const accountArea = useRef<HTMLDivElement>(null);
  const immersive = /^(?:\/play\/[^/]+|\/creator\/[^/]+)$/.test(pathname);

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

  useEffect(() => {
    if (!accountOpen) return;
    function close(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent && event.key !== "Escape") return;
      if (event instanceof MouseEvent && accountArea.current?.contains(event.target as Node))
        return;
      setAccountOpen(false);
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [accountOpen]);

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    setUser(undefined);
    setAccountOpen(false);
    router.replace("/");
    router.refresh();
  }

  const roleNavigation = [
    user?.roles.includes("reviewer")
      ? { href: "/review", label: "审核台", icon: ShieldCheck }
      : undefined,
    user?.roles.includes("admin") ? { href: "/admin", label: "管理", icon: Gauge } : undefined,
  ].filter(Boolean) as Array<{ href: string; label: string; icon: typeof Gauge }>;
  const navigation = user
    ? [...primaryNavigation, { href: "/settings", label: "账户设置", icon: Settings }]
    : primaryNavigation;

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
            叙界<small>互动叙事平台</small>
          </span>
        </Link>
        <div className="navSpacer" aria-hidden="true" />
        <nav className="primaryNav" aria-label="主导航">
          <span className="navSectionLabel">探索与工作</span>
          {navigation.map(({ href, label, icon: Icon }) => (
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
          <div className="accountArea" ref={accountArea}>
            <button
              type="button"
              className={`account ${accountOpen || isCurrent(pathname, "/settings") ? "active" : ""}`}
              title={`${user.email} · 账户菜单`}
              aria-label={`打开账户菜单：${displayName(user)}`}
              aria-expanded={accountOpen}
              aria-controls="account-menu"
              onClick={() => setAccountOpen((open) => !open)}
            >
              <span className="accountAvatar" aria-hidden="true">
                {displayName(user).slice(0, 1).toUpperCase()}
              </span>
              <span className="accountCopy">
                <b>{displayName(user)}</b>
                <small>账户与偏好</small>
              </span>
              <ChevronUp className="accountSettings" size={16} aria-hidden="true" />
            </button>
            {accountOpen && (
              <div className="accountMenu" id="account-menu" role="menu">
                <header>
                  <b>{displayName(user)}</b>
                  <small>{user.email}</small>
                </header>
                <Link href="/play" role="menuitem" onClick={() => setAccountOpen(false)}>
                  <BookOpenText size={16} /> 我的故事
                </Link>
                <Link href="/settings" role="menuitem" onClick={() => setAccountOpen(false)}>
                  <Settings size={16} /> 账户设置
                </Link>
                {user.roles.includes("admin") && (
                  <Link href="/admin" role="menuitem" onClick={() => setAccountOpen(false)}>
                    <Gauge size={16} /> 平台管理
                  </Link>
                )}
                <button type="button" role="menuitem" onClick={() => void logout()}>
                  <LogOut size={16} /> 退出登录
                </button>
              </div>
            )}
          </div>
        ) : (
          <Link className="account accountGuest" href="/" aria-label="登录叙界">
            {authReady ? <LogIn size={18} /> : <UserRound className="authPulse" size={18} />}
            <span>{authReady ? "登录" : "账户"}</span>
          </Link>
        )}
      </header>
      <main id="content">{children}</main>
      {!immersive && (
        <footer>
          <span>叙界 · 互动叙事平台</span>
          <span>尊重创作、隐私与每一次明确选择</span>
        </footer>
      )}
    </div>
  );
}
