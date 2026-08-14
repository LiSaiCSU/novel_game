"use client";

import { useMemo, useState } from "react";
import { EntityList, Field, JsonEditor } from "./editor-controls";
import { clone, type EndingDefinition, type Entity } from "./editor-types";

export function LocationWorkspace({
  items,
  startLocation,
  onChange,
}: {
  items: Entity[];
  startLocation: string;
  onChange: (items: Entity[]) => void;
}) {
  const [from, setFrom] = useState(items[0]?.key ?? "");
  const [to, setTo] = useState(items[1]?.key ?? "");
  const [minutes, setMinutes] = useState(10);
  const positions = useMemo(
    () =>
      Object.fromEntries(
        items.map((item, index) => [
          item.key,
          { x: 90 + (index % 3) * 250, y: 60 + Math.floor(index / 3) * 105 },
        ]),
      ),
    [items],
  );
  const edges = useMemo(() => {
    const found = new Map<string, { from: string; to: string; minutes: number }>();
    for (const item of items) {
      const travel = (item.travel ?? {}) as Record<string, unknown>;
      for (const [target, duration] of Object.entries(travel)) {
        if (!positions[target]) continue;
        const edgeKey = [item.key, target].sort().join("::");
        if (!found.has(edgeKey))
          found.set(edgeKey, { from: item.key, to: target, minutes: Number(duration) || 0 });
      }
    }
    return [...found.values()];
  }, [items, positions]);
  const height = Math.max(180, 125 + Math.ceil(items.length / 3) * 105);

  function connect() {
    if (!from || !to || from === to) return;
    const next = clone(items);
    for (const [source, target] of [
      [from, to],
      [to, from],
    ]) {
      const item = next.find((entry) => entry.key === source);
      if (!item) continue;
      item.travel = {
        ...((item.travel ?? {}) as Record<string, unknown>),
        [target]: Math.max(1, minutes),
      };
    }
    onChange(next);
  }

  function disconnect(edge: { from: string; to: string }) {
    const next = clone(items);
    for (const [source, target] of [
      [edge.from, edge.to],
      [edge.to, edge.from],
    ]) {
      const item = next.find((entry) => entry.key === source);
      const travel = { ...((item?.travel ?? {}) as Record<string, unknown>) };
      delete travel[target];
      if (item) item.travel = travel;
    }
    onChange(next);
  }

  return (
    <div className="entityWorkspace">
      <section className="mapPanel">
        <header>
          <div>
            <p className="eyebrow">LOCATION GRAPH</p>
            <h2>地点关系图</h2>
          </div>
          <span>
            {items.length} 个节点 · {edges.length} 条通路
          </span>
        </header>
        {items.length ? (
          <svg
            className="locationMap"
            viewBox={`0 0 760 ${height}`}
            role="img"
            aria-label="地点和双向通路关系图"
          >
            {edges.map((edge) => {
              const a = positions[edge.from],
                b = positions[edge.to];
              return (
                <g key={`${edge.from}-${edge.to}`}>
                  <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
                  <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 5}>
                    {edge.minutes} 分
                  </text>
                </g>
              );
            })}
            {items.map((item) => {
              const point = positions[item.key];
              return (
                <g
                  className={item.key === startLocation ? "startNode" : ""}
                  key={item.key}
                  transform={`translate(${point.x - 78} ${point.y - 25})`}
                >
                  <rect width="156" height="50" rx="12" />
                  <text x="78" y="21" textAnchor="middle">
                    {String(item.name ?? item.key).slice(0, 12)}
                  </text>
                  <text className="nodeKey" x="78" y="38" textAnchor="middle">
                    {item.key.slice(0, 20)}
                  </text>
                </g>
              );
            })}
          </svg>
        ) : (
          <div className="empty">添加地点后会在这里形成可达性图。</div>
        )}
        <div className="connectionEditor">
          <select className="select" value={from} onChange={(event) => setFrom(event.target.value)}>
            {items.map((item) => (
              <option key={item.key} value={item.key}>
                {String(item.name ?? item.key)}
              </option>
            ))}
          </select>
          <span>⇄</span>
          <select className="select" value={to} onChange={(event) => setTo(event.target.value)}>
            {items.map((item) => (
              <option key={item.key} value={item.key}>
                {String(item.name ?? item.key)}
              </option>
            ))}
          </select>
          <input
            className="input"
            aria-label="通行分钟"
            type="number"
            min="1"
            max="1440"
            value={minutes}
            onChange={(event) => setMinutes(Number(event.target.value))}
          />
          <button className="button" onClick={connect}>
            添加双向通路
          </button>
        </div>
        <div className="edgeList">
          {edges.map((edge) => (
            <button
              key={`${edge.from}-${edge.to}`}
              onClick={() => disconnect(edge)}
              title="删除这条双向通路"
            >
              {String(items.find((item) => item.key === edge.from)?.name ?? edge.from)} ⇄{" "}
              {String(items.find((item) => item.key === edge.to)?.name ?? edge.to)} · {edge.minutes}{" "}
              分 <span>×</span>
            </button>
          ))}
        </div>
      </section>
      <EntityList
        kind="地点"
        items={items}
        fields={[
          ["name", "显示名称"],
          ["type", "地点类型"],
          ["parent", "父级地点 key"],
          ["description", "场景描述", true],
        ]}
        onChange={onChange}
      />
    </div>
  );
}

