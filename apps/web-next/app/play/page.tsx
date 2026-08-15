"use client";

import {
  ArrowRight,
  BookOpenText,
  Check,
  Clock3,
  Plus,
  SlidersHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
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
  settings: PlaythroughSettings;
};

type NarrativeLength = "concise" | "standard" | "detailed" | "long";
type PlaythroughSettings = {
  narrative_length: NarrativeLength;
  narrative_max_chars: number;
  presets: Array<{
    key: NarrativeLength;
    label: string;
    min_chars: number;
    max_chars: number;
  }>;
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
  const [deleting, setDeleting] = useState("");
  const [settingsOpen, setSettingsOpen] = useState("");
  const [savingSettings, setSavingSettings] = useState("");

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

  async function deleteStory(item: Play) {
    if (!window.confirm(`删除“${item.name || item.release.title}”？它会立即从你的故事书架移除。`)) {
      return;
    }
    setDeleting(item.id);
    setError("");
    try {
      await api(`/playthroughs/${item.id}`, { method: "DELETE" });
      setItems((current) => current.filter((story) => story.id !== item.id));
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setDeleting("");
    }
  }

  async function updateLength(item: Play, narrativeLength: NarrativeLength) {
    setSavingSettings(item.id);
    setError("");
    try {
      const settings = await api<PlaythroughSettings>(`/playthroughs/${item.id}/settings`, {
        method: "PUT",
        body: JSON.stringify({ narrative_length: narrativeLength }),
      });
      setItems((current) =>
        current.map((story) => (story.id === item.id ? { ...story, settings } : story)),
      );
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setSavingSettings("");
    }
  }

  return (
    <div className="page playLibraryPage">
      <header className="pageHead">
        <div>
          <p className="eyebrow">我的故事</p>
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
                    {item.preview ? "创作预览" : (statusLabels[item.status] ?? "状态已更新")}
                  </span>
                  <span>{item.release.title}</span>
                </div>
                <h2>{item.name || "未命名旅程"}</h2>
                <p>
                  <Clock3 size={14} />
                  最后进入 {new Date(item.updated_at).toLocaleString("zh-CN")}
                </p>
              </div>
              <div className="playCardActions">
                <Link
                  className="playContinue"
                  href={`/play/${item.id}`}
                  aria-label={`继续${item.name}`}
                >
                  {item.status === "completed" ? "重温" : "继续"} <ArrowRight size={17} />
                </Link>
                <button
                  type="button"
                  className={`playManage ${settingsOpen === item.id ? "active" : ""}`}
                  aria-label={`设置${item.name || item.release.title}`}
                  aria-expanded={settingsOpen === item.id}
                  onClick={() => setSettingsOpen((current) => (current === item.id ? "" : item.id))}
                >
                  <SlidersHorizontal size={16} />
                  <span>故事设置</span>
                </button>
                <button
                  type="button"
                  className="playDelete"
                  aria-label={`删除${item.name}`}
                  title="删除故事"
                  disabled={deleting === item.id}
                  onClick={() => void deleteStory(item)}
                >
                  <Trash2 size={16} />
                </button>
              </div>
              {settingsOpen === item.id && (
                <fieldset className="playSettings">
                  <legend>每回合叙事长度</legend>
                  <p>从下一个回合开始生效；字数越多，生成时间和模型用量越高。</p>
                  <div>
                    {item.settings.presets.map((preset) => {
                      const selected = item.settings.narrative_length === preset.key;
                      return (
                        <button
                          type="button"
                          key={preset.key}
                          className={selected ? "selected" : ""}
                          aria-pressed={selected}
                          disabled={savingSettings === item.id}
                          onClick={() => void updateLength(item, preset.key)}
                        >
                          <span>
                            <b>{preset.label}</b>
                            <small>
                              约 {preset.min_chars}–{preset.max_chars} 字
                            </small>
                          </span>
                          {selected && <Check size={15} aria-hidden="true" />}
                        </button>
                      );
                    })}
                  </div>
                </fieldset>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
