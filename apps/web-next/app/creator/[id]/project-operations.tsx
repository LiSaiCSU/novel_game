"use client";

import { type FormEvent, useMemo, useState } from "react";
import { Field } from "./editor-controls";
import type { Asset, CreatedRelease, ProjectRevision, Release } from "./editor-types";

type FlatDocument = Record<string, string>;
function flattenDocument(value: unknown, path = "", target: FlatDocument = {}): FlatDocument {
  if (value !== null && typeof value === "object") {
    for (const [key, child] of Object.entries(value))
      flattenDocument(child, path ? `${path}.${key}` : key, target);
  } else target[path] = JSON.stringify(value) ?? "undefined";
  return target;
}

export function VersionDiff({ revisions }: { revisions: ProjectRevision[] }) {
  const [before, setBefore] = useState<number>();
  const [after, setAfter] = useState<number>();
  const beforeRevision = before ?? revisions[1]?.revision ?? revisions[0]?.revision;
  const afterRevision = after ?? revisions[0]?.revision;
  const changes = useMemo(() => {
    const oldDocument = revisions.find((item) => item.revision === beforeRevision)?.document;
    const newDocument = revisions.find((item) => item.revision === afterRevision)?.document;
    if (!oldDocument || !newDocument) return [];
    const oldFlat = flattenDocument(oldDocument),
      newFlat = flattenDocument(newDocument);
    return [...new Set([...Object.keys(oldFlat), ...Object.keys(newFlat)])]
      .filter((path) => oldFlat[path] !== newFlat[path])
      .map((path) => ({ path, before: oldFlat[path], after: newFlat[path] }));
  }, [revisions, beforeRevision, afterRevision]);
  if (!revisions.length) return <div className="empty">保存第一次修改后即可比较版本。</div>;
  return (
    <div className="diffWorkspace">
      <section className="panel">
        <div className="diffSelectors">
          <label className="studioField">
            <span>对比起点</span>
            <select
              className="select"
              value={beforeRevision}
              onChange={(event) => setBefore(Number(event.target.value))}
            >
              {revisions.map((item) => (
                <option key={item.revision} value={item.revision}>
                  Revision {item.revision} · {new Date(item.created_at).toLocaleString("zh-CN")}
                </option>
              ))}
            </select>
          </label>
          <span>→</span>
          <label className="studioField">
            <span>对比终点</span>
            <select
              className="select"
              value={afterRevision}
              onChange={(event) => setAfter(Number(event.target.value))}
            >
              {revisions.map((item) => (
                <option key={item.revision} value={item.revision}>
                  Revision {item.revision} · {new Date(item.created_at).toLocaleString("zh-CN")}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>
      <div className="diffSummary">
        <b>{changes.length}</b>
        <span>处字段变化</span>
      </div>
      {changes.slice(0, 120).map((change) => (
        <article className="diffRow" key={change.path}>
          <code>{change.path}</code>
          <div>
            <del>{change.before ?? "未设置"}</del>
            <ins>{change.after ?? "已删除"}</ins>
          </div>
        </article>
      ))}
      {changes.length > 120 && (
        <p className="studioHint">仅显示前 120 处变化；导出两个版本可进行完整机器比较。</p>
      )}
      {!changes.length && <div className="empty">两个修订内容一致。</div>}
    </div>
  );
}

export function AssetManager({
  assets,
  upload,
}: {
  assets: Asset[];
  upload: (event: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  return (
    <div className="releaseLayout">
      <form className="panel stack" onSubmit={upload}>
        <h2>上传图片</h2>
        <label className="studioField">
          <span>稳定 key</span>
          <input
            className="input"
            name="key"
            pattern="[a-z][a-z0-9_]{1,79}"
            placeholder="main_cover"
            required
          />
        </label>
        <label className="studioField">
          <span>类型</span>
          <select className="select" name="kind">
            <option value="cover">封面</option>
            <option value="avatar">角色头像</option>
            <option value="background">场景背景</option>
          </select>
        </label>
        <label className="studioField">
          <span>无障碍描述</span>
          <input className="input" name="alt_text" required maxLength={300} />
        </label>
        <input
          className="input"
          type="file"
          name="file"
          accept="image/jpeg,image/png,image/webp"
          required
        />
        <button className="button primary">上传并加入内容包</button>
        <p className="studioHint">
          支持 JPEG、PNG、WebP，最大 8 MB、64–6000 像素；服务端会重新编码、清除元数据并生成 WebP
          缩略图。
        </p>
      </form>
      <section>
        <h2>素材库</h2>
        <div className="assetGrid">
          {assets.map((asset) => (
            <article className="assetCard" key={asset.id}>
              <div
                className="assetPreview"
                role="img"
                aria-label={asset.alt}
                style={{ backgroundImage: `url(${asset.thumbnail_url ?? asset.url})` }}
              />
              <b>{asset.key}</b>
              <small>
                {asset.kind} · {asset.width}×{asset.height}
              </small>
            </article>
          ))}
        </div>
        {assets.length === 0 && <div className="empty">尚未上传图片</div>}
      </section>
    </div>
  );
}

export function ReleaseCenter({
  releases,
  publish,
  appeal,
}: {
  releases: Release[];
  publish: (version: string, visibility: string) => Promise<CreatedRelease>;
  appeal: (releaseId: string) => Promise<void>;
}) {
  const [version, setVersion] = useState("1.0.0");
  const [visibility, setVisibility] = useState("private");
  const [message, setMessage] = useState("");
  return (
    <div className="releaseLayout">
      <section className="panel stack">
        <h2>生成不可变版本</h2>
        <Field label="语义版本" value={version} onChange={setVersion} />
        <label className="studioField">
          <span>可见性</span>
          <select
            className="select"
            value={visibility}
            onChange={(event) => setVisibility(event.target.value)}
          >
            <option value="private">私密</option>
            <option value="unlisted">未列出</option>
            <option value="public">公开并提交审核</option>
          </select>
        </label>
        <button
          className="button primary"
          onClick={() =>
            publish(version, visibility)
              .then(async (created) => {
                if (created.share_token) {
                  const url = `${window.location.origin}/invite/${created.share_token}`;
                  await navigator.clipboard?.writeText(url);
                  setMessage(`受邀链接已复制（令牌仅显示一次）：${url}`);
                } else setMessage("版本已创建");
              })
              .catch((error) => setMessage(error.message))
          }
        >
          编译并发布
        </button>
        {message && <p className="saveState shareUrl">{message}</p>}
      </section>
      <section>
        <h2>版本历史</h2>
        {releases.length === 0 ? (
          <div className="empty">尚未发布版本</div>
        ) : (
          releases.map((item) => (
            <article className="releaseRow" key={item.id}>
              <div>
                <b>v{item.version}</b>
                <small>{item.checksum.slice(0, 12)}</small>
              </div>
              <div className="releaseStatus">
                <span>
                  {item.visibility} · {item.status}
                </span>
                {["rejected", "withdrawn"].includes(item.status) && (
                  <button
                    className="dangerLink"
                    onClick={() =>
                      appeal(item.id)
                        .then(() => setMessage("申诉已提交"))
                        .catch((error) => setMessage(error.message))
                    }
                  >
                    提交申诉
                  </button>
                )}
              </div>
            </article>
          ))
        )}
      </section>
    </div>
  );
}
