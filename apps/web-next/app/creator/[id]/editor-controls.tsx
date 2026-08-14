"use client";

import { useState } from "react";
import { clone, type Entity } from "./editor-types";

export function Field({
  label,
  value,
  onChange,
  multiline = false,
}: {
  label: string;
  value: unknown;
  onChange: (value: string) => void;
  multiline?: boolean;
}) {
  return (
    <label className="studioField">
      <span>{label}</span>
      {multiline ? (
        <textarea
          className="textarea"
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          className="input"
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </label>
  );
}

export function EntityList({
  items,
  kind,
  onChange,
  fields,
}: {
  items: Entity[];
  kind: string;
  onChange: (items: Entity[]) => void;
  fields: Array<[string, string, boolean?]>;
}) {
  function add() {
    const prefix: Record<string, string> = {
      地点: "location",
      人物: "character",
      事实: "fact",
      剧情线: "plot_thread",
      任务: "quest",
    };
    const key = `${prefix[kind] ?? "entity"}_${items.length + 1}`;
    onChange([
      ...items,
      kind === "事实"
        ? { key, statement: `新${kind}`, sensitivity: 0 }
        : { key, name: `新${kind}`, description: "" },
    ]);
  }
  return (
    <div className="entityWorkspace">
      <div className="entityToolbar">
        <p>{items.length} 项</p>
        <button className="button" onClick={add}>
          添加{kind}
        </button>
      </div>
      {items.length === 0 && (
        <div className="empty">
          <p>还没有{kind}。从一个最重要的对象开始，系统会实时检查引用。</p>
        </div>
      )}
      {items.map((item, index) => (
        <article className="entityCard" key={item.key}>
          <header>
            <code>{item.key}</code>
            <button
              className="dangerLink"
              onClick={() => onChange(items.filter((_, i) => i !== index))}
            >
              删除
            </button>
          </header>
          <div className="formGrid">
            {fields.map(([key, label, multiline]) => (
              <Field
                key={key}
                label={label}
                value={item[key]}
                multiline={multiline}
                onChange={(value) => {
                  const next = clone(items);
                  next[index][key] = ["age", "sensitivity"].includes(key) ? Number(value) : value;
                  onChange(next);
                }}
              />
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

export function JsonEditor({
  value,
  onApply,
  label,
}: {
  value: unknown;
  onApply: (value: unknown) => void;
  label: string;
}) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  return (
    <textarea
      className="editor"
      aria-label={label}
      value={text}
      onChange={(event) => setText(event.target.value)}
      onBlur={() => {
        try {
          onApply(JSON.parse(text) as unknown);
        } catch {
          /* keep draft until valid */
        }
      }}
    />
  );
}
