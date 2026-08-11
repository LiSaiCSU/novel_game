# DECISIONS — 重要工程假设与决策记录

按 Prompt §68：普通工程决策自行判断，重要假设记录在此。

格式：`D-<编号> 标题 / 背景 / 决策 / 后果 / 可逆性`

---

## D-001 数据库：SQLite 默认 + PostgreSQL/pgvector 生产

**背景**
Prompt §3 要求 PostgreSQL + pgvector。宿主机未探测到 PostgreSQL 实例，
若强制依赖，则“在 conda env `game` 中运行与测试代码”这一硬性要求无法满足。

**决策**
- 统一使用 SQLAlchemy 2.x（async）。`DATABASE_URL` 由 `.env` 提供。
- 默认 `sqlite+aiosqlite:///./data/game.db`，生产 `postgresql+asyncpg://...`。
- 所有 `JSONB` 字段用 `sa.JSON().with_variant(postgresql.JSONB, "postgresql")`。
- 向量检索抽象为 `engine/memory/vector_index.py::VectorIndex`：
  - `PgVectorIndex` — 生产，`vector(N)` 列 + `<=>` 余弦距离，走 SQL。
  - `NumpyVectorIndex` — 开发/测试，embedding 存 JSON，进程内 numpy 计算余弦。
- Alembic 迁移对两种方言都生成有效 DDL（pgvector 扩展与向量列仅在 postgresql 分支创建）。

**后果**
测试零外部依赖；生产切换只改 `.env`。代价是 SQLite 下向量检索为 O(n)，
但 V1 单世界记忆量级（万级以内）完全可接受，且检索本就不是纯 Top-K（见 §16）。

**可逆性**: 高。

---

## D-002 前端：V1 用零构建 SPA，保留 Next.js 迁移路径

**背景**
Prompt §3 建议 Next.js + TS + React + Tailwind。宿主机 **无 Node.js/npm**，
无法安装依赖、无法 `next build`、无法运行、无法测试。
Prompt §70 优先级表中 “UI视觉效果” 排在最后一位（第 8），
而 §69.10 明确禁止“做大量UI，却没有稳定世界引擎”。

**决策**
V1 前端 = `apps/web/` 下的零构建单页应用（原生 ES Module + 手写 CSS 设计系统），
由 FastAPI 以 `StaticFiles` 托管在 `/`。实现 Prompt §51 的三栏布局、流式文本、
Markdown 渲染、背包/关系/任务/历史面板与 §52 Debug Panel。

前后端**只通过 REST/SSE 契约耦合**（见 `docs/ARCHITECTURE.md` §7），
后续在有 Node 的机器上新建 `apps/web-next/` 即可复用全部接口，无需改后端。

**后果**
牺牲组件库生态与类型检查，换取“现在就能真正跑起来并被测试”。

**可逆性**: 高（后端零改动）。

---

## D-003 Redis：接口抽象，默认进程内实现

**背景** Prompt §3 列出 Redis，§59 要求 transaction / locking / idempotency key。

**决策**
`engine/core/locks.py` 定义 `LockBackend` 与 `IdempotencyStore` 协议。
默认 `InMemoryLockBackend`（asyncio.Lock + TTL dict）。
`REDIS_URL` 存在时使用 `RedisLockBackend`。
世界状态的真正原子性由**数据库事务**保证，而不是靠锁（锁只防重复执行）。

**可逆性**: 高。

---

## D-004 engine/ 不依赖 database/

**背景** Prompt §65：禁止把“青云宗”硬编码进 engine；§75：Engine 不应知道自己在跑修仙。

**决策**
- `engine/` 是**纯领域层**：只依赖 pydantic / numpy / pyyaml，**不 import SQLAlchemy**。
- 持久化通过 `engine/core/ports.py` 中的 `Protocol`（Repository 端口）注入。
- `database/` 实现这些端口（Adapter）。
- 内容（境界名、宗门、NPC、物品、技能、规则参数）全部来自
  `content/<pack>/*.yaml`，由 `engine/contentpack/` 加载为 `ContentPack` 对象。
- 引擎中**不允许出现中文专有名词字面量**（除注释/文档）。
  已加自动化测试 `tests/unit/test_engine_purity.py` 强制此约束。

**后果** 换 YAML 可替换同机制世界内容；复杂题材机制通过 D-017 的 Rule Plugin 扩展。
单元测试可用假 repo 全内存运行。角色 schema 中仍有 V1 progression 兼容字段，不能把
“没有中文专名”夸大为“引擎没有任何修炼历史结构”。

**可逆性**: 低（这是架构基石，不应回退）。

---

## D-005 世界时间用整数分钟 + 内容包日历

**背景** Prompt §33 要求独立世界时钟，跨度从 5 分钟到数年。

**决策**
`WorldClock` 内部只存 `int` —— 世界纪元起点以来的**分钟数**（`world_minute`）。
年/月/日/时辰的换算规则来自 `content/<pack>/calendar.yaml`（`calendar_config`）。
好处：全序可比、可做差、可索引、可回放；显示层才做本地化格式化。

**可逆性**: 中。

---

## D-006 RNG：显式 seed 派生，禁止全局 random

