"use client";

import { FormEvent, useEffect, useState } from "react";
import { Gift } from "lucide-react";
import { api } from "@/lib/api";

type CampaignStatus = "draft" | "active" | "paused" | "ended";

type Campaign = {
  id: string;
  code: string;
  name: string;
  description: string;
  credit_amount: number;
  status: CampaignStatus;
  starts_at: string;
  ends_at: string;
  max_redemptions: number | null;
  redemption_count: number;
  redemptions_remaining: number | null;
  claimable: boolean;
};

type CampaignList = { credit_label: string; items: Campaign[] };

type Draft = {
  code: string;
  name: string;
  description: string;
  credit_amount: number;
  status: "draft" | "active" | "paused";
  starts_at: string;
  ends_at: string;
  max_redemptions: string;
  reason: string;
};

const statusLabel: Record<CampaignStatus, string> = {
  draft: "草稿",
  active: "进行中",
  paused: "已暂停",
  ended: "已结束",
};

function localDateTime(value: Date): string {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 16);
}

function defaultDraft(): Draft {
  const now = Date.now();
  return {
    code: "launch_bonus",
    name: "新玩家体验赠点",
    description: "活动期间每位玩家仅可领取一次。",
    credit_amount: 100,
    status: "draft",
    starts_at: localDateTime(new Date(now)),
    ends_at: localDateTime(new Date(now + 7 * 24 * 60 * 60_000)),
    max_redemptions: "",
    reason: "创建可审计的运营赠点活动",
  };
}

export default function CampaignOpsPanel() {
  const [campaigns, setCampaigns] = useState<CampaignList>();
  const [draft, setDraft] = useState<Draft>(defaultDraft);
  const [saving, setSaving] = useState(false);
  const [changingId, setChangingId] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const result = await api<CampaignList>("/admin/commerce/campaigns");
    setCampaigns(result);
    setError("");
  }

  useEffect(() => {
    api<CampaignList>("/admin/commerce/campaigns")
      .then((result) => {
        setCampaigns(result);
        setError("");
      })
      .catch((exception: Error) => setError(exception.message));
  }, []);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (draft.reason.trim().length < 3) return;
    setSaving(true);
    try {
      await api<Campaign>("/admin/commerce/campaigns", {
        method: "POST",
        body: JSON.stringify({
          ...draft,
          max_redemptions: draft.max_redemptions ? Number(draft.max_redemptions) : null,
          starts_at: new Date(draft.starts_at).toISOString(),
          ends_at: new Date(draft.ends_at).toISOString(),
          reason: draft.reason.trim(),
        }),
      });
      setDraft(defaultDraft());
      await load();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(campaign: Campaign, status: CampaignStatus) {
    const reason = window.prompt(
      `确认将“${campaign.name}”设为${statusLabel[status]}，请输入操作理由：`,
    );
    if (!reason || reason.trim().length < 3) return;
    setChangingId(campaign.id);
    try {
      await api<Campaign>(`/admin/commerce/campaigns/${campaign.id}/status`, {
        method: "PUT",
        body: JSON.stringify({ status, reason: reason.trim() }),
      });
      await load();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setChangingId("");
    }
  }

  const label = campaigns?.credit_label ?? "叙点";
  return (
    <section className="panel stack campaignOpsPanel">
      <div className="entityToolbar">
        <div>
          <h2>
            <Gift size={19} aria-hidden="true" /> 运营赠点活动
          </h2>
          <p>每次领取只写入一笔不可变账本；活动可暂停或结束，但从不删除历史。</p>
        </div>
        <span className="statusPill live">无需支付通道</span>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <form className="campaignForm" onSubmit={(event) => void create(event)}>
        <label>
          内部代码
          <input
            value={draft.code}
            maxLength={48}
            onChange={(event) => setDraft({ ...draft, code: event.target.value })}
            required
          />
        </label>
        <label>
          玩家展示名称
          <input
            value={draft.name}
            maxLength={100}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            required
          />
        </label>
        <label>
          赠送 {label}
          <input
            type="number"
            min="1"
            value={draft.credit_amount}
            onChange={(event) =>
              setDraft({ ...draft, credit_amount: Number(event.target.value) || 1 })
            }
            required
          />
        </label>
        <label>
          初始状态
          <select
            value={draft.status}
            onChange={(event) =>
              setDraft({ ...draft, status: event.target.value as Draft["status"] })
            }
          >
            <option value="draft">草稿（不展示）</option>
            <option value="active">立即生效</option>
            <option value="paused">暂停（不展示）</option>
          </select>
        </label>
        <label>
          开始时间
          <input
            type="datetime-local"
            value={draft.starts_at}
            onChange={(event) => setDraft({ ...draft, starts_at: event.target.value })}
            required
          />
        </label>
        <label>
          结束时间
          <input
            type="datetime-local"
            value={draft.ends_at}
            onChange={(event) => setDraft({ ...draft, ends_at: event.target.value })}
            required
          />
        </label>
        <label>
          领取上限（留空为不限）
          <input
            type="number"
            min="1"
            value={draft.max_redemptions}
            onChange={(event) => setDraft({ ...draft, max_redemptions: event.target.value })}
          />
        </label>
        <label className="campaignDescription">
          玩家说明
          <input
            value={draft.description}
            maxLength={500}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          />
        </label>
        <div className="billingPolicySubmit campaignSubmit">
          <input
            className="input"
            value={draft.reason}
            minLength={3}
            maxLength={500}
            placeholder="创建理由（写入审计日志）"
            onChange={(event) => setDraft({ ...draft, reason: event.target.value })}
            required
          />
          <button className="button primary" disabled={saving}>
            {saving ? "正在创建…" : "创建活动"}
          </button>
        </div>
      </form>
      <div className="campaignOpsList">
        {campaigns?.items.length ? (
          campaigns.items.map((campaign) => (
            <article key={campaign.id}>
              <div>
                <div className="campaignTitle">
                  <b>{campaign.name}</b>
                  <span className={campaign.status === "active" ? "statusPill live" : "statusPill pending"}>
                    {statusLabel[campaign.status]}
                  </span>
                </div>
                <p>{campaign.description || "未填写玩家说明"}</p>
                <small>
                  {campaign.credit_amount.toLocaleString()} {label} · 已领 {campaign.redemption_count.toLocaleString()}
                  {campaign.max_redemptions === null
                    ? " / 不限"
                    : ` / 上限 ${campaign.max_redemptions.toLocaleString()}`} · 截止至 {new Date(campaign.ends_at).toLocaleString("zh-CN")}
                </small>
              </div>
              <div className="campaignActions">
                {campaign.status !== "active" && campaign.status !== "ended" && (
                  <button
                    className="button secondary"
                    type="button"
                    disabled={changingId === campaign.id}
                    onClick={() => void changeStatus(campaign, "active")}
                  >
                    启用
                  </button>
                )}
                {campaign.status === "active" && (
                  <button
                    className="button secondary"
                    type="button"
                    disabled={changingId === campaign.id}
                    onClick={() => void changeStatus(campaign, "paused")}
                  >
                    暂停
                  </button>
                )}
                {campaign.status !== "ended" && (
                  <button
                    className="button danger"
                    type="button"
                    disabled={changingId === campaign.id}
                    onClick={() => void changeStatus(campaign, "ended")}
                  >
                    结束
                  </button>
                )}
              </div>
            </article>
          ))
        ) : (
          <p className="emptyState">尚未创建赠点活动。</p>
        )}
      </div>
    </section>
  );
}
