"use client";

import { FormEvent, useEffect, useState } from "react";
import { ChartNoAxesCombined } from "lucide-react";
import { api } from "@/lib/api";

type CommerceSummary = {
  credit_label: string;
  wallet_accounts: number;
  credits_issued: number;
  credits_settled: number;
  credits_outstanding: number;
  ledger_entries: number;
  net_credit_delta_30d: number;
  active_holds: number;
  credits_reserved: number;
  orders_by_status: Record<string, number>;
  checkout_live: boolean;
  billing_policy: BillingPolicy;
  campaigns_by_status: Record<string, number>;
};

type BillingPolicy = {
  mode: "disabled" | "wallet";
  enabled: boolean;
  credit_label: string;
  cost_microunits_per_credit: number;
  turn_reserve_credits: number;
  hold_minutes: number;
};

export default function CommerceOpsPanel() {
  const [summary, setSummary] = useState<CommerceSummary>();
  const [policy, setPolicy] = useState<BillingPolicy>();
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    const result = await api<CommerceSummary>("/admin/commerce/summary");
    setSummary(result);
    setPolicy(result.billing_policy);
    setError("");
  }

  useEffect(() => {
    api<CommerceSummary>("/admin/commerce/summary")
      .then((result) => {
        setSummary(result);
        setPolicy(result.billing_policy);
        setError("");
      })
      .catch((exception: Error) => setError(exception.message));
  }, []);

  async function savePolicy(event: FormEvent) {
    event.preventDefault();
    if (!policy || reason.trim().length < 3) return;
    setSaving(true);
    try {
      const saved = await api<BillingPolicy>("/admin/commerce/billing-policy", {
        method: "PUT",
        body: JSON.stringify({
          mode: policy.mode,
          credit_label: policy.credit_label,
          cost_microunits_per_credit: policy.cost_microunits_per_credit,
          turn_reserve_credits: policy.turn_reserve_credits,
          hold_minutes: policy.hold_minutes,
          reason: reason.trim(),
        }),
      });
      setPolicy(saved);
      setReason("");
      await load();
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel stack" id="commerce-operations">
      <div className="entityToolbar">
        <div>
          <h2>
            <ChartNoAxesCombined size={19} aria-hidden="true" /> 商业账本概览
          </h2>
          <p>仅聚合指标；不在运营首页暴露玩家身份或故事内容。</p>
        </div>
        <span className={summary?.checkout_live ? "statusPill live" : "statusPill pending"}>
          {summary?.checkout_live ? "支付已启用" : "支付待配置"}
        </span>
      </div>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : (
        <div className="commerceStats">
          <article>
            <span>有余额账户</span>
            <b>{(summary?.wallet_accounts ?? 0).toLocaleString()}</b>
          </article>
          <article>
            <span>累计发放</span>
            <b>{(summary?.credits_issued ?? 0).toLocaleString()}</b>
          </article>
          <article>
            <span>累计结算</span>
            <b>{(summary?.credits_settled ?? 0).toLocaleString()}</b>
          </article>
          <article>
            <span>在途权益</span>
            <b>{(summary?.credits_outstanding ?? 0).toLocaleString()}</b>
          </article>
          <article>
            <span>30 天净变动</span>
            <b>{(summary?.net_credit_delta_30d ?? 0).toLocaleString()}</b>
          </article>
          <article>
            <span>进行中预授权</span>
            <b>{(summary?.credits_reserved ?? 0).toLocaleString()}</b>
          </article>
          <article>
            <span>预授权回合</span>
            <b>{(summary?.active_holds ?? 0).toLocaleString()}</b>
          </article>
          <article>
            <span>进行中赠点活动</span>
            <b>{(summary?.campaigns_by_status?.active ?? 0).toLocaleString()}</b>
          </article>
        </div>
      )}
      <p className="studioHint">
        每项余额修正均要求管理员 MFA、CSRF、理由、幂等键和不可变审计记录；余额不能被调为负数。
      </p>
      {policy && (
        <form className="billingPolicyForm" onSubmit={(event) => void savePolicy(event)}>
          <div className="entityToolbar">
            <div>
              <h3>平台回合结算策略</h3>
              <p>保存会立即影响后续平台托管模型回合；BYOK 永远不使用平台叙点。</p>
            </div>
            <span className={policy.enabled ? "statusPill live" : "statusPill pending"}>
              {policy.enabled ? "已启用" : "已停用"}
            </span>
          </div>
          <div className="billingPolicyFields">
            <label>
              状态
              <select
                value={policy.mode}
                onChange={(event) =>
                  setPolicy({
                    ...policy,
                    mode: event.target.value as BillingPolicy["mode"],
                    enabled: event.target.value === "wallet",
                  })
                }
              >
                <option value="disabled">停用结算</option>
                <option value="wallet">启用叙点结算</option>
              </select>
            </label>
            <label>
              叙点名称
              <input
                value={policy.credit_label}
                maxLength={24}
                onChange={(event) => setPolicy({ ...policy, credit_label: event.target.value })}
              />
            </label>
            <label>
              每叙点微单位
              <input
                type="number"
                min="1"
                value={policy.cost_microunits_per_credit}
                onChange={(event) =>
                  setPolicy({
                    ...policy,
                    cost_microunits_per_credit: Number(event.target.value) || 1,
                  })
                }
              />
            </label>
            <label>
              单回合预留上限
              <input
                type="number"
                min="1"
                value={policy.turn_reserve_credits}
                onChange={(event) =>
                  setPolicy({ ...policy, turn_reserve_credits: Number(event.target.value) || 1 })
                }
              />
            </label>
            <label>
              预授权分钟数
              <input
                type="number"
                min="1"
                max="120"
                value={policy.hold_minutes}
                onChange={(event) =>
                  setPolicy({ ...policy, hold_minutes: Number(event.target.value) || 1 })
                }
              />
            </label>
          </div>
          <div className="billingPolicySubmit">
            <input
              className="input"
              value={reason}
              minLength={3}
              maxLength={500}
              placeholder="变更理由（写入审计日志）"
              onChange={(event) => setReason(event.target.value)}
              required
            />
            <button className="button primary" disabled={saving}>
              {saving ? "正在保存…" : "保存结算策略"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