**背景** Prompt §9 要求可复现、可回放。

**决策**
`GameRNG(world_seed).derive(session_seed).derive(event_key)` 走
BLAKE2b(seed_material) → `random.Random(int)`。每次掷点写入
`RngTrace{stream_key, seed_hex, method, args, result}` 并随事件持久化。
`tests/unit/test_engine_purity.py` 静态断言 engine 内除 `engine/rng/` 外
不出现 `import random` / `np.random`。

**可逆性**: 低。

---

## D-007 LLM 不可用时系统必须仍可运行

**背景** 用户未提供 API Key；Phase 2/3 明确要求“先不调用 LLM”。

**决策**
`LLM_PROVIDER=null` 时使用 `NullProvider`：
- Intent 解析退化为**确定性规则解析器**（`engine/actions/fallback_parser.py`，
  关键词 + 内容包别名表）；
- NPC 决策退化为**基于人格/关系/规则的启发式决策器**；
- Director 退化为张力曲线 + 线程优先级的确定性调度；
- Narrative 退化为模板化事实播报（`engine/narrative/template_renderer.py`）。

这保证：**世界引擎的正确性可以在没有任何 LLM 的情况下被完整测试**，
LLM 只是“理解与表达”的增强层——与 Prompt §0 的分工完全一致。
所有 eval 用 `ScriptedProvider`（录制/回放固定 JSON）运行，不消耗真实额度。

**可逆性**: 高（填 `.env` 即启用真实模型）。

---

## D-008 Action 校验与结算分离，AI 只能提 proposal

**背景** Prompt §18 / §47。

**决策**
所有变更走 `StateChange` 值对象 → `ConsistencyGuard.check()` → 单事务 `commit()`。
AI 返回的任何结构在进入 `StateChange` 之前必须：
`pydantic 校验` → `语义校验（存在性/存活/在场/所有权/规则）` → `幅度钳制（clamp）`。
`engine/core/mutations.py` 是**唯一**允许生成 `StateChange` 的地方，
`tests/unit/test_engine_purity.py` 断言 narrative/director/npc 模块不 import 任何 repo 写方法。

**可逆性**: 低。

---

## D-009 关系变化幅度钳制

**背景** Prompt §14 禁止“一次普通对话 trust +50”。

**决策**
`content/<pack>/rules.yaml::relationship.max_delta_per_event` 按事件重要性分档：
`trivial: 2 / minor: 5 / major: 15 / life_changing: 40`。
AI 提案超出即钳制并记 `clamped: true` 到事件日志（不静默丢弃，便于 A/B 观察模型行为）。

**可逆性**: 高（改 YAML）。

---

## D-010 UnitOfWork 端口用只读 property 而非属性

**背景**
`engine/core/ports.py::UnitOfWork` 最初把各仓储声明为普通属性。
mypy 对 Protocol 的可变属性要求**不变性**，因此 `SqlUnitOfWork.characters: SqlCharacterRepo`
即使结构上完全满足 `CharacterRepository` 也会报错（28 个类型错误）。

**决策**
改为只读 `@property` 声明。属性是不变的，property 是协变的，适配器因此可以
暴露各端口的具体子类型。这同时表达了正确的语义：**仓储句柄在一个事务内不可替换**。

**后果** `mypy engine database apps prompts` 全绿；适配器无需任何 `type: ignore`。

**可逆性**: 高，但没有理由回退。

---

## D-011 内存 UnitOfWork 读取时返回副本

**背景**
最初 `MemoryUnitOfWork` 的读方法直接返回存储中的对象。这掩盖了一个真实缺陷：
Orchestrator 用 "提交前的 state 视图" 与 "提交后的 fresh_state" 做 before/after 差分，
而两者指向同一个对象，所有差分恒为空——`state_changes.character` 永远是 `{}`。

**决策**
两处一起改：
1. Orchestrator 在 S1 阶段用 `_capture()` 冻结基元值再做差分，这在任何后端下都正确；
2. `MemoryUnitOfWork` 的 world/character 读取返回 `model_copy(deep=True)`，
   与真实 ORM session 在 commit 后交出刷新行的语义一致。

**后果**
测试替身不再比生产实现"更宽容"，同类别名缺陷无法躲在内存后端里。
代价是每回合多几十次浅层深拷贝，实测无感。

**可逆性**: 高。

---

## D-012 目录布局在 Prompt §4 基础上的调整

- 未创建顶层 `ai_narrative_world/` 包裹目录：工作目录本身即项目根，避免 `game/ai_narrative_world/...` 冗余嵌套。
- 增加 `engine/contentpack/`（内容包加载器）与 `engine/core/`（ports / errors / config / mutations），Prompt 树中未显式列出但为 D-004 所必需。
- `database/` 同时容纳 ORM models、repositories 与 alembic migrations。

**可逆性**: 高。

---

## D-013 长时间推进使用 Temporal Jump，不按 Tick 重放

**背景**
旧实现把 `WorldSimulator` 的处理跨度静默裁到一年，但 Orchestrator 仍把世界时钟推进
完整三年；势力变化又只计算前 52 周，离线事件逐周掷骰。这会让数据库时间与实际演化
出现不可恢复的分叉，也无法支持数十年游戏。

