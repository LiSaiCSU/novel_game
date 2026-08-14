"use client";

import { ArrowRight, BookOpenText, Clock3, Plus, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CardSkeletons, EmptyState, ErrorState, RetryButton } from "@/components/ui/async-state";
import { api } from "@/lib/api";

type Play = {
  id: string;
  name: string;
  status: string;
  preview: boolean;
  updated_at: string;
  release: { id: string; title: string };
};

const statusLabels: Record<string, string> = {
  active: "进行中",
  completed: "已抵达结局",
  archived: "已归档",
};

export default function PlayLibrary() {
  const [items, setItems] = useState<Play[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    api<Play[]>("/playthroughs")
      .then((result) => {
        setItems(result);
        setError("");
      })
      .catch((exception) => setError((exception as Error).message))
      .finally(() => setLoading(false));
  }, [reloadKey]);

  const counts = useMemo(
    () => ({
      active: items.filter((item) => item.status === "active" && !item.preview).length,
      completed: items.filter((item) => item.status === "completed").length,
      preview: items.filter((item) => item.preview).length,
    }),
    [items],
  );

  return (
    <div className="page playLibraryPage">
      <header className="pageHead">
        <div>
          <p className="eyebrow">MY STORIES</p>
          <h1>我的故事</h1>
          <p>每段旅程都有独立存档，并固定在开始时的作品版本上。</p>
        </div>
        <Link className="button primary" href="/library">
          <Plus size={17} />
          开始新故事
        </Link>
      </header>

      {!loading && !error && items.length > 0 && (
        <div className="storyStats" aria-label="故事统计">
          <span>
            <BookOpenText size={18} /> <b>{counts.active}</b> 段进行中
          </span>
          <span>
            <Sparkles size={18} /> <b>{counts.completed}</b> 个已完成结局
          </span>
          {counts.preview > 0 && (
            <span>
              <Clock3 size={18} /> <b>{counts.preview}</b> 个创作预览
            </span>
          )}
        </div>
      )}

      {error ? (
        <ErrorState
          title="还不能读取你的故事"
          description={error}
          action={
            <div className="stateButtons">
              <RetryButton
                onClick={() => {
                  setLoading(true);
                  setError("");
                  setReloadKey((value) => value + 1);
                }}
              />
              <Link className="button ghost" href="/login">
                前往登录
              </Link>
            </div>
          }
        />
      ) : loading ? (
        <CardSkeletons count={3} />
      ) : items.length === 0 ? (
        <EmptyState
          title="书架还是空的"
          description="从公开作品库选择一个世界。你的角色、选择与存档都会保存在自己的账号中。"
          action={
            <Link className="button primary" href="/library">
              浏览作品库 <ArrowRight size={16} />
            </Link>
          }
        />
      ) : (
        <div className="playGrid">
          {items.map((item) => (
            <article className="playCard" key={item.id}>
              <div className="playMonogram" aria-hidden="true">
                {item.release.title.slice(0, 1)}
              </div>
              <div className="playCardBody">
                <div className="meta">
                  <span className={`statusDot ${item.status}`}>
                    {item.preview ? "创作预览" : (statusLabels[item.status] ?? item.status)}
                  </span>
                  <span>{item.release.title}</span>
                </div>
                <h2>{item.name || "未命名旅程"}</h2>
                <p>
                  <Clock3 size={14} />
                  最后进入 {new Date(item.updated_at).toLocaleString("zh-CN")}
                </p>
              </div>
              <Link
                className="playContinue"
                href={`/play/${item.id}`}
                aria-label={`继续${item.name}`}
              >
                {item.status === "completed" ? "重温" : "继续"} <ArrowRight size={17} />
              </Link>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
