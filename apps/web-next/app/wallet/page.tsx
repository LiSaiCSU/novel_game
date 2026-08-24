"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CircleDollarSign, Gift, History, Sparkles } from "lucide-react";
import { api } from "@/lib/api";

type WalletEntry = {
  id: string;
  credit_delta: number;
  entry_type: string;
  source_type: string;
  reason: string;
  expires_at: string | null;
  created_at: string;
};

type Wallet = {
  credit_label: string;
  balance: number;
  available_balance: number;
  reserved_credits: number;
  billing_policy: {
    mode: "disabled" | "wallet";
    enabled: boolean;
    credit_label: string;
    cost_microunits_per_credit: number;
    turn_reserve_credits: number;
    hold_minutes: number;
  };
  entries: WalletEntry[];
  total: number;
};

type CatalogItem = {
  code: string;
  name: string;
  description: string;
  credits: number;
  price_minor: number;
  badge: string;
  active: boolean;
};

type Catalog = {
  currency: string;
  items: CatalogItem[];
  checkout_live: boolean;
};

type Campaign = {
  id: string;
  code: string;
  name: string;
  description: string;
  credit_amount: number;
  ends_at: string;
  redemptions_remaining: number | null;
};

type Campaigns = {
  credit_label: string;
  items: Campaign[];
};

const entryLabels: Record<string, string> = {
  grant: "权益发放",
  adjustment: "余额调整",
  refund: "退款返还",
  reversal: "冲正",
  usage: "模型服务结算",
  payment: "充值到账",
};

function formatMinorPrice(priceMinor: number, currency: string): string {
  const formatter = new Intl.NumberFormat("zh-CN", { style: "currency", currency });
  const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2;
  return formatter.format(priceMinor / 10 ** digits);
}