**决策**
- simulator 要么处理完整 `requested_minutes`，要么在配置安全上限处明确拒绝，禁止裁剪。
- 势力随机游走按周分布的均值与方差直接聚合到整个跨度。
- `GameRNG.binomial/normal` 各写一条 trace；大样本采用有界成本近似。
- 世界事件先聚合出现次数，再最多物化内容包规定的代表事件数；每条记录 occurrences。
- 历年边界直接计算年龄增量；达到内容包寿命上限时写 canonical death。

**后果**
三十年 jump 的计算量取决于世界实体数量和物化事件上限，而不是经过的周数；世界时钟、
人物年龄、寿命、任务和事件使用同一时间跨度。聚合事件保留因果数量与代表时间，但不声称
逐条重建玩家未观察期间的所有微观过程。

**可逆性**: 中。采样算法可版本化替换，但禁止恢复静默裁剪或逐 Tick 长循环。

---

## D-014 重要 NPC 目标是持久 Canonical Lifecycle

**背景**
原实现只有 `long_term_goal` 和 `short_term_goals` 文本，日程系统最多选择一个调查/旅行地点。
NPC 离开玩家场景后不会保存计划游标、行动尝试或结果，长期跳跃也无法解释人物为何发生变化。

**决策**
- 仅 `MAJOR_NPC` 自动建立持久 `goal_lifecycle`：长期目标是 Goal，短期目标列表是当前 Plan 的步骤。
- 生命周期保存计划版本、当前步骤、下次行动时间、累计尝试和最近 Result 的 event id。
- Temporal Jump 使用 traceable `GameRNG.geometric` 直接求跨度内首次成功尝试；工作量受最多五个计划步骤约束，
  不按天或周重放。
- 每个物化 Action Result 都是 append-only `NPC_GOAL_ACTION_RESULT` canonical event；角色生命周期状态与事件同事务提交。
- 死亡角色不能推进目标。AI 的 `goal_update_proposal` 只提供短期目标文本，程序清洗后构造新计划版本。
- 当前 Plan 全部完成进入 `REVIEW_REQUIRED`，而不是自动把长期 Goal 标为 `ACHIEVED`。
  题材特定结果必须由标准 Rule Plugin 验证并提交，通用 Engine 不硬编码领域因果。

**后果**
重要 NPC 在玩家不可见时也会留下可追溯的行动与结果，叙事只能复述已提交事件；长期闭关的计算量
不会随重试周期线性增长。生命周期提供通用执行骨架；领域后果可由 D-017 的 Rule Plugin 接续裁决。

**可逆性**: 中。JSON 状态可迁移为独立关系表，但 canonical event 与“不自动宣告目标实现”的语义应保留。

---

## D-015 Director Proposal 与已发生 Event 之间必须有持久生命周期

**背景**
旧实现把通过校验的 `DirectorDecision` 直接写成普通 Event。冷却从 Turn debug 反推，线程 stage
未变化的 foreshadowing 可以被反复触发；内容包声明的 `scheduled_beats` 没有执行器，未来事件也无法在
人物死亡或因果失效后取消。

**决策**
- 新增 world-scoped `director_events` canonical table，状态为
  `PROPOSED / SCHEDULED / ACTIVE / RESOLVED / CANCELLED`，并保存完整 transition history。
- 去重键由线程键与 stage、决策类型、事件类型、参与者和因果依据稳定计算，不包含 AI 可改写的 proposal 文本。
- 只有从 SCHEDULED 重新验证成功并进入 ACTIVE 时，才创建 append-only world Event；瞬时事件随后 RESOLVED，
  两者在同一事务提交。
- 未来事件到期时重新检查人物存活、路径和线程 stage。失败转 CANCELLED，不修改世界事件日志。
- 内容包 `scheduled_beats` 在建世时成为 SCHEDULED lifecycle；Temporal Jump 按到期边界兑现，
  不逐 Tick 轮询。
- `max_events_per_day` 是硬规则。超出容量的到期事件按候选数有界地顺延到下一可用日；预约阶段也拒绝超额。
- Director 冷却查询 canonical lifecycle。若同一 jump 已兑现预定事件，本回合不再用旧快照额外导演一次。

**后果**
“想发生”“计划发生”和“已经发生”成为不同数据库事实；模型重述、叙事崩溃重试、长时间跳跃和关键人物死亡
都不会重复兑现同一 beat。Inspector 可直接查看调度、取消原因与 canonical event 关联。

**可逆性**: 低。表结构可演进，但 proposal 不能再绕过生命周期直接成为已发生事实。

---

## D-016 Memory 是 Canonical Event 的幂等派生投影

**背景**
旧流程在 canonical commit 之后直接抽取并写 Memory，但 Turn 恢复胶囊不记录这一步。
进程在此中断会永久漏记；直接补重试又可能重复写入。同样，模型生成的 `summary` 被原样持久化，
允许未验证的修辞或细节逐渐变成角色长期“事实”。

