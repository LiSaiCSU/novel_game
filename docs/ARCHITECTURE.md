# ARCHITECTURE

> Code determines what CAN happen.
> Database determines what IS true.
> AI determines intent, reasoning, behavior and expression.

本文件是全项目的结构契约。任何与本文件冲突的实现都是 bug。

---

## 1. 分层

```text
┌──────────────────────────────────────────────────────────────┐
│ apps/web        零构建 SPA（三栏 UI + Debug Panel）           │
├──────────────────────────────────────────────────────────────┤
│ apps/api        FastAPI：REST + SSE，只做 I/O 与 DTO 转换      │
├──────────────────────────────────────────────────────────────┤
│ engine/         纯领域层（不 import SQLAlchemy / FastAPI）    │
│   orchestrator  回合调度                                      │
│   actions rules events knowledge memory relationships         │
│   world characters simulation director narrative context llm  │
│   contentpack   世界观数据加载                                 │
│   core          ports / errors / config / mutations / clock   │
├──────────────────────────────────────────────────────────────┤
│ database/       SQLAlchemy 2.x models + repositories(适配器)   │
│                 + alembic migrations + seeding                │
├──────────────────────────────────────────────────────────────┤
│ content/        YAML 内容包（cultivation_v1 / …）             │
└──────────────────────────────────────────────────────────────┘
```

**依赖方向严格向下**：`apps → engine → (ports) ← database`。
`engine` 通过 `engine/core/ports.py` 中的 `Protocol` 反向依赖持久化，
因此可以用纯内存 fake repo 完整跑通整个回合（见 `tests/`）。

自动化守卫：`tests/unit/test_engine_purity.py`
- engine 内不得出现 `import sqlalchemy` / `import fastapi`
- engine 内除 `engine/rng/` 外不得出现 `import random` / `numpy.random`
- engine 内不得出现内容包专有名词（中文实体名硬编码）

---

## 2. 回合数据流（与 Prompt §5 一致）

```text
                      PLAYER
                        │  natural language
                        ▼
                 GameOrchestrator            ← 唯一的流程编排者
                        │
      ┌─────────────────┼─────────────────┐
      ▼                 ▼                 ▼
 IntentParser      ContextBuilder     WorldStateView
 (LLM/fallback)    (逐 Agent 裁剪)     (repo 只读快照)
      └─────────────────┼─────────────────┘
                        ▼
                   RuleEngine            ← 纯确定性，LLM 无权覆盖
                   validate_action()
                        │  allowed / reason_code
                        ▼
                  ActionResolver         ← GameRNG，产出 ActionOutcome
                        │
      ┌─────────────────┼─────────────────┐
      ▼                 ▼                 ▼
  NPCAgents        WorldSimulator      Director
 (proposal only)   (LOD 0..3)        (剧情线程/张力)
      └─────────────────┼─────────────────┘
                        ▼
                 ProposalValidator       ← §18：AI 提案 → 校验 → 钳制
                        ▼
                 ConsistencyGuard        ← §63：7 类一致性检查
                        ▼
                 StateTransaction        ← §58：一个回合 = 一个事务
                        │
      ┌─────────────────┴─────────────────┐
      ▼                                   ▼
   EventLog (append-only)            MemoryExtractor
      └─────────────────┬─────────────────┘
                        ▼
                NarrativeRenderer        ← 只描述已确定的事实
                        ▼
                      PLAYER
```

**关键不变量**
1. `NarrativeRenderer` 在 `commit()` 之后才启动（§49）。流式输出不影响世界状态。
2. 任何 AI 输出在未经 `ProposalValidator` 之前不得转成 `StateChange`（§18/§47）。
3. `ContextBuilder` 是 NPC 上帝视角的唯一防线（§15/§30）。
4. 不是每回合都调 LLM。`OrchestratorPlan` 决定本回合需要哪些 AI（§6）。

---

## 3. 模块职责表

