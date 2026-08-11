# GAME_LOOP

一个玩家回合的完整规格。实现见 `engine/orchestrator/orchestrator.py`。

---

## 0. 一次输入 = 一段跑动（D-023）

游戏的实际入口是 `GameOrchestrator.advance()`，不是 `play_turn()`：

```text
advance(玩家输入)
  ├─ 若玩家自己写了动作 → 跑一步（下面 S0—S11 的完整流水线）
  ├─ 然后 Autopilot 一次规划最多 N 步——**以玩家刚说的那句话为第一原则**
  │     （D-024：只有纯「继续」时才回落到角色自身目标），逐步执行：
  │     每步都是一次完整的 S0—S11，独立提交、独立留痕
  │     每步之后 InterruptDetector 判断是否该停
  ├─ 停下的条件（确定性，见 engine/orchestrator/interrupt.py）：
  │     重要人物开口 / NPC 对你动手或递物 / 掉血 / 死亡 /
  │     差事上门 / 导演即时事件 / 重要度越线 / 步数或世界时间耗尽
  └─ 最后由 ChapterRenderer 把整段写成【一章】+ StoryBeat（仅一次调用）
```

要点：

- **叙事被合并，审计没有被合并**：每一步仍是一个状态完整的 Turn。
- **章节是真流式**：`ChapterRenderer` 走 `stream_text` 边写边推；
  遇到 `---BEAT---` 之前始终扣住标记与最多 180 字的收尾窗口，结构化块不会漏进正文，
  超出用户上限时可在尚未发送的中文句末收束。
- SSE 事件顺序：`progress`（每提交一步）× N → `narrative` 分块 → `state` → `done`。
  「世界先定稿再叙事」的可观测形式是：**所有 `progress` 都早于第一个 `narrative`**。
- 中途各步以 `narrate=False` 提交，短暂停留在 `CANONICAL_COMMITTED`
  （即既有的可恢复状态）；每步的 canonical Event 仍立即投影 Memory，章节写完后统一转为 `COMPLETED`。
- 一段跑动写入**一条 `chapter` 叙事片段**，整段共用请求的幂等键，
  键挂在**首个** Turn 上——重试会重放整段，而不是让角色再走一遍。
- `TurnRequest.narrative_max_chars` 范围为 400—4000，默认 1800。它是幂等请求身份的一部分：
  相同 key 若换了输入或长度会被拒绝；模型预算和程序级句末钳制共同保证上限。
- 未配置模型时不自动推进（确定性兜底会重复同一个动作），行为退回单回合。
- `auto_advance.max_steps: 1` 可退回逐动作节奏，无需改代码。

---

## 1. 单步的回合阶段