**决策**
- Memory 投影与 canonical 世界事务分离，但投影行和恢复胶囊中的完成标记在第二个事务内原子提交。
- 失败时部分投影整体回滚，Turn 保持 `CANONICAL_COMMITTED`；相同幂等键从已存 ChangeSet 重建投影，
  不重新解析、裁决、模拟或提交玩家行为。
- 数据库以 `UNIQUE(owner_character_id, related_event_id)` 保证同一角色对同一事件最多一条记忆；
  repository 在调用模型和 embedding 前先做幂等查询。
- actor、target 和显式 witness 之外的角色不会获得该事件记忆。AI 只能建议存储选择、标签、重要度和
  情绪值；持久化 summary 与 embedding 输入只取 canonical Event 描述，Narrative 永不进入 Memory 提取。

**后果**
Memory 可从 event log 安全重建，Narrative 或模型措辞无法反向污染长期事实。Memory 服务故障会令本次
请求失败并要求使用同一幂等键恢复，但已经发生的世界行为不会重复。

**可逆性**: 低。分类模型与检索算法可替换，canonical 来源和 owner/event 幂等约束不应回退。

---

## D-017 Content Pack 的复杂领域规则使用受信任 Rule Plugin

**背景**
旧文档声称更换目录即可替换任意题材，但 `RuleEngine` 与 `ActionResolver` 直接包含修炼/突破分支。
YAML 能调整数值，却无法表达需要代码裁决的复杂领域因果；继续堆配置会形成不可验证的小语言。

**决策**
- `pack.yaml` 可显式声明 API 版本、入口文件和插件类；路径不能逃逸内容包目录。
- `RulePlugin` 声明所处理 Action，并分别实现确定性 validate 与 resolve。
- Engine 不给插件 UnitOfWork 或 Repository。插件只能读取 `RuleContext`，使用 traceable GameRNG，
  并返回 `ActionOutcome + ChangeSet` proposal；ConsistencyGuard 与事务提交权仍属于 Engine。
- 修炼与突破的计算、状态变化和事件生成迁入 `content/cultivation_v1/`；核心 router 不保留题材分支。
- 插件是部署者审查并安装的受信任 Python 代码，不承诺隔离恶意代码。bundled plugin 由源码测试禁止
  导入数据库、Web 框架和非确定性随机模块。

**后果**
通用 Engine 保持规则提交权和一致性边界，同时不需要把复杂题材规则压成过度抽象的 YAML。
非修仙领域可通过 `CUSTOM + parameters` 增加行为语义，无需扩充核心枚举。完整第二内容包与角色通用
属性建模仍是后续验证项。

**可逆性**: 中。API 可按版本并行演进；插件不得获得直接提交权。

---

## D-018 多行为输入编译为短时、原子的 Action Plan

**背景**
旧 schema 暴露 `secondary_actions` 和自由文本 `condition.trigger`，Prompt 也要求模型填写，
但执行器只结算 primary action。这会让后续叙事误以为附带行为已经发生；直接循环结算又无法保证
后一步看到前一步状态、失败回滚、时间模拟和因果链正确。

**决策**
- 复合意图使用包含全部步骤的 `ActionPlan(primitives=2..4, atomic=true)`，不再接受装饰性的
  `secondary_actions`。每个 primitive 是完整 Action，并有稳定 snake_case id。
- `ActionPlanExecutor` 为每步派生独立 RNG，在前一步 ChangeSet 的内存投影上重新验证和结算，
  最终合并为一个 ChangeSet，通过统一 ConsistencyGuard 后只提交一次。
- 规则/引用拒绝意味着整个 proposal 不成立：此前步骤标记 `DISCARDED`，不写状态或事件，只写一次
  `REJECTED_ACTION`。合法结算得到的失败则是 canonical attempt，不回滚。
- 条件只允许程序可计算的四种谓词。后一步 Event 以 `cause_event_ids` 连接前一步 Event。
- 短计划总耗时由内容包限制（当前一天）；MOVE 只能最后执行，query 不得混入。跨日复杂行动必须
  拆成 Turn，使世界模拟在步骤间推进。
- Null/fallback parser 无能力可靠编译复合计划时明确要求拆分，禁止只执行识别到的第一项。

**后果**
自然语言可表达紧耦合复合行为，同时 Code 仍逐步决定什么能发生、数据库只收到一个原子事实集合。
计划不是宏脚本或多年任务系统；长期 NPC 计划继续使用独立 Goal 生命周期与 Temporal Jump。

**可逆性**: 中。可增加新的确定性谓词或更高层编译器，但不能恢复自由文本条件或静默忽略步骤。

---

## D-019 Temporal Jump 必须保留死亡前的人生，并由一致性门验证事件时间序

**背景**
旧的长期模拟先计算跳跃终点的死亡名单，再只让“终点仍存活”的 NPC 推进 Goal。这会让一个在
十年跳跃第七年寿终的重要 NPC 丢失此前七年的全部行动；Director 却已经使用精确死亡时刻判断
事件是否仍可发生。同一时间轴因子系统不同而产生矛盾。一致性门也只拒绝回合开始前已死亡角色，
无法发现同一 ChangeSet 内排在死亡之后的事件。

