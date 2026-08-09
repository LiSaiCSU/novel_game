# AI_PIPELINE

AI 在本系统中的**唯一合法职责**：理解意图、模拟人物决策、判断剧情时机、文学表达。
AI **没有**世界事实的最终决定权。

---

## 1. Agent 清单

| Agent | 输入 | 输出 | 模型档 | 可否改世界 |
|---|---|---|---|---|
| IntentParser | 玩家原文 + 可见场景摘要 + 可用动作词表 | `PlayerIntent`(严格 JSON) | fast | ❌ |
| NPCAgent | NPCContext（只含该 NPC 知道的信息） | `NPCDecision`(proposal) | medium / strong | ❌ 仅提案 |
| Director | DirectorContext（世界摘要 + 线程 + 张力） | `DirectorDecision`(proposal) | strong | ❌ 仅提案 |
| MemoryExtractor | 已结算事件 + 参与者 + 相似记忆 | `MemoryExtraction` | fast | ❌ 仅提案 |
| NarrativeRenderer | 已提交事实 | 中文小说文本 | medium/strong | ❌ |
| Embedder | 记忆摘要 | float[] | embedding | ❌ |

**没有任何 Agent 拿到数据库写句柄**（D-008，`tests/unit/test_engine_purity.py` 强制）。

---

## 2. IntentParser（§21）

职责只有一件事：自然语言 → `Action`。

必须正确处理：复合行为 / 模糊行为 / 欺骗 / 套话 / 隐瞒 / 观察 / 试探 / 条件行为。

```jsonc
{
  "action_type": "CONVERSATION",
  "actor_id": "player",
  "target_id": "npc_shopkeeper_001",
  "method": "indirect_questioning",
  "style": "pretend_drunk",
  "goal": {"type": "obtain_information", "topic": "soul_devouring_grass_purchase"},
  "secondary_actions": [{"type": "DRINK"}],
  "condition": {"trigger": "guard_looks_away", "then_action_type": "SNEAK"},
  "raw_text": "…",
  "confidence": 0.86,
  "ambiguity": null
}
```

约束：
- 只能引用**上下文中真实存在**的 `target_id`（解析后做存在性校验，不存在 → `ambiguity` + 请求澄清）。
- 不得输出成功/失败、不得描述结果、不得决定 NPC 反应。
- `confidence < 0.45` 或 `ambiguity != null` → Orchestrator 走澄清分支（不推进世界时间）。

Fallback：`engine/actions/fallback_parser.py`，基于内容包别名词表 + 动词模式匹配，
覆盖 MOVE/TALK/ASK/OBSERVE/SEARCH/CULTIVATE/BREAKTHROUGH/USE_ITEM/ATTACK/REST/WAIT 等。

---

## 3. NPCAgent（§19/§20）

上下文（`ContextBuilder.build_npc_context`）：

```text
Identity  Personality  Values  Goals  CurrentEmotion
CurrentSituation(场景/在场者/时间/氛围)
Relationships(仅与在场者)
KnownFacts(仅 character_knowledge，附 confidence 措辞降级)
RelevantMemories(复合排序 Top-K)
AvailableActions(规则允许的动作白名单)
RecentEvents(该 NPC 感知得到的)
```

输出：

```jsonc
{
  "reasoning_summary": "…",
  "decision": {"action_type": "REFUSE", "target": "player", "parameters": {}},
  "speech_intent": "冷淡拒绝，但不撕破脸",
  "emotion_update": {"dominant": "wary", "intensity": 0.4},
  "relationship_change_proposal": {"player": {"trust": -2, "suspicion": +4}},
  "goal_update_proposal": null
}
```

**校验链**：pydantic → `action_type ∈ AvailableActions` → 目标存在且在场 → NPC 存活 →
规则允许 → 关系增量按 `max_delta_per_event` 钳制 → 情绪允许快变、人格禁止快变。

---

## 4. Director（§22/§24）

**不写散文、不改事实、不违背人物动机。**

调用门槛（省 token 且避免"每回合都有大事"）：
```text
turns_since_last_director >= director.min_interval_turns
或 上回合 importance >= 0.7
或 存在 overdue 线程（承诺/伏笔到期）
```

输出：

```jsonc
{
  "decision": "TRIGGER_EVENT" | "NO_EVENT" | "ADVANCE_THREAD" | "PLANT_FORESHADOWING",
  "source_plot_thread": "thread_091",
  "event_type": "NPC_RETURN",
  "participants": ["lin_qingxue"],
  "proposal": "…",
  "causal_basis": ["三日前进入黑风谷", "正在调查魔修踪迹"],
  "narrative_purpose": ["推进魔宗调查线"],
  "urgency": "medium"
}
```

