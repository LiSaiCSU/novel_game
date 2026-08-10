# PROMPTS

所有 prompt 以文件形式版本化保存在 `prompts/`，由 `prompts/registry.py` 加载。
代码中**不内联 prompt 正文**。

所有面向 LLM 的控制说明使用中文；JSON 字段名、枚举值与实体 key 保持机器协议原文。
结构化输出失败后的 repair instruction 同样使用中文，避免修复轮次把英文语气带入后续输出。

## 文件清单

| 文件 | role | 输出 schema | 默认 temperature |
|---|---|---|---|
| `prompts/player_intent_v1.md` | `player_intent` | `PlayerIntent` | 0.2 |
| `prompts/npc_decision_v1.md` | `npc_decision` | `NPCDecision` | 0.7 |
| `prompts/director_v1.md` | `director` | `DirectorDecision` | 0.6 |
| `prompts/narrative_v1.md` | `narrative` | free text | 0.85 |
| `prompts/memory_v1.md` | `memory_extractor` | `MemoryExtraction` | 0.3 |
| `prompts/structured_repair_v1.md` | `structured_repair` | 目标 schema | 0.0 |

## Front-matter 规范

```yaml
---
role: npc_decision
version: v1
output_schema: NPCDecision
temperature: 0.7
max_output_tokens: 900
---
```

正文中用 `{{variable}}` 占位，由 `PromptRegistry.render(role, version, **vars)` 填充。
未提供的占位符会抛 `PromptRenderError`（防止悄悄发出带 `{{}}` 的 prompt）。

## 记录内容（§46）

每次 LLM 调用写入 `turn_traces.llm_calls[]`：

```jsonc
{
  "role": "npc_decision",
  "prompt_version": "v1",
  "provider": "anthropic",
  "model": "<from .env>",
  "temperature": 0.7,
  "prompt_tokens": 1832,
  "completion_tokens": 214,
  "latency_ms": 940,
  "attempts": 1,
  "repaired": false,
  "valid": true
}
```

便于按 `prompt_version` 做 A/B 对比。新增 `_v2.md` 后，通过
`.env` 的 `PROMPT_VERSION_NPC_DECISION=v2` 切换，无需改代码。

## 通用硬约束（注入到所有非叙事 prompt 尾部）

`prompts/_common_constraints.md`：

```text
- 只返回一个 JSON 对象，不要输出散文、Markdown 代码围栏或解释。
- 不得编造实体 id，只能使用上下文中出现过的 id。
- 不得断言上下文中不存在的世界事实。
- 若无法遵守，返回该角色约定的兜底对象。
```