**决策**
- 自然死亡继续以确定的 canonical `DEATH.world_minute` 为边界。
- 每个重要 NPC 的 Goal 推进终点为 `min(jump_end, death_minute - 1)`；死亡当刻及以后不得行动。
- 日程移动、恢复和传言候选只使用跳跃终点仍存活的角色，避免把死者投影到终点状态。
- `ConsistencyGuard` 比较同一 ChangeSet 内所有参与事件与死亡事件的时间；除死亡事件本身外，
  角色在 `event_minute >= death_minute` 时参与事件一律拒绝。
- 破坏性测试把死亡前 Goal、死亡后 Director 取消、错过任务、跨多年推进放入同一跳跃，并通过
  完整 Turn 验证提交后的时间序；玩家说出假命题只记录为话语，不改变客观事实或 NPC 知识。

**后果**
Temporal Jump 不再以终点快照抹掉人物已经生活过的时间，且未来新增模拟模块即使产生死后事件，
也会在最终提交前被一致性门阻断。长期跳跃成本仍由 Goal 步骤数和物化事件上限约束，不恢复逐 Tick。

**可逆性**: 低。具体寿命模型可由内容规则演化，但“死亡前可行动、死亡后不可行动”的时间序不可放宽。

---

## D-020 数据库负责合理性与记忆，不负责限制可玩性；世界可以就地生长

**背景**
内容包写死了地点表与人物表，任何未被写下的引用都会在意图绑定阶段失败，回合以
`AMBIGUOUS_INTENT` 结束、世界时间不推进，玩家还会看到内部枚举名。实测一局中，
「我走进青云观」「我要进入大殿进行灵力测试」「我假装喝醉去找药铺老板聊天」全部被打回——
而 `青云主殿` 与 `百草堂` 其实就在世界里，只是意图上下文只喂了当前地点的邻接点。
玩家因此退化为反复输入唯一被识别的动作（打坐修炼），可玩性归零。

**决策**
- 拒绝不再是默认反应。意图解析器只负责*理解*，不再承担把关职责；
  `needs_clarification` 的门槛降到"完全读不出想做什么"，且该路径不再向玩家暴露 reason code。
- 意图上下文改喂**全世界**地点与不在场人物；跨地点行动交由既有寻路与时间规则处理。
- 新增 `WorldSteward`（`engine/world/steward.py`）：先按别名表→精确名→包含匹配在
  已有实体中辨认；确实缺失时才由模型提议新实体。
- **模型提议什么可以存在，代码决定什么被允许存在**：新角色强制为 MINOR_NPC、
  境界不得超过玩家 +1 个大境界、必须落在已有地点；新地点必须挂在已有地点之下、
  危险度 ≤ 母地点 +1、灵气浓度 ≤ 母地点 ×1.2、路程 1—240 分钟；
  单回合上限 2 地点 / 3 人物；key 必须全新且为 snake_case。
- 新增 `CHARACTER_SPAWN` / `LOCATION_SPAWN` 两种 ChangeKind，与本回合其余变更同一事务提交，
  因此新实体从下一回合起就是普通世界状态：可被检索、可被记住、可被一致性门校验。

**后果**
世界从"白名单"变成"锚点"：数据库继续保证一致性与记忆，但不再充当可玩性的闸门。
代价是世界会随游玩变大，且新实体质量取决于模型；边界由上述钳制而非提示词保证。
即兴人物永远不会盖过内容包写就的重要角色——那仍然是 Director 的职权。

**可逆性**: 中。钳制阈值与单回合上限可调；但"未写下的东西不得成为拒绝玩家的理由"这一原则不再放宽。

---

## D-021 每回合输出场景与 StoryBeat，而非一行结算播报

**背景**
叙事层每回合只产出一句模板结论（"你盘膝坐下……修为推进了 4.0%"），且 NPC 兜底模板把内部
枚举拼进正文（"韩墨neutral。"）。更根本的是交互形态：每输入一句就得到一句判决，
是命令行问答，不是小说。玩家也无从判断何时该自己做决定。

**决策**
- 叙事模型一次产出「正文 + `---BEAT---` + 紧凑 JSON」：最初正文是 300—600 字的完整场景
  （现由 D-027 的 400—4000 字请求上限取代），
  BEAT 声明这一段是否真的需要玩家决定、戏内提示句与 2—4 个当下可做的具体选项。
- BEAT 块缺失或不可解析时只丢弃 BEAT，正文照常呈现；选项退回确定性 `_choices`。
- 内容包新增 `continue_words`；玩家输入「继续」时由 `Autopilot` 代角色选出符合处境的下一步，
  再走同一套规则、RNG 与 NPC 决策——自动推进改变的是谁按下按钮，不是谁裁决结果。
- 会话开始时运行 `Prologue`：写出角色是谁、此地正在发生什么、三件当下可做的事，
  并把角色动机写入 `short_term_goals`，供 Autopilot 与 Director 取用。
- 任何情况下都不再向玩家展示 `reason_code`：被规则拒绝的行动由叙事写成戏。

**后果**
回合从"指令→判决"变为"场景→抉择点"，且非关键段落可以由 AI 演完。
代价是每回合叙事 token 预算显著上升，且叙事调用同时承担了 BEAT 结构化输出的职责。

