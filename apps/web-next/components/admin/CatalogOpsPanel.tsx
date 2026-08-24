"use client";

import { FormEvent, useEffect, useState } from "react";
import { Plus, Tags, Trash2 } from "lucide-react";
import { api } from "@/lib/api";

type CatalogItem = {
  code: string;
  name: string;
  description: string;
  credits: number;
  price_minor: number;
  badge: string;
  sort_order: number;
  active: boolean;
};

type Catalog = {
  currency: string;
  items: CatalogItem[];
  checkout_live: false;
};

function emptyItem(index: number): CatalogItem {
  return {
    code: `package_${index + 1}`,
    name: "新套餐",
    description: "用于平台托管模型的可核验回合结算。",
    credits: 100,
    price_minor: 1000,
    badge: "",
    sort_order: (index + 1) * 10,
    active: false,
  };
}

export default function CatalogOpsPanel() {
  const [catalog, setCatalog] = useState<Catalog>();
  const [currency, setCurrency] = useState("CNY");
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Catalog>("/admin/commerce/catalog")
      .then((result) => {
        setCatalog(result);
        setCurrency(result.currency);
        setItems(result.items);
      })
      .catch((exception: Error) => setError(exception.message));
  }, []);

  function updateItem(index: number, patch: Partial<CatalogItem>) {
    setItems((current) =>
      current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)),
    );
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (reason.trim().length < 3) return;
    setSaving(true);
    try {
      const saved = await api<Catalog>("/admin/commerce/catalog", {
        method: "PUT",
        body: JSON.stringify({ currency, items, reason: reason.trim() }),
      });
      setCatalog(saved);
      setCurrency(saved.currency);
      setItems(saved.items);
      setReason("");
      setError("");
    } catch (exception) {
      setError((exception as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const activeCount = items.filter((item) => item.active).length;

  return (
    <section className="panel stack catalogOpsPanel">
      <div className="entityToolbar">
        <div>
          <h2>
            <Tags size={19} aria-hidden="true" /> 叙点套餐目录
          </h2>
          <p>价格先公开审核；在主体、地区、税务、退款和签名回调全部就绪前，始终不创建支付订单。</p>
        </div>
        <span className="statusPill pending">收款待接入</span>
      </div>
      <p className="studioHint">
        当前已配置 {catalog?.items.length ?? 0} 个套餐，其中 {activeCount} 个对玩家可见。金额使用货币最小单位：CNY 1000 表示 ¥10.00。
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <form className="catalogForm" onSubmit={(event) => void save(event)}>
        <label className="catalogCurrency">
          结算货币（ISO 4217）
          <input value={currency} maxLength={3} onChange={(event) => setCurrency(event.target.value)} />
        </label>
        <div className="catalogRows">
          {items.map((item, index) => (
            <fieldset className="catalogRow" key={`${item.code}-${index}`}>
              <legend>套餐 {index + 1}</legend>
              <button
                className="iconButton catalogDelete"
                type="button"
                aria-label={`删除套餐 ${item.name}`}
                onClick={() => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index))}
              >
                <Trash2 size={16} />
              </button>
              <label>
                内部代码
                <input
                  value={item.code}
                  maxLength={48}
                  onChange={(event) => updateItem(index, { code: event.target.value })}
                />
              </label>
              <label>
                展示名称
                <input
                  value={item.name}
                  maxLength={80}
                  onChange={(event) => updateItem(index, { name: event.target.value })}
                />
              </label>
              <label>
                叙点数量
                <input
                  type="number"
                  min="1"
                  value={item.credits}
                  onChange={(event) => updateItem(index, { credits: Number(event.target.value) || 1 })}
                />
              </label>
              <label>
                价格（最小单位）
                <input
                  type="number"
                  min="1"
                  value={item.price_minor}
                  onChange={(event) => updateItem(index, { price_minor: Number(event.target.value) || 1 })}
                />
              </label>
              <label>
                排序
                <input
                  type="number"
                  min="0"
                  value={item.sort_order}
                  onChange={(event) => updateItem(index, { sort_order: Number(event.target.value) || 0 })}
                />
              </label>
              <label>
                标签（可选）
                <input
                  value={item.badge}
                  maxLength={36}
                  onChange={(event) => updateItem(index, { badge: event.target.value })}
                />
              </label>
              <label className="catalogDescription">
                玩家说明
                <input
                  value={item.description}
                  maxLength={240}
                  onChange={(event) => updateItem(index, { description: event.target.value })}
                />
              </label>
              <label className="catalogActive">
                <input
                  type="checkbox"
                  checked={item.active}
                  onChange={(event) => updateItem(index, { active: event.target.checked })}
                />
                对玩家公开
              </label>
            </fieldset>
          ))}
        </div>
        <button
          className="button secondary catalogAdd"
          type="button"
          disabled={items.length >= 24}
          onClick={() => setItems((current) => [...current, emptyItem(current.length)])}
        >
          <Plus size={16} /> 新增套餐
        </button>
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
            {saving ? "正在保存…" : "保存套餐目录"}
          </button>
        </div>
      </form>
    </section>
  );
}
