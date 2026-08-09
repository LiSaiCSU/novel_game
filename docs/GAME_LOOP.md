# GAME_LOOP

一个玩家回合的完整规格。实现见 `engine/orchestrator/orchestrator.py`。

---

## 1. 回合阶段

```text
S0  ingest          请求校验、幂等键检查、世界锁
S1  snapshot        读取 WorldStateView（只读快照，含玩家、场景、在场角色）
S2  intent          自然语言 → Action（LLM 或 fallback 解析器）
S3  plan            OrchestratorPlan：本回合需要哪些子系统（成本控制）
S4  validate        RuleEngine.validate_action() → Allowed / Rejected(reason_code)
S5  resolve         ActionResolver + GameRNG → ActionOutcome
S6  npc             在场 NPC 决策（proposal）
S7  simulate        WorldSimulator 推进世界时间，LOD 0-3
S8  direct          Director 判断是否触发剧情事件（proposal）
S9  validate2       ProposalValidator：所有 AI 提案二次校验 + 幅度钳制
S10 guard           ConsistencyGuard 七类检查
S11 commit          单事务写入：state changes + events + relationship changes
S12 memory          MemoryExtractor（可异步）
S13 narrate         NarrativeRenderer（此时世界已定稿；可流式）
S14 respond         组装 TurnResult + TurnTrace
```

`S13` 严格在 `S11` 之后（§49）。

---

## 2. 快路径（不调用 LLM）

`OrchestratorPlan` 检测到以下情况直接走确定性通道：

| 场景 | 处理 |
|---|---|
| `查看背包` / `我的状态` / `看看关系` | 纯 repo 查询，`needs_llm=False`，S2/S6/S8/S13 全跳过 |
| Rule 拒绝（如境界不足） | 跳过 S5-S9，narrative 用模板拒绝语（可选轻量 LLM 润色） |
| 场景内无 NPC | 跳过 S6 |
| 张力/节奏检查未到阈值 | 跳过 S8（Director 有 `min_turns_between_calls` 与冷却） |
| 记忆重要度 < 阈值 | 跳过 S12 的 LLM 抽取，走确定性打分 |

目标：**大多数“查询型”回合 0 次 LLM 调用；普通行动 1-2 次；重大剧情回合 ≤5 次。**

---

## 3. 时间推进（§33）

时间成本来自 `content/<pack>/rules.yaml::time_costs`，由 `ActionResolver` 计算：

```text
conversation      5–20 分钟
observe/search    5–30 分钟
local move        10–60 分钟
regional move     数小时–数天（按 locations.travel_minutes 图搜索）
cultivate         小时–月（玩家指定时长，规则钳制上限）
seclusion         天–年
combat round      1–5 分钟
```

时间推进后 `WorldSimulator.advance(minutes)` 被调用：
时间跨度越大，触发的 LOD 层级越高、离线事件越多。
**玩家闭关三年回来，世界必须已经变了**（§72）。

---

## 4. 状态提交（§58）

```python
async with uow.transaction():          # 一个回合 = 一个事务
    guard.check(changes)               # 失败 → 抛出 → 回滚
    await apply_state_changes(changes)
    await event_log.append(events)     # append-only
    await relationship_log.append(...)
    await turns.record(turn)
# 事务外：memory extraction / narrative（失败不污染世界）
```

若 `S13` 叙事生成失败：世界状态**保持已提交**，返回模板化叙事 + `degraded: true`。
若 `S11` 之前任一环节失败：整体回滚，世界时间不推进，返回错误，
`turns` 中记录一条 `failed` 回合供 debug。

---

## 5. 幂等（§59）

```text
Idempotency-Key: <client uuid>
  → turns.idempotency_key UNIQUE
  → 命中则直接返回已存储的 TurnResult，不重放世界
世界锁: LockBackend.acquire(f"world:{world_id}", ttl=120s)
  → 同一世界的并发行动串行化
```

---

## 6. TurnResult 结构

```jsonc
{
  "turn_id": "…",
  "narrative": "…",                 // 小说文本
  "state_changes": {                // 玩家可见的变化摘要
    "character": {"health": [82, 71], "cultivation_progress": [0.31, 0.44]},
    "relationships": [{"with": "…", "trust": [31, 34], "reason": "…"}],
    "inventory": {"added": [], "removed": []},
    "world_minute": [102400, 102440]
  },
  "visible_updates": {              // 右栏场景面板
    "location": {...}, "present_characters": [...], "time_label": "…"
  },
  "choices": [ {"label": "…", "hint": "…"} ],   // 可选建议，玩家永远可自由输入
  "rejected": null | {"reason_code": "REALM_TOO_LOW", "reason": "…"},
  "debug": { … }                    // DEBUG_MODE 时输出 TurnTrace
}
```

---

## 7. 失败与降级矩阵

| 失败点 | 行为 |
|---|---|
| Intent LLM 超时/非法 JSON | 重试 1 次 → fallback 规则解析器 → 仍失败则 `CUSTOM` action + observe |
| NPC LLM 失败 | 该 NPC 走启发式决策器，标记 `degraded` |
| Director LLM 失败 | 视为 `NO_EVENT` |
| Narrative LLM 失败 | 模板渲染器输出事实播报 |
| DB 事务失败 | 全回滚，返回 500 + `turn_id` 供追查 |
| ConsistencyGuard 失败 | 全回滚，记录 `ConsistencyViolation` 到 trace（这是**引擎 bug 的告警信号**） |