**可逆性**: 中。BEAT 可改为独立调用以换取更稳的结构化输出，代价是每回合多一次往返。

---

## D-022 推理模型的隐藏思考与正文共用输出预算，必须显式处理

**背景**
接入 `doubao-seed` 系列后，游戏每回合仍全部退化为模板。追查发现 provider 把空 `content`
当作合法响应返回，而空的原因是：推理模型先用 `max_tokens` 生成隐藏的 `reasoning_content`，
预算耗尽后正文为空。实测同一句 105 字的回答，开启思考模式耗时 30.9 秒 / 1400 completion tokens，
关闭后 4.2 秒 / 89 tokens。文字 RPG 每回合有 4—5 次串行调用，这个差异决定游戏能否玩。

**决策**
- 空正文不再是"合法响应"：provider 抛出 `LLMTruncated`，`LLMClient` 加倍预算重试，
  重试次数由 `LLM_TRUNCATION_RETRIES` 控制，耗尽后才允许调用方降级。
- 学到的预算按 role 记入 `_budget_floor` 并在进程内复用；否则修复重试会与预算重试相乘，
  单个阶段的最坏耗时可达数分钟。
- 新增 `LLM_EXTRA_BODY`：逐字合并进请求体的 JSON，厂商开关（如思考模式）写在配置里，
  代码中依然不出现任何厂商名或模型名（§48 不变）。
- 各 role 输出预算整体上调，并可由 `LLM_OUTPUT_BUDGET_SCALE` 统一缩放。

**后果**
"模型可用但游戏全程退化"这一类静默失败被消除，且失败会被记录而非吞掉。
代价是遇到真正的长响应时可能多付一次调用。

**可逆性**: 高。纯属 LLM 传输层策略，不影响世界语义。

---

## D-023 一个回合是一段故事，不是一个动作；交还控制权的时机由代码判定

**背景**
D-021 把每回合的产出从"一行结算播报"提升为"一个场景 + StoryBeat"，但交互粒度没变：
玩家输入一句 → 得到一段文字 → 再输入一句。`继续` 也只推进一个回合，等于把打字换成了点按钮。
实测反馈是"输入了一段内容结果返回了一段，没什么太大意义"——**问题不在文笔，在推进粒度**。
一部小说里真正需要主角做决定的时刻很稀疏，中间全是赶路、打听、把答应的事办完；
让玩家逐句驱动这些，既累又无趣。

**决策**
- 新增 `GameOrchestrator.advance()` 作为游戏的实际主入口（`play_turn` 保留为单回合 API）：
  **玩家的动作 + 角色自行推进，直到出现只有玩家能回答的事**，整段一次性返回。
- **中断时机由 `engine/orchestrator/interrupt.py` 确定性判定**，不询问模型：
  重要人物开口对你说话、NPC 对你动手或递物、掉血超过阈值、有人死亡、
  差事摆到面前、导演触发即时事件、事件重要度越线。
  叙事模型的 `needs_player` 只作为**最弱的一票**，排在所有事实信号之后。
  阈值全部来自内容包 `auto_advance.*`，题材可自行调节松紧。
- **一次规划、逐步裁决**：`Autopilot.plan_run()` 一次调用规划最多 N 步，
  但每一步仍单独绑定、单独走规则引擎、单独提交为一个完整 Turn。
  中断发生时，计划中剩余的步骤直接作废。
- **一次叙事**：整段跑完后由 `ChapterRenderer` 写成**一章**（初版 600—1000 字；现见 D-027），
  而不是每步一段。这既快（N 次叙事调用 → 1 次）又更好读——
  章节可以把四个时辰的赶路压成一句，把真正的对峙展开写。
- 一段跑动记为**一条 `chapter` 叙事片段**，下一章的上下文读到的是连续故事而非碎片。
- 没有配置模型时**不自动推进**：确定性兜底每次都选同一个安全动作，
  连跑五步只会让角色打坐五次，比不跑更糟。此时行为退回单回合，与旧版一致。

**后果**
玩家的输入频率从"每个动作一次"降到"每个抉择一次"，这正是想要的节奏。
代价是单次请求的墙钟时间变长（覆盖数步而非一步），且 `TurnResult` 的语义从
"一个回合"变为"一段故事"（新增 `steps` 与 `interrupt` 字段）。
审计没有被批量化：每一步仍是独立提交、独立留痕的 Turn，只是叙事被合并。

**可逆性**: 中。`auto_advance.max_steps: 1` 可退回逐动作节奏而无需改代码；
但"何时该交还控制权由代码而非模型判定"这一条不再放宽。

---

## D-024 这是"玩家可以干涉的小说"，不是回合制 RPG：上下文连贯优先于机制纯粹

**背景**
D-023 把推进粒度从"一个动作"提到"一段跑动"后，实测反馈仍然是三条硬伤：

1. **玩家的话被无视。** 玩家说「过去看看是干什么的」，指的是上一章结尾刚贴出的告示；
   引擎却跑去问另一个 NPC、查另一桩案子。根因：`Autopilot.plan_run()` 只拿到
   角色的 `short_term_goals` 与近期叙事，**从未拿到玩家刚说的那句话**，
   于是按自己的议程规划了一整程。这不是文笔问题，是意图在管线里丢了。
