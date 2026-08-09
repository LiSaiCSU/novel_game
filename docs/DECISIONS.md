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

**后果** 换 content pack 即换世界观；单元测试可用假 repo 全内存运行。

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
