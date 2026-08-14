"use client";

import { ArrowUpRight, Search, SlidersHorizontal, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";
import { CardSkeletons, EmptyState, ErrorState, RetryButton } from "@/components/ui/async-state";
import { api } from "@/lib/api";

type Release = {
  id: string;
  slug: string;
  title: string;
  summary: string;
  version: string;
  locale: string;
  rating: string;
  tags: string[];
  cover_url?: string | null;
  play_count: number;
};

const localeNames: Record<string, string> = {
  "zh-CN": "简体中文",
  "zh-TW": "繁体中文",
  "ja-JP": "日语",
};

export default function LibraryPage() {
  const [items, setItems] = useState<Release[]>([]);
  const [q, setQ] = useState("");
  const [locale, setLocale] = useState("");
  const [rating, setRating] = useState("");
  const [sort, setSort] = useState("updated");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const hasFilters = Boolean(q || locale || rating || sort !== "updated");

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      const query = new URLSearchParams({ q, sort });
      if (locale) query.set("locale", locale);
      if (rating) query.set("rating", rating);
      api<{ items: Release[] }>(`/catalog/releases?${query}`, { signal: controller.signal })
        .then((result) => {
          setItems(result.items);
          setError("");
        })
        .catch((exception) => {
          if ((exception as Error).name !== "AbortError") setError((exception as Error).message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [q, locale, rating, sort, reloadKey]);

  function clearFilters() {
    setQ("");
    setLocale("");
    setRating("");
    setSort("updated");
  }

  return (
    <div className="page libraryPage">
      <header className="pageHead libraryHead">
        <div>
          <p className="eyebrow">WORLD LIBRARY</p>
          <h1>找一个世界，留下你的版本。</h1>
          <p>每局固定在开始时的发布版本上。作者更新作品，也不会悄悄改写你的经历。</p>
        </div>
        <div className="libraryPromise" aria-label="作品库保障">
          <b>不可变发布版本</b>
          <span>审核内容 · 独立存档 · 随时继续</span>
        </div>
      </header>

      <section className="filterPanel" aria-label="筛选作品">
        <div className="filterPanelTitle">
          <SlidersHorizontal size={18} />
          <b>筛选作品</b>
          {!loading && <span>{items.length} 部可进入作品</span>}
        </div>
        <div className="libraryFilters">
          <label className="field" htmlFor="search">
            <span>搜索</span>
            <span className="searchInput">
              <Search size={17} aria-hidden="true" />
              <input
                id="search"
                className="input"
                value={q}
                onChange={(event) => setQ(event.target.value)}
                placeholder="标题、简介或标签"
              />
              {q && (
                <button type="button" onClick={() => setQ("")} aria-label="清除搜索内容">
                  <X size={16} />
                </button>
              )}
            </span>
          </label>
          <label className="field">
            <span>语言</span>
            <select className="select" value={locale} onChange={(e) => setLocale(e.target.value)}>
              <option value="">全部语言</option>
              <option value="zh-CN">简体中文</option>
              <option value="ja-JP">日语</option>
            </select>
          </label>
          <label className="field">
            <span>分级</span>
            <select className="select" value={rating} onChange={(e) => setRating(e.target.value)}>
              <option value="">全部分级</option>
              <option value="all">全年龄</option>
              <option value="13+">13+</option>
              <option value="16+">16+</option>
            </select>
          </label>
          <label className="field">
            <span>排序</span>
            <select className="select" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="updated">最近更新</option>
              <option value="popular">最受欢迎</option>
              <option value="newest">最新发布</option>
            </select>
          </label>
        </div>
        {hasFilters && (
          <button className="clearFilters" type="button" onClick={clearFilters}>
            清除全部筛选
          </button>
        )}
      </section>

      {error ? (
        <ErrorState
          title="作品库暂时没有加载成功"
          description={error}
          action={<RetryButton onClick={() => setReloadKey((value) => value + 1)} />}
        />
      ) : loading && items.length === 0 ? (
        <CardSkeletons />
      ) : items.length === 0 ? (
        <EmptyState
          title="没有找到符合条件的作品"
          description="换一个关键词或清除筛选条件，再看看其他世界。"
          action={
            <button className="button secondary" type="button" onClick={clearFilters}>
              清除筛选
            </button>
          }
        />
      ) : (
        <div className={`cardGrid ${loading ? "refreshing" : ""}`} aria-busy={loading}>
          {items.map((item) => (
            <article className="workCard catalogCard" key={item.id}>
              <Link
                className="workCover"
                href={`/library/${item.id}`}
                tabIndex={-1}
                aria-hidden="true"
              >
                <Image
                  src={item.cover_url || "/og.png"}
                  alt=""
                  fill
                  sizes="(max-width:720px) 100vw, (max-width:1100px) 50vw, 33vw"
                />
                <span className="coverRating">{item.rating}</span>
              </Link>
              <div className="workBody">
                <div className="meta">
                  <span>{localeNames[item.locale] ?? item.locale}</span>
                  <span>v{item.version}</span>
                  <span>{item.play_count.toLocaleString("zh-CN")} 局</span>
                </div>
                <h2>
                  <Link href={`/library/${item.id}`}>{item.title}</Link>
                </h2>
                <p className="cardSummary">{item.summary}</p>
                <div className="chips compactChips">
                  {item.tags.slice(0, 4).map((tag) => (
                    <button type="button" key={tag} onClick={() => setQ(tag)}>
                      {tag}
                    </button>
                  ))}
                </div>
                <Link className="cardLink" href={`/library/${item.id}`}>
                  查看作品 <ArrowUpRight size={16} />
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