2. **前因后果缺失。** 开局 360 字，直接把玩家扔进宗门，不交代身世、来历、
   怎么进的宗门、这三个月怎么过的。读者不知道自己是谁，也就无从代入。
3. **文风过于文艺，内容过少。** 每章 600—700 字，且堆砌"指尖悬在……上方半寸处"
   这类句式。受众要的是好读的网络小说，不是散文。

**决策**
- **玩家的话是第一原则。** `plan_run()` 新增 `player_input` / `player_did`，
  提示词第一节即规定：规划的每一步都必须是在把玩家说的那件事做完，或是它的直接后果；
  只有玩家什么都没说（纯「继续」）时，才回落到角色自身目标。
- **上一章与其结尾必须完整进入意图解析。** 新增 `pending_beat`（上一章悬着的问题与选项），
  意图上下文的 `recent_narrative` 从 800 字提到 2500 字，预算 1200→2600。
  玩家十有八九在回应上一章结尾，省略宾语的说法（"过去看看"）的宾语就在那里。
- **在场人物必须带身份进入叙事上下文**：姓名/性别/境界/身份/说话方式/与主角关系。
  此前只喂一串姓名，导致外门弟子被写成杂役、女性被写成"青年"——读者一眼就能看出破绽。
- **开局改写为完整第一章**（1200—1800 字）：出身、家里出了什么事、
  怎么进的宗门、进来之后这三个月怎么过的，全部用具体的事带出来，且必须平凡。
- **章节目标长度当时由 600—1000 字提高到 1500—2500 字**，`auto_advance.max_steps` 5 → 8；
  D-027 后改为用户可控的 400—4000 字上限。
- **文风改为白话**：提示词明令少写景、多写人与对话，并把实测中反复出现的 AI 腔
  （"心里微沉""指尖悬在""目光扫过……又落回"等）加入内容包的 `avoid_phrases`。
- **章节改为真流式**：`ChapterRenderer` 走 `stream_text`，边写边推给前端，
  并在遇到 `---BEAT---` 前保留尾部窗口，保证结构化块不会泄漏进正文。

**后果**
玩家一次输入换来的是一章可读的小说，而不是一小格进度；他说的话不会再被覆盖。
代价是单次请求更长（覆盖至多 8 步；当前篇幅由玩家设定），上下文与输出预算随上限上升。

**可逆性**: 中。长度与步数都是内容包/配置项；
但"玩家刚说的话优先于角色自身目标"这一条不再放宽——它是这个产品与回合制 RPG 的分界。

### 补记：开局那一章此前根本没有落库

排查上面第 1 条时发现了更深的一层：`open_session()` 把第一章**返回给了客户端，却从未写进数据库**。
于是玩家的第一次输入永远是在回应一段引擎从未见过的文字——
`recent_narrative` 是空的，`pending_beat` 也是空的，
「过去看看是干什么的」自然无从解析，只能退回角色的既有目标。
这解释了玩家报告里"方向全变了"的现象，也解释了为什么只修 Autopilot 之后第一步仍会跑偏。

现在第一章作为 `kind="chapter"` 的叙事片段落库，其 beat 作为 `kind="beat"` 的片段单独落库
（`BEAT_SEGMENT`，不参与 `recent_narrative` 拼接，只供 `_pending_beat` 读取）。

### 补记：一段跑动里每个在场者都在调用模型

同一次排查中发现单回合耗时可达 445 秒。原因是 `_run_npcs` 对**每一步的每一个在场角色**
都发起一次 LLM 决策：5 步 × 3 人 = 15 次调用，再叠加结构化输出的修复重试。
现在只有**被搭话的对象**（永远算数，不占额度）与少量重要角色动用模型，
其余走确定性启发式，额度由内容包 `auto_advance.npc_llm_per_step` 控制。
围观者的心理活动本来也不会出现在正文里。

---

## D-025 存档是整份世界的拷贝，不是回放，也不是逆向撤销

**背景**
玩家需要存档、读档与重新开始。读档的语义是"回到那个时刻"，而这在本引擎里不能靠撤销实现：
事件日志是 append-only，记忆是事件的投影，叙事文本根本不可逆。
逐条反转 `StateChange` 只能还原数值字段，还不回事件、记忆与已经读过的章节。

**决策**
- **存档 = 把该 session 的所有行整份拷贝进一条 `save_slots` 记录**。
  世界侧的表按 `world_id` 取（地点/人物/关系/信念/记忆/事件/任务/线程/导演事件），
  故事侧的表按 `session_id` 取（会话/回合/回合轨迹/叙事片段），
  背包/功法/知识三张表通过角色 id 取。整个青云界不过数百行，直接拷贝既诚实又便宜。
- **读档 = 删掉当前这些行，再把快照写回去**。此后发生的一切被丢弃，这正是玩家要的语义。
- 实现放在 `database/saves.py`，**泛型遍历表清单**而非逐表手写映射：
  新增一张表只需加进清单，不必再写一遍搬运代码。
- **仅 SQL 后端提供存档**。内存 UoW 服务于 CLI 与测试，其生命周期就是一个进程，
  给它加存档没有意义；网页版本来就跑在 SQL 上。