| 模块 | 职责 | 确定性 | 可调 LLM |
|---|---|---|---|
| `engine/orchestrator` | 回合编排、事务边界、重试、token 预算、日志 | ✅ | ❌ |
| `engine/actions` | Action schema、fallback 解析、Action 注册表 | ✅ | ❌ |
| `engine/rules` | 12 个规则族：validate / resolve / calculate | ✅ | ❌ |
| `engine/rng` | GameRNG、seed 派生、RngTrace | ✅ | ❌ |
| `engine/world` | 世界状态视图、WorldClock、位置图 | ✅ | ❌ |
| `engine/characters` | 角色模型、属性、人格/情绪演化 | ✅ | ❌ |
| `engine/relationships` | 8 维关系、钳制、变化原因日志 | ✅ | ❌ |
| `engine/knowledge` | Fact / CharacterKnowledge、信息传播 | ✅ | ❌ |
| `engine/memory` | 4 层记忆、embedding、复合排序检索 | ✅ | ✅(抽取) |
| `engine/events` | Event 构造、append-only、因果链 | ✅ | ❌ |
| `engine/simulation` | LOD 0-3、NPC 日程、势力模拟 | ✅ | ✅(LOD0) |
| `engine/director` | 剧情线程、张力曲线、事件提案 | 部分 | ✅ |
| `engine/narrative` | 叙事渲染、风格配置、去 AI 味 | ❌ | ✅ |
| `engine/context` | 逐 Agent 上下文构造 + token 预算 | ✅ | ❌ |
| `engine/llm` | Provider 抽象、ModelRouter、结构化输出与修复 | ✅ | — |
| `engine/contentpack` | YAML → ContentPack 对象、校验 | ✅ | ❌ |

---

## 4. LLM 抽象（§3/§48）

```text
LLMProvider (Protocol)
├── AnthropicProvider
├── OpenAIProvider
├── CompatibleProvider     (OpenAI 兼容端点：DeepSeek/Qwen/vLLM/Ollama…)
├── ScriptedProvider       (测试：录制/回放固定响应)
└── NullProvider           (无 Key 时：触发确定性 fallback)

方法: generate_text() / generate_structured(schema) / stream_text()
```

`ModelRouter` 按任务角色选模型，全部来自 `.env`：

```text
INTENT_MODEL   NPC_MODEL   NPC_MAJOR_MODEL
DIRECTOR_MODEL NARRATIVE_MODEL   MEMORY_MODEL
```

`generate_structured()` 流程：`调用 → JSON 抽取 → pydantic 校验 →
（失败）修复提示重试 ≤N → （仍失败）fallback 策略 → 记录 LLMCallRecord`。

---

## 5. 内容包接口（§64/§65）

```text
content/cultivation_v1/
├── pack.yaml         元信息、叙事风格、模型偏好
├── calendar.yaml     世界日历（分钟↔年月日时辰）
├── realms.yaml       境界阶梯 + 突破参数 + 战力系数
├── rules.yaml        时间成本/关系钳制/检测/经济/社交等数值
├── locations.yaml    位置树
├── factions.yaml     势力
├── characters.yaml   重要 NPC（完整人格/知识/日程/秘密）
├── npc_templates.yaml 背景 NPC 模板
├── items.yaml        物品
├── skills.yaml       技能
├── facts.yaml        世界事实（truth）与初始知识分布
├── plot_threads.yaml 初始剧情线程 / World Seeds
└── event_templates.yaml
```

引擎侧只认 `ContentPack` 的**结构**，不认其**内容**。
新增 `content/wuxia_v1/` 即可复用全部引擎代码。

---

## 6. 一致性与事务（§58/§59/§63）

- 一个玩家回合 = 一个 `TurnTransaction`。失败整体回滚。
- `ConsistencyGuard` 在 commit 前检查：alive / location / inventory /
  realm / knowledge / faction / time 七类一致性，任一失败 → 回滚并记录 `TurnError`。
- 幂等：`POST /game/{sid}/action` 接受 `Idempotency-Key`；
  同 key 重放返回首次结果，不重复推进世界。
- 世界级并发：`LockBackend.acquire(f"world:{world_id}")`。

---

## 7. 前后端契约

```text
POST /worlds                      创建世界（从 content pack 播种）
GET  /worlds/{id}
POST /characters                  创建角色
GET  /characters/{id}
POST /game/start                  开局 → session
POST /game/{session_id}/action    提交自然语言行动（同步返回完整回合结果）
GET  /game/{session_id}/action/stream   SSE：先推 state_changes，再流式 narrative
GET  /game/{session_id}/state
GET  /game/{session_id}/history
GET  /characters/{id}/relationships
GET  /characters/{id}/memories
GET  /player/inventory
GET  /debug/turn/{turn_id}        Debug Panel 数据（§52）
GET  /admin/world/{id}/inspector  World Inspector（§53）
```

`action` 响应：

```json
{
  "narrative": "...",
  "state_changes": {},
  "visible_updates": {},
  "choices": [],
  "turn_id": "...",
  "debug": { "...": "DEBUG_MODE 时才有" }
}
```

---

## 8. Observability（§60）

每回合产出一条 `TurnTrace`：
`request_id / session_id / world_id / turn_id / 各阶段耗时 /
每次 LLM 调用(model, prompt_version, temperature, tokens, latency, 校验结果) /
RNG traces / state mutations / errors`。
持久化到 `turn_traces` 表，Debug Panel 直接读取。
结构化日志走 `engine/core/logging.py`（stdlib logging + JSON formatter），禁止 print。