export default function WalletPage() {
  const [wallet, setWallet] = useState<Wallet>();
  const [catalog, setCatalog] = useState<Catalog>();
  const [campaigns, setCampaigns] = useState<Campaigns>();
  const [error, setError] = useState("");
  const [campaignError, setCampaignError] = useState("");
  const [claimingCode, setClaimingCode] = useState("");
  const [campaignMessage, setCampaignMessage] = useState("");

  async function loadWallet() {
    const result = await api<Wallet>("/commerce/wallet");
    setWallet(result);
    setError("");
  }

  async function loadCampaigns() {
    const result = await api<Campaigns>("/commerce/campaigns");
    setCampaigns(result);
    setCampaignError("");
  }

  useEffect(() => {
    api<Wallet>("/commerce/wallet")
      .then((result) => {
        setWallet(result);
        setError("");
      })
      .catch((exception) => setError(exception.message));
  }, []);

  useEffect(() => {
    // Pricing remains readable even if the signed-in wallet request fails.
    api<Catalog>("/commerce/catalog").then(setCatalog).catch(() => undefined);
  }, []);

  useEffect(() => {
    api<Campaigns>("/commerce/campaigns")
      .then((result) => {
        setCampaigns(result);
        setCampaignError("");
      })
      .catch((exception) => setCampaignError(exception.message));
  }, []);

  async function claimCampaign(code: string) {
    setClaimingCode(code);
    setCampaignMessage("");
    try {
      const result = await api<{ idempotent_replay: boolean; credit_delta: number }>(
        `/commerce/campaigns/${encodeURIComponent(code)}/redeem`,
        { method: "POST" },
      );
      setCampaignMessage(
        result.idempotent_replay ? "这份活动权益已经到账。" : `已领取 +${result.credit_delta.toLocaleString()} ${wallet?.credit_label ?? "叙点"}。`,
      );
      await Promise.all([loadWallet(), loadCampaigns()]);
    } catch (exception) {
      setCampaignError((exception as Error).message);
    } finally {
      setClaimingCode("");
    }
  }

  if (error) {
    return (
      <div className="page narrowPage">
        <section className="panel stack">
          <h1>余额中心</h1>
          <p className="error" role="alert">
            {error}
          </p>
          <Link className="button primary" href="/login">
            登录后查看余额
          </Link>
        </section>
      </div>
    );
  }

  return (
    <div className="page walletPage">
      <div className="pageHead walletHead">
        <div>
          <p className="eyebrow">账户与权益</p>
          <h1>余额中心</h1>
          <p>清楚查看平台托管模型的权益记录；使用自带密钥（BYOK）时不消耗叙点。</p>
        </div>
        <CircleDollarSign size={42} aria-hidden="true" />
      </div>

      <section className="walletHero">
        <div>
          <span>可用{wallet?.credit_label ?? "叙点"}</span>
          <b>{(wallet?.available_balance ?? 0).toLocaleString()}</b>
          <small>
            账面余额 {(wallet?.balance ?? 0).toLocaleString()}；
            {wallet?.reserved_credits
              ? ` ${wallet.reserved_credits.toLocaleString()} 已为进行中的回合预留。`
              : " 当前没有进行中的预授权。"}
          </small>
        </div>
        <div className="walletHeroNote">
          <Sparkles size={18} aria-hidden="true" />
          <span>支付通道会在主体、地区与结算规则配置并验收后开放；当前不会在此页发起扣款。</span>
        </div>
      </section>

      <section className="panel stack walletCatalog">
        <div className="entityToolbar">
          <div>
            <h2>叙点套餐与公开定价</h2>
            <p>套餐、叙点数量和价格在创建订单前公开展示；当前尚未开放在线收款。</p>
          </div>
          <span className="statusPill pending">暂不支持购买</span>
        </div>
        {catalog?.items.length ? (
          <div className="walletPackages">
            {catalog.items.map((item) => (
              <article key={item.code}>
                <div>
                  <div className="packageTitle">
                    <b>{item.name}</b>
                    {item.badge && <span>{item.badge}</span>}
                  </div>
                  <p>{item.description || "用于平台托管模型的可核验回合结算。"}</p>
                  <small>{item.credits.toLocaleString()} {wallet?.credit_label ?? "叙点"}</small>
                </div>
                <strong>{formatMinorPrice(item.price_minor, catalog.currency)}</strong>
              </article>
            ))}
          </div>
        ) : (
          <p className="emptyState">运营方尚未发布可购买套餐；不会在这里生成订单或扣款。</p>
        )}
        <p className="studioHint">
          支付渠道须先完成签约、地区与税务配置、退款/拒付流程、服务条款披露，以及服务端签名回调验收后才会开放。
        </p>
      </section>

      {(campaigns?.items.length || campaignError || campaignMessage) && (
        <section className="panel stack walletCampaigns">
          <div className="entityToolbar">
            <div>
              <h2>
                <Gift size={19} aria-hidden="true" /> 可领取活动权益
              </h2>
              <p>每项活动每个账号仅能领取一次，到账记录会永久显示在余额明细中。</p>
            </div>
            <span className="statusPill live">无需支付</span>
          </div>
          {campaignMessage && <p className="success" role="status">{campaignMessage}</p>}
          {campaignError && <p className="error" role="alert">{campaignError}</p>}
          {campaigns?.items.length ? (
            <div className="walletCampaignList">
              {campaigns.items.map((campaign) => (
                <article key={campaign.id}>
                  <div>
                    <b>{campaign.name}</b>
                    <p>{campaign.description || "活动权益将在领取后立即入账。"}</p>
                    <small>
                      +{campaign.credit_amount.toLocaleString()} {campaigns.credit_label} · 截止至{" "}
                      {new Date(campaign.ends_at).toLocaleString("zh-CN")}
                      {campaign.redemptions_remaining === null
                        ? ""
                        : ` · 剩余 ${campaign.redemptions_remaining.toLocaleString()} 份`}
                    </small>
                  </div>
                  <button
                    className="button primary"
                    disabled={claimingCode === campaign.code}
                    onClick={() => void claimCampaign(campaign.code)}
                  >
                    {claimingCode === campaign.code ? "正在领取…" : "领取权益"}
                  </button>
                </article>
              ))}
            </div>
          ) : (
            !campaignError && <p className="emptyState">目前没有可领取的活动权益。</p>
          )}
        </section>
      )}

      <div className="walletGrid">
        <section className="panel stack">
          <div className="entityToolbar">
            <div>
              <h2>收费说明</h2>
              <p>计费开关、预授权上限和失败不收费规则都在这里透明展示。</p>
            </div>
          </div>
          <ol className="walletRules">
            <li>平台托管模型按实际、可核验的用量结算；失败或降级结果不应计入付费消耗。</li>
            {wallet?.billing_policy?.enabled ? (
              <li>
                当前已启用回合预授权：每次平台模型回合最多预留{" "}
                {wallet.billing_policy.turn_reserve_credits.toLocaleString()} {wallet.credit_label}
                ， 最终按实际模型用量结算，最长 {wallet.billing_policy.hold_minutes}{" "}
                分钟后自动释放。
              </li>
            ) : (
              <li>当前未启用平台托管模型的叙点结算；开始游戏前不会冻结或扣减余额。</li>
            )}
            <li>充值、赠送、退款、冲正和消耗都生成独立记录，余额从记录汇总而来。</li>
            <li>BYOK 直接使用你的模型服务商额度，不消耗平台叙点。</li>
          </ol>
        </section>

        <section className="panel stack">
          <div className="entityToolbar">
            <div>
              <h2>支付状态</h2>
              <p>支付不是一个占位按钮，而是一条可审计的结算链路。</p>
            </div>
          </div>
          <p className={wallet?.billing_policy?.enabled ? "statusPill live" : "statusPill pending"}>
            {wallet?.billing_policy?.enabled ? "回合结算已启用" : "回合结算未启用"}
          </p>
          <p className="studioHint">
            运营方会先完成支付商签约、回调验签、退款/拒付处理、发票与税务规则，再向玩家开放充值。
          </p>
        </section>
      </div>

      <section className="panel stack walletLedger">
        <div className="entityToolbar">
          <div>
            <h2>
              <History size={19} aria-hidden="true" /> 余额明细
            </h2>
            <p>
              最近 {wallet?.entries.length ?? 0} / {wallet?.total ?? 0} 条记录
            </p>
          </div>
        </div>
        {wallet?.entries.length ? (
          <div className="walletEntries">
            {wallet.entries.map((entry) => (
              <article key={entry.id}>
                <div>
                  <b>{entryLabels[entry.entry_type] ?? entry.entry_type}</b>
                  <span>{entry.reason || "账户变动"}</span>
                  <small>{new Date(entry.created_at).toLocaleString("zh-CN")}</small>
                </div>
                <strong className={entry.credit_delta > 0 ? "creditPlus" : "creditMinus"}>
                  {entry.credit_delta > 0 ? "+" : ""}
                  {entry.credit_delta.toLocaleString()}
                </strong>
              </article>
            ))}
          </div>
        ) : (
          <p className="emptyState">
            暂无余额变动。体验权益、充值到账或模型服务结算都会显示在这里。
          </p>
        )}
      </section>
    </div>
  );
}