- **重新开始 = 开一局全新游戏**，不删除任何东西——旧进度仍可通过存档找回。

**后果**
读档能真正还原玩家看到过的世界与读过的章节，而不是一个数值对得上、故事却错乱的近似。
代价是每个存档占用一份世界快照（当前内容包下约数百 KB 量级），且存档与内容包版本耦合：
内容包结构大改后，旧存档可能无法正确载入。

**可逆性**: 中。存档格式可以换（例如改为增量或压缩），但"读档必须还原故事而不仅是数值"不再放宽。

---

## D-026 这是连载小说不是模拟器：主动推进既有压力，而不是制造随机热闹

**背景**
玩家反馈"剧情太过于平淡毫无意思……一个草药丢失了搞了半天……现在人很浮躁，
不能很快感觉到爽的东西就不会再玩了"。

追查发现问题不在文笔，在**默认取向**：

- `prompts/director_v1.md` 原文写着"**避免持续升级，允许平静期**……若现在无需事件，返回 `NO_EVENT`"，
  并规定张力高于 75 就降温。这是一份为文学克制写的提示词。
- `director.min_interval_turns: 3` / `cooldown_after_event_turns: 4` / `max_events_per_day: 2`
  三重闸门叠加，导演几乎不开火。
- 于是主线（血魔宗渗透、黑风谷失踪案、赤霞秘境）一直躺在内容包里没被推进，
  玩家看到的只有它们的**伏笔碎片**（"灵药又少了几株"），自然味同嚼蜡。
- Autopilot 在没有明确指令时会去"办正事"——打坐、闲逛、盘点家当，
  每一步都合理，合起来就是流水账。

**决策**
把"不能无聊"提升为与"不能自相矛盾"同级的硬要求，但压力必须来自 canonical 因果：

- **Director 主动推进既有线程**：提示词要求长时间没有目标、阻碍或后果时推进主线，
  节奏定为 `受压 → 谋划 → 反击 → 得利 → 更大的麻烦`；
  已有后果正在落地、角色面临选择或缺少因果依据时必须返回 `NO_EVENT`，禁止按固定频率硬造反转。
  闸门放开：`min_interval_turns 3→1`、`cooldown 4→1`、`max_events_per_day 2→6`、
  `high_importance_override 0.7→0.5`。
- **章节提示词只压缩无效过程**。`BUDGET` 收尾只能落在最后一个已裁定事实的未解决影响上；
  不得补写人物到场、物品异动、跟踪者或新线索来伪造钩子。
- **序章使用落库的倒计时与麻烦**：玩家持有的血名册、玩家已知 Fact 和 Director 已调度事件
  先进入 canonical state，序章不得另编家庭苦难、凶手、证据或行动结果。
- **Autopilot 禁止办无关杂事**：没有明确指令时去追最紧要的目标，
  "惹上麻烦的一章比平安无事的一章好看"。

**后果**
世界仍独立演化，但内容包在开局就提供高压的既有因果，Director 只选择何时推进，Narrative 只复述。
这样获得快节奏而不让世界显得凭空围着主角转。导演事件频率上升仍会增加 LLM 调用与 token 消耗。

**可逆性**: 高。所有阈值都在 `content/<pack>/rules.yaml::director` 里；
想要慢节奏世界，把闸门调回去即可，提示词也可以按版本回退。

---

## D-027 性别自适应共同主角与长度偏好必须进入正式契约

**背景**
旧内容包只有零散失窃案，开场缺少直接针对玩家的目标；人物关系与生成长度也只能靠提示词或固定值，
无法跨回合稳定复现。把搭档写死在序章会导致 Narrative 决定世界事实，把长度只写在 prompt 则无法保证上限。

**决策**

- 内容包在 `story.lead_by_player_gender` 声明候选：男性玩家匹配成年女性共同主角，女性玩家匹配成年男性
  共同主角。Seeder 将选择写入玩家/NPC metadata，并创建带 `co_protagonist`、`romance_candidate`
  标签的双向关系；未声明的性别不强塞搭档。
- 玩家与候选均须成年。关系可以有基于同意、非露骨的成年人张力，但玩家可拒绝，任何关系变化仍必须
  由已验证 Action/Event 支撑。
- 血名册残页、七日开启、搜查令等开局信息先作为 Inventory/Fact/DirectorEvent 落库；序章只接收玩家
  可见事实，不能把小说修辞反向变成开局真相。
- `narrative_max_chars` 加入 Start/Action/Turn DTO，范围 400—4000，也是幂等请求身份的一部分。
  它同时控制 prompt 目标、供应商 token 预算、流式保留窗口和最终中文句末钳制。
- 题材文字与中文展示标签仍属于 Content Pack；通用 Engine 不硬编码性别、关系或故事文案。

**后果**
同一世界内容可随玩家选择形成不同共同主角，但选择、关系和线索都可审计；用户可自由权衡篇幅、等待时间
和调用成本，而不会改变 canonical 结果。旧客户端不传长度时继续使用 1800 字默认值。

**可逆性**: 中。候选与文风可以只改内容包；DTO 字段与幂等语义属于公开契约，不应无迁移移除。