```text
S0  ingest          请求校验、幂等键检查、世界锁
S1  snapshot        读取 WorldStateView（只读快照，含玩家、场景、在场角色）
S2  intent          自然语言 → Action / 短 ActionPlan proposal（LLM 或 fallback）
                    输入若是「继续」，改由 Autopilot 代角色产出 intent
S2b steward         意图引用了世界里没有的人/地点时：先在全世界辨认，
                    确实没有才创造，并产出 CHARACTER_SPAWN / LOCATION_SPAWN
S3  plan            OrchestratorPlan：本回合需要哪些子系统（成本控制）
S4  validate        单 Action 直接验证；多 primitive 在 S5 逐步投影验证
S5  resolve         ActionResolver / ActionPlanExecutor + 派生 GameRNG → ActionOutcome
S6  npc             在场 NPC 决策（proposal）
S7  simulate        WorldSimulator 推进世界时间，LOD 0-3
S8  direct          Director 判断是否触发剧情事件（proposal）
S9  validate2       ProposalValidator：所有 AI 提案二次校验 + 幅度钳制
S10 guard           ConsistencyGuard 提交前 canonical 一致性检查
S11 commit          单事务写入：state changes + events + turn(CANONICAL_COMMITTED)
S12 memory          MemoryExtractor（独立幂等投影事务，可恢复）
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
| Rule 拒绝（如境界不足） | S5 只生成 canonical `REJECTED_ACTION`，跳过 NPC/模拟/Director |
| 场景内无 NPC | 跳过 S6 |
| 张力/节奏检查未到阈值 | 跳过 S8（Director 有 `min_turns_between_calls` 与冷却） |
| 记忆重要度 < 阈值 | 跳过 S12 的 LLM 抽取，走确定性打分 |

目标：**大多数“查询型”回合 0 次 LLM 调用；普通行动 1-2 次；重大剧情回合 ≤5 次。**

### 短 Action Plan 的原子语义

- 2—4 个 primitive，共享一个 Turn、一个最终 ChangeSet 和一次 canonical commit。
- 每步使用 `turn RNG / primitive:<id>` 派生流，并在前一步 ChangeSet 的内存投影上重新走 RuleEngine。
- 任一步引用/规则验证失败：此前步骤从未提交，debug 标为 `DISCARDED`；只记录整个计划被拒绝。
- 骰子结算后的失败是已经发生的尝试，不回滚；结构化条件可令依赖步骤 `SKIPPED_CONDITION`。
- 条件只允许 `PREVIOUS_SUCCEEDED / HAS_ITEM / TARGET_PRESENT / AT_LOCATION`；自由文本 trigger
  不能执行，必须澄清。
- MOVE 只能是最后一步，查询不能混入。总耗时默认不超过一天；更长跨度必须拆成独立 Turn，
  以便 Temporal Jump、NPC 日程和 Director 事件在边界处真实运行。

---

## 3. 时间推进（§33）

时间成本来自 `content/<pack>/rules.yaml::time_costs`，由 `ActionResolver` 计算：

```text
conversation      5–20 分钟
observe/search    5–30 分钟
local move        10–60 分钟
regional move     数小时–数天（按 locations.travel_minutes 图搜索）
cultivate         小时–月（玩家指定时长，规则钳制上限）
seclusion         天–数十年（由内容包给出单行动硬上限）
combat round      1–5 分钟
```

时间推进后 `WorldSimulator.advance(minutes)` 被调用。长跨度使用 **Temporal Jump**：

- 直接计算目标时间，只在日程终点、任务期限、历年边界和世界事件等有意义的边界工作；
- 势力漂移用按跨度聚合的随机游走，不循环每周 Tick；
- 离线事件数量用一次 binomial 聚合抽样，最多物化内容包规定的代表事件数，
  其余数量写入事件 `payload.occurrences`；
- 跨过历年边界时所有存活人物增长年龄，超过内容包境界寿命者产生 canonical `DEATH`；
- `requested_minutes` 必须等于实际 `minutes`。部署安全上限只会明确拒绝，禁止静默裁剪。
- 重要 NPC 的到期计划行动使用 `GameRNG.geometric` 一次跨过多次重试；计算量受计划步骤数约束，
  不随闭关周数线性增长。每个物化 Action Result 写入 canonical event，计划游标与结果引用原子提交。

因此玩家闭关三年或三十年后，世界时钟、人物年龄、死亡、任务、势力与事件使用同一跨度。

### Director Event 生命周期

- AI 只产生 `DirectorDecision` proposal；通过白名单、参与者、因果、张力、每日容量和去重校验后，
  才建立 canonical `director_events` 记录。
- 即时事件原子经历 `PROPOSED → SCHEDULED → ACTIVE → RESOLVED`，ACTIVE 时才创建
  append-only world event。
- 未来事件保持 `SCHEDULED`；Temporal Jump 直接读取到期边界并重新校验。人物已死亡、不可达或
  线程 stage 已变化时转为 `CANCELLED`，不会强行演出。
- 同一天超过内容包 `max_events_per_day` 的到期事件顺延到下一可用日；顺延成本取决于候选事件数，
  不逐日模拟。
- Director 冷却读取 canonical 生命周期，不再从 Turn debug 反推。Narrative 重试只读取已提交结果，
  不会再次激活事件。

---

## 4. 状态提交（§58）

```python
async with uow.transaction():          # 一个回合 = 一个事务
    guard.check(changes)               # 失败 → 抛出 → 回滚
    await apply_state_changes(changes)
    await event_log.append(events)     # append-only
    await relationship_log.append(...)
    await turns.record(turn)
# canonical 已提交；以下失败不污染世界，也不得重做行为
async with uow.transaction():
    await project_event_memories()      # 与 memory_projection=COMPLETED 原子提交
# narrative 是纯展示阶段
```

若 `S12` 记忆投影失败：已写入的一部分记忆整体回滚，Turn 仍为
`CANONICAL_COMMITTED`，恢复胶囊记录 `memory_projection=FAILED`。同一幂等键重试时，
只重新投影 canonical events；`(owner_character_id, related_event_id)` 唯一约束是最终防线。
AI 只能建议是否存储、标签、重要度与情绪值，持久化 `summary` 固定来自 canonical event，
不读取 Narrative 文本。

若 `S13` 叙事生成失败：世界状态**保持已提交**，Turn 转为 `NARRATIVE_FAILED`，
返回模板化叙事 + `degraded: true`。使用同一幂等键重试时只重跑 S13/S14，
不会再次解析、裁决、模拟或提交行为。
若 `S11` 之前任一环节失败：整体回滚，世界时间不推进，返回错误，
且不写入 canonical Turn；错误通过日志与请求 trace 诊断。

---

## 5. 幂等（§59）

```text
Idempotency-Key: <client uuid>
  → turns.idempotency_key UNIQUE
  → COMPLETED：直接返回已存储的 TurnResult
  → CANONICAL_COMMITTED：补完 Memory 投影后生成叙事
  → NARRATIVE_FAILED：Memory 已完成，只恢复叙事
  → 同 key 不同玩家输入：拒绝
未传 key 时服务端以 turn_id 生成唯一 key 并在 TurnResult 返回；客户端需要安全网络重试时仍应主动传 key。
世界锁: LockBackend.acquire(f"world:{world_id}", ttl=120s)
  → 同一世界的并发行动串行化
```

---

## 6. TurnResult 结构

```jsonc
{
  "turn_id": "…",
  "idempotency_key": "…",
  "status": "COMPLETED",
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

## 8. Turn 状态机

```text
CANONICAL_COMMITTED ──叙事成功──→ COMPLETED
          │
          └──叙事失败──→ NARRATIVE_FAILED ──重试叙事──→ COMPLETED
                                  └──再次失败──→ NARRATIVE_FAILED
```

`CANONICAL_COMMITTED` 与世界变更、事件、session.turn_number 在同一数据库事务中落盘。
恢复胶囊 `canonical_payload` 保存已裁决 outcome、已验证 ChangeSet、NPC 已确认反应及叙事上下文；
状态进入该节点后，程序没有回到 S2—S11 的合法迁移。
