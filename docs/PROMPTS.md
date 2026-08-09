# PROMPTS

所有 prompt 以文件形式版本化保存在 `prompts/`，由 `prompts/registry.py` 加载。
代码中**不内联 prompt 正文**。

## 文件清单

| 文件 | role | 输出 schema | 默认 temperature |
|---|---|---|---|
| `prompts/player_intent_v1.md` | `player_intent` | `PlayerIntent` | 0.2 |
| `prompts/npc_decision_v1.md` | `npc_decision` | `NPCDecision` | 0.7 |
| `prompts/director_v1.md` | `director` | `DirectorDecision` | 0.6 |
| `prompts/narrative_v1.md` | `narrative` | free text | 0.85 |
| `prompts/memory_v1.md` | `memory_extractor` | `MemoryExtraction` | 0.3 |

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
- Return ONLY a single JSON object. No prose, no markdown fences, no explanation.
- Never invent entity ids. Use only ids present in the provided context.
- Never assert world facts that are not in the provided context.
- If you cannot comply, return the documented fallback object.
```
