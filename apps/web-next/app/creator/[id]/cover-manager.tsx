"use client";

import { type FormEvent, useState } from "react";
import type { Asset } from "./editor-types";

const labels: Record<Asset["kind"], string> = {
  cover: "作品封面",
  avatar: "角色头像",
  background: "场景背景",
};

export function CoverManager({
  assets,
  upload,
}: {
  assets: Asset[];
  upload: (form: FormData) => Promise<void>;
}) {
  const [kind, setKind] = useState<Asset["kind"]>("cover");
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const currentCover = assets.find((asset) => asset.kind === "cover");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    form.set("kind", kind);
    // Logical keys are an implementation detail. Generate a new immutable
    // asset key for every replacement, so already published releases keep
    // pointing at their original cover.
    form.set("key", `${kind}_${Date.now().toString(36)}`);
    if (!String(form.get("alt_text") ?? "").trim()) form.set("alt_text", labels[kind]);
    setUploading(true);
    setMessage("");
    try {
      await upload(form);
      event.currentTarget.reset();
      setMessage(kind === "cover" ? "封面已更新，已发布版本仍保留原图。" : "图片已加入故事素材。 ");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="releaseLayout creatorVisuals">
      <form className="panel stack" onSubmit={submit}>
        <div>
          <span className="eyebrow">故事视觉</span>
          <h2>给故事加一张封面</h2>
          <p className="studioHint">
            封面是读者认识作品的第一眼。以后可以放心替换，不会改变已发布的旧版本。
          </p>
        </div>
        <label className="studioField">
          <span>图片用途</span>
          <select
            className="select"
            value={kind}
            onChange={(event) => setKind(event.target.value as Asset["kind"])}
          >
            <option value="cover">作品封面</option>
            <option value="avatar">角色头像</option>
            <option value="background">场景背景</option>
          </select>
        </label>
        <label className="studioField">
          <span>一句图片描述（可选）</span>
          <input
            className="input"
            name="alt_text"
            maxLength={300}
            placeholder="例如：雨夜里亮着灯的旧书店"
          />
        </label>
        <label className="studioField">
          <span>选择图片</span>
          <input
            className="input"
            type="file"
            name="file"
            accept="image/jpeg,image/png,image/webp"
            required
          />
        </label>
        <button className="button primary" disabled={uploading}>
          {uploading ? "正在安全处理图片…" : kind === "cover" ? "上传并设为封面" : "上传图片"}
        </button>
        <p className="studioHint">
          支持 JPEG、PNG、WebP，最大 8 MB。上传后会清除图片元数据、重新编码并生成缩略图。
        </p>
        {message && <p className={message.includes("失败") ? "error" : "saveState"}>{message}</p>}
      </form>
      <section>
        <h2>你的图片</h2>
        {currentCover && (
          <article className="creatorCoverPreview">
            <div
              className="assetPreview"
              style={{ backgroundImage: `url(${currentCover.thumbnail_url ?? currentCover.url})` }}
            />
            <div>
              <span className="eyebrow">当前封面</span>
              <b>{currentCover.alt || "作品封面"}</b>
            </div>
          </article>
        )}
        <div className="assetGrid">
          {assets.map((asset) => (
            <article className="assetCard" key={asset.id}>
              <div
                className="assetPreview"
                role="img"
                aria-label={asset.alt}
                style={{ backgroundImage: `url(${asset.thumbnail_url ?? asset.url})` }}
              />
              <b>{labels[asset.kind]}</b>
              <small>
                {asset.width}×{asset.height}
              </small>
            </article>
          ))}
        </div>
        {assets.length === 0 && <div className="empty">还没有图片。先上传一张封面吧。</div>}
      </section>
    </div>
  );
}
