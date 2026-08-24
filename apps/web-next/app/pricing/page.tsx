"use client";

import { Check, CircleDollarSign, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type CatalogItem = {
  code: string;
  name: string;
  description: string;
  credits: number;
  price_minor: number;
  badge: string;
};

type Catalog = { currency: string; items: CatalogItem[]; checkout_live: boolean };

function formatMinorPrice(priceMinor: number, currency: string): string {
  const formatter = new Intl.NumberFormat("zh-CN", { style: "currency", currency });
  const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2;
  return formatter.format(priceMinor / 10 ** digits);
}

export default function PricingPage() {
  const [catalog, setCatalog] = useState<Catalog>();
  const [error, setError] = useState("");

  useEffect(() => {
    api<Catalog>("/commerce/catalog").then(setCatalog).catch((exception) => setError(exception.message));
  }, []);

  return (
    <div className="page pricingPage">
      <header className="pricingHero">
        <p className="eyebrow">清晰、可核验的权益规则</p>
        <h1>先看清价格，再决定是否继续。</h1>
        <p>平台托管模型按真实可核验的用量结算；使用自己的模型密钥（BYOK）时，不消耗平台叙点。</p>
        <div className="pricingSignals">
          <span>
            <ShieldCheck size={17} /> 失败或降级结果不计费
          </span>
          <span>
            <CircleDollarSign size={17} /> 余额变化逐笔留痕
          </span>
        </div>
      </header>

      <section className="pricingRules panel">
        <h2>当前购买状态</h2>
        <p className="statusPill pending">在线收款尚未开放</p>
        <p>
          套餐及价格会在这里先行公开审核；在支付签约、退款与拒付流程、税务规则以及服务端回调验收完成前，不会创建订单或发起扣款。
        </p>
      </section>

      <section className="pricingCatalog" aria-labelledby="pricing-catalog-title">
        <div className="landingSectionHead">
          <p className="eyebrow">公开套餐目录</p>
          <h2 id="pricing-catalog-title">叙点套餐</h2>
        </div>
        {error ? (
          <p className="error" role="alert">
            价格目录暂时无法加载：{error}
          </p>
        ) : catalog?.items.length ? (
          <div className="pricingCards">
            {catalog.items.map((item) => (
              <article key={item.code}>
                {item.badge && <span className="pricingBadge">{item.badge}</span>}
                <h3>{item.name}</h3>
                <strong>{formatMinorPrice(item.price_minor, catalog.currency)}</strong>
                <b>{item.credits.toLocaleString()} 叙点</b>
                <p>{item.description || "用于平台托管模型的可核验回合结算。"}</p>
                <small>
                  <Check size={14} /> 当前仅公开展示，不提供购买按钮
                </small>
              </article>
            ))}
          </div>
        ) : (
          <div className="panel emptyState">运营方尚未发布套餐；不会在此生成订单或扣款。</div>
        )}
      </section>

      <section className="pricingCta">
        <div>
          <h2>先体验，再决定。</h2>
          <p>浏览作品世界，或创建账号保存你的第一次选择。</p>
        </div>
        <div className="landingActions">
          <Link className="button primary" href="/register">
            免费注册
          </Link>
          <Link className="button landingSecondary" href="/library">
            浏览作品
          </Link>
        </div>
      </section>
    </div>
  );
}