程序二次校验（`engine/director/validator.py`）：
- 所有 `participants` 存在、**存活**、物理上可到场（位置距离 / 旅行时间）；
- `source_plot_thread` 存在且 `status ∈ {active, dormant}`；
- `causal_basis` 中引用的事件必须真实存在于 event log；
- 张力约束：`new_tension` 不得连续 3 回合位于 80+（§25 禁止连续高潮）；
- 不得凭空创造重要角色/物品（`event_type` 白名单）。
任一失败 → 降级为 `NO_EVENT` 并记录 `director_rejected` 到 trace。

---

## 5. NarrativeRenderer（§26/§27/§56）

输入全部是**已提交的事实**。可控：文笔、氛围、感官、节奏、肢体语言、台词措辞、无后果细节。
禁止：改成败 / 造重要物品 / 造重要角色 / 杀人 / 复活 / 改境界数值 /
瞬移 / 改关系 / 编造世界事实 / 泄露视角人物不知道的秘密 / 发奖励 / 触发突破 / 改 NPC 决策。

**AI 味控制**（§56）：
- `NarrativeStyleConfig` 来自 `content/<pack>/pack.yaml::narrative_style`。
- `engine/narrative/antipattern.py` 维护近 N 段落的**套路短语频次表**
  （"嘴角勾起一抹弧度"/"眼中闪过一丝异色"/"心中暗道"/"恐怖如斯"…）。
  超阈值的短语在下次调用时进入 prompt 的 `avoid_phrases`，并在
  后处理阶段做一次检测，命中过多则触发一次重写（≤1 次）。
- 后处理还检查：是否出现了**未在事实集合中**的角色名/物品名/地名 →
  命中即记 `narrative_hallucination` 告警（不阻断，但进 Debug Panel 与指标）。

---

## 6. MemoryExtractor（§28）

判定"是否值得长期记忆"。普通寒暄不入库。

```jsonc
{
  "should_store": true,
  "importance": 0.87,
  "memory_type": "promise",
  "summary": "…",
  "characters": ["player"],
  "facts_learned": [{"fact_key": "…", "state": "KNOWN", "confidence": 1.0}],
  "relationship_implications": {"player": {"trust": +6}}
}
```

确定性前置过滤器（省钱且防噪）：事件 `importance < memory.min_importance`
且 `event_type` 不在 `always_remember` 白名单 → 直接跳过 LLM。

---

## 7. 结构化输出与修复（§47）

```text
generate_structured(schema, prompt)
  ↓ provider 原生 JSON mode / tool-use（若支持）
  ↓ 抽取 JSON（容忍 ```json 包裹、前后缀噪声）
  ↓ pydantic 校验
  ├─ 成功 → 语义校验 → 返回
  └─ 失败 → 附上校验错误重试（≤ LLM_MAX_REPAIRS，默认 2）
             ↓ 仍失败 → fallback 策略（见 GAME_LOOP §7）
每次调用记录 LLMCallRecord{role, provider, model, prompt_version, temperature,
  prompt_tokens, completion_tokens, latency_ms, attempts, repaired, valid}
```

---

## 8. ModelRouter（§48）

```text
INTENT_MODEL      → fast/cheap
MEMORY_MODEL      → fast/cheap
NPC_MODEL         → medium         (MINOR_NPC / BACKGROUND)
NPC_MAJOR_MODEL   → strong         (MAJOR_NPC)
DIRECTOR_MODEL    → strong
NARRATIVE_MODEL   → medium/strong
EMBEDDING_MODEL   → embedding
```

模型名一律来自 `.env`，代码中**不出现任何具体模型字符串**
（`tests/unit/test_no_hardcoded_models.py` 强制）。

---

## 9. Token 预算（§29）

`ContextBuilder` 对每类上下文有硬预算（`.env` 可调）：

```text
CTX_BUDGET_NPC=2500     CTX_BUDGET_DIRECTOR=3000
CTX_BUDGET_NARRATIVE=3500   CTX_BUDGET_INTENT=1200   CTX_BUDGET_MEMORY=1200
```

裁剪顺序：`RecentEvents → Memories(按 score 截断) → Relationships(仅在场) →
KnownFacts(按相关度) → 核心身份（永不裁剪）`。
超预算时记录 `context_truncated` 指标。

---

## 10. Prompt 版本管理（§46）

`prompts/*_v1.md` + `prompts/registry.py`（`PromptRegistry.get(role, version)`）。
每次调用记录 `prompt_version`，便于 A/B。文件内容带 front-matter：

```yaml
---
role: npc_decision
version: v1
output_schema: NPCDecision
temperature: 0.7
---
```