export function KnowledgeStudio({
  facts,
  characters,
  onChange,
}: {
  facts: Entity[];
  characters: Entity[];
  onChange: (facts: Entity[]) => void;
}) {
  const actors = [
    { key: "player", name: "玩家" },
    ...characters.map((character) => ({
      key: character.key,
      name: String(character.name ?? character.key),
    })),
  ];
  function knowledge(fact: Entity, actor: string) {
    const map = (fact.initial_knowledge ?? {}) as Record<string, Record<string, unknown>>;
    return String(map[actor]?.state ?? "UNKNOWN");
  }
  function setKnowledge(factIndex: number, actor: string, state: string) {
    const next = clone(facts);
    const map = {
      ...((next[factIndex].initial_knowledge ?? {}) as Record<string, Record<string, unknown>>),
    };
    if (state === "UNKNOWN") delete map[actor];
    else
      map[actor] = {
        ...(map[actor] ?? {}),
        state,
        confidence: state === "KNOWN" ? 1 : 0.6,
        source: map[actor]?.source ?? "DOCUMENT",
      };
    next[factIndex].initial_knowledge = map;
    onChange(next);
  }
  return (
    <div className="entityWorkspace">
      <section className="knowledgePanel">
        <div className="entityToolbar">
          <div>
            <p className="eyebrow">KNOWLEDGE BOUNDARIES</p>
            <h2>知识与秘密矩阵</h2>
          </div>
          <p>未知 / 怀疑 / 已知</p>
        </div>
        <p className="studioHint">
          这里定义开局时谁知道什么。运行时只会把角色已知的信息交给模型，秘密不会因为同处一个内容包而泄露。
        </p>
        <div className="knowledgeTable">
          <table>
            <thead>
              <tr>
                <th>事实</th>
                {actors.map((actor) => (
                  <th key={actor.key}>{actor.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {facts.map((fact, factIndex) => (
                <tr key={fact.key}>
                  <th title={String(fact.statement ?? fact.key)}>
                    {String(fact.name ?? fact.statement ?? fact.key).slice(0, 22)}
                  </th>
                  {actors.map((actor) => (
                    <td key={actor.key}>
                      <select
                        aria-label={`${String(fact.statement ?? fact.key)}：${actor.name}`}
                        value={knowledge(fact, actor.key)}
                        onChange={(event) => setKnowledge(factIndex, actor.key, event.target.value)}
                      >
                        <option value="UNKNOWN">未知</option>
                        <option value="SUSPECTED">怀疑</option>
                        <option value="KNOWN">已知</option>
                      </select>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <EntityList
        kind="事实"
        items={facts}
        fields={[
          ["statement", "事实内容", true],
          ["scope", "作用域"],
          ["sensitivity", "敏感度 0–1"],
        ]}
        onChange={onChange}
      />
    </div>
  );
}

export function EndingStudio({
  endings,
  characters,
  onChange,
}: {
  endings: EndingDefinition[];
  characters: Entity[];
  onChange: (endings: EndingDefinition[]) => void;
}) {
  function add() {
    onChange([
      ...endings,
      {
        key: `ending_${endings.length + 1}`,
        title: "新结局",
        type: "other",
        condition: false,
        hidden_until_available: true,
        priority: 0,
        epilogue: "请写下这个结局发生后的余韵。",
      },
    ]);
  }
  function update(index: number, patch: Partial<EndingDefinition>) {
    const next = clone(endings);
    next[index] = { ...next[index], ...patch };
    onChange(next);
  }
  return (
    <div className="entityWorkspace">
      <div className="entityToolbar">
        <div>
          <p className="studioHint">
            结局资格由受限条件 AST
            对真实游戏状态判定，模型无法擅自发放结局。恋爱结局强制要求玩家明确同意。
          </p>
        </div>
        <button className="button" onClick={add}>
          添加结局
        </button>
      </div>
      {endings.map((ending, index) => (
        <article className="entityCard endingEditorCard" key={ending.key}>
          <header>
            <code>{ending.key}</code>
            <button
              className="dangerLink"
              onClick={() => onChange(endings.filter((_, itemIndex) => itemIndex !== index))}
            >
              删除
            </button>
          </header>
          <div className="formGrid">
            <Field
              label="结局标题"
              value={ending.title}
              onChange={(value) => update(index, { title: value })}
            />
            <label className="studioField">
              <span>类型</span>
              <select
                className="select"
                value={ending.type}
                onChange={(event) => {
                  const type = event.target.value as EndingDefinition["type"];
                  update(index, {
                    type,
                    requires_consent: type === "romance" ? true : ending.requires_consent,
                  });
                }}
              >
                <option value="romance">恋爱</option>
                <option value="bond">深度羁绊</option>
                <option value="independent">独立成长</option>
                <option value="other">其他</option>
              </select>
            </label>
            <label className="studioField">
              <span>关联人物</span>
              <select
                className="select"
                value={ending.lead ?? ""}
                onChange={(event) => update(index, { lead: event.target.value || null })}
              >
                <option value="">无</option>
                {characters.map((character) => (
                  <option key={character.key} value={character.key}>
                    {String(character.name ?? character.key)}
                  </option>
                ))}
              </select>
            </label>
            <Field
              label="优先级"
              value={ending.priority ?? 0}
              onChange={(value) => update(index, { priority: Number(value) })}
            />
            <label className="checkField">
              <input
                type="checkbox"
                checked={ending.requires_consent ?? false}
                disabled={ending.type === "romance"}
                onChange={(event) => update(index, { requires_consent: event.target.checked })}
              />
              需要明确关系同意
            </label>
            <label className="checkField">
              <input
                type="checkbox"
                checked={ending.hidden_until_available ?? true}
                onChange={(event) =>
                  update(index, { hidden_until_available: event.target.checked })
                }
              />
              达成前隐藏标题
            </label>
            <Field
              label="结局尾声"
              value={ending.epilogue}
              multiline
              onChange={(value) => update(index, { epilogue: value })}
            />
            <label className="studioField conditionField">
              <span>达成条件（受限表达式 AST）</span>
              <JsonEditor
                label={`${ending.title}达成条件`}
                value={ending.condition}
                onApply={(value) => update(index, { condition: value })}
              />
            </label>
          </div>
        </article>
      ))}
      {!endings.length && (
        <div className="empty">
          还没有结局。至少设计一个独立成长结局，让恋爱选择不是完成作品的前提。
        </div>
      )}
    </div>
  );
}
