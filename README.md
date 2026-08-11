# AI Narrative World Engine

一个 **AI 原生开放世界文字 RPG 引擎**。当前修仙内容包是快节奏悬疑冒险《七日血契》。

> 世界先存在，剧情是玩家与世界交互之后产生的结果。
>
> **Code determines what CAN happen. Database determines what IS true.
> AI determines intent, reasoning, behavior and expression.**

这不是"一个大 Prompt + 一次 LLM 调用"。玩家的自然语言先被解析成结构化 Action，
经过确定性规则引擎裁决、RNG 结算、NPC 决策、世界模拟、剧情导演判断、
一致性校验与单事务提交之后，**最后**才由叙事模型把已经发生的事实写成小说。

---

## 快速开始

本项目在 conda 环境 `game` 中开发、运行与测试。

```bash
# 1. 环境（已创建则跳过）
conda create -n game python=3.12 -y
conda activate game
pip install -e ".[dev,postgres,redis,llm]"      # 或 pip install -r 见 pyproject

# 2. 配置（PowerShell）
Copy-Item .env.example .env     # 默认 LLM_PROVIDER=null，无需任何 API Key 即可运行

# 3. 建表
python -m alembic upgrade head

# 4. 玩（终端）
python scripts/play_cli.py --name 沈砚

# 5. 玩（浏览器）
python -m uvicorn apps.api.main:app --reload
#   → http://127.0.0.1:8000
```

浏览器必须打开 `.env` 中 `API_PORT` 对应的端口。例如 `API_PORT=8012` 时访问
`http://127.0.0.1:8012`，不要固定使用 8000。若看到 `ERR_EMPTY_RESPONSE`，先确认运行
uvicorn 的终端没有退出或报错，再访问同一端口的 `/api/health`；它应返回
`{"status":"ok"}`。如果该端口已被其他程序占用，请更换 `API_PORT` 后重启 uvicorn。

不配置任何 LLM 也能完整游玩：意图解析、NPC 决策、剧情导演、叙事全部有确定性
实现兜底（见 `docs/DECISIONS.md` D-007）。通常只需在 `.env` 填统一的 API 地址、
密钥和默认模型；所有文字角色会沿用 `LLM_MODEL`：

```dotenv
LLM_PROVIDER=compatible
LLM_API_KEY=替换成你的密钥
LLM_BASE_URL=https://example.com/v1
LLM_MODEL=替换成模型名
```

有多个同服务的 Key 时，把 `LLM_API_KEY` 换成逗号分隔的 `LLM_API_KEYS`。请求会轮询
分配到 Key 池，能提高多玩家、多会话或多个独立角色请求的并发吞吐，并绕开单 Key 的并发
上限；同一回合的意图、裁决和叙事互相依赖，因此多个 Key 不会把这些阶段变成并行执行。

```dotenv
LLM_PROVIDER=compatible
LLM_API_KEYS=key-1,key-2,key-3
LLM_BASE_URL=https://example.com/v1
LLM_MODEL=默认模型名
```

如果某个角色需要不同模型，只填写对应的覆盖项，例如 `NARRATIVE_MODEL=更强的写作模型`；
`INTENT_MODEL`、`NPC_MODEL`、`NPC_MAJOR_MODEL`、`DIRECTOR_MODEL`、`STEWARD_MODEL` 和
`MEMORY_MODEL` 都是可选项。旧的 `COMPATIBLE_API_KEY`、`OPENAI_API_KEY`、
`ANTHROPIC_API_KEY` 及各角色模型配置仍然兼容。修改 `.env` 后需要重启 uvicorn。

### 用推理模型时先关掉思考模式

推理模型的隐藏思考与正文**共用同一个输出预算**：预算被思考吃光时，接口会返回空正文，
上游只能退化成模板播报——游戏看起来"能跑"，实际全程没有小说。引擎现在会把空正文当作
可重试的预算问题（加倍重试，见 D-022），但真正的解法是关掉它：

```dotenv
# 实测同一句 105 字的回答：开启 30.9s / 1400 tokens，关闭 4.2s / 89 tokens。
# 字段名以你的端点文档为准，这里逐字合并进请求体。
LLM_EXTRA_BODY={"thinking":{"type":"disabled"}}
```

一个回合有 4—5 次串行调用，这个开关基本决定了游戏是"能玩"还是"等到烦"。

---

## 它到底做了什么

一个回合走完这条流水线（`docs/GAME_LOOP.md`）：

**这是一部玩家可以干涉的小说，不是回合制 RPG。**

一次输入不是一个动作，是一段故事：玩家说一句话，角色会**接着这句话**把该做的事做完——
赶路、打听、把答应的差事办完——直到出现只有玩家能回答的事才停下来（`advance()`），
整段写成一章小说。网页中的滑杆与最大值输入可把单次正文上限设为 400—4000 字（默认 1800）；
上限会参与模型 token 预算，并由程序在中文句末再次钳制，只影响表达长度，不改变已提交的世界结果。

因此这三件事被当作硬要求，而不是锦上添花：

- **玩家说的话优先于角色自身目标。** 规划下一程时，玩家刚说的那句话是第一原则；
  只有他什么都没说（纯「继续」）才回落到角色的动机（D-024）。
- **上一章及其结尾完整进入意图解析。** 玩家十有八九在回应上一章的结尾，
  「过去看看」的宾语就在那里。
- **在场人物带身份进入叙事**（性别/境界/身份/说话方式/与主角的关系），
  否则外门弟子会被写成杂役，同一个人前后判若两人。

```text
玩家自然语言（或「继续」）
  ↓
  ├─ 玩家这一步：IntentParser → WorldSteward → 规则裁决 → 提交
  └─ 然后角色自己往下走：Autopilot 一次规划数步，逐步裁决、逐步提交
        每步之后由 InterruptDetector 判断：该把笔交还给玩家了吗？
  ↓
  ChapterRenderer      把这一整程写成【一章】小说 + StoryBeat
```

单步内部仍是原来那条流水线：

```text
  → IntentParser        自然语言 → Action（不决定成败，也不负责把关）
  → WorldSteward        玩家提到而世界还没有的人/地点：先辨认，再就地创造并落库
  → RuleEngine          12 个确定性规则族裁决，LLM 无权推翻
  → ActionResolver      GameRNG 结算，产出事实
  → NPCAgent            在场 NPC 决策（只能提 proposal）
  → WorldSimulator      LOD 0-3 推进世界，玩家不在的地方照样变化
  → Director            判断哪条已有因果值得现在发展
  → ProposalValidator   AI 提案二次校验 + 幅度钳制
  → ConsistencyGuard    提交前 canonical 一致性检查
  → 单事务提交          世界变更 + 事件 + CANONICAL_COMMITTED Turn 原子落盘
  → MemoryExtractor     canonical event → 可恢复、owner/event 幂等的长期记忆投影
```

### 什么时候把控制权交还给玩家

由代码判定，不问模型（`engine/orchestrator/interrupt.py`）：

| 停下来 | 继续演 |
|---|---|
| 重要人物开口对你说话 | 路人之间的闲聊 |
| 有人对你动手、递东西、拦住你 | NPC 各忙各的 |
| 掉血超过阈值、有人死了 | 走了四个时辰的路 |
| 差事摆到了面前 | 打坐、采买、等天亮 |
| 导演触发了即时事件、事件重要度越线 | 平淡的成功与失败 |

叙事模型也能投一票（`needs_player`），但排在所有事实信号**之后**——
交还控制权的时机不该取决于模型当时的心情。阈值全在内容包 `auto_advance.*` 里。

会话开始时另有一次 `Prologue`：写出角色是谁、此地正在发生什么、眼下有哪三件事可做，
并把角色当下的动机写进 `short_term_goals`，供 Autopilot 与 Director 后续取用。

### 数据库负责合理性与记忆，不负责限制可玩性

这是本项目的一条硬原则：**世界缺一个人或一个地方，是世界的问题，不是玩家的问题。**

- 玩家说「去大殿」「找药铺老板」时，`WorldSteward` 先在**全世界**范围内辨认
  （别名表 → 精确名 → 包含匹配），确实没有才交给模型创造。
- 模型只提议*应该存在什么*；**允许存在什么由代码钳制**：新角色只能是配角，
  境界不得高于玩家一个大境界，新地点必须挂在已有地点之下且危险度不得超过母地点 +1，
  单回合上限 2 地点 / 3 人物。
- 创造出的实体通过 `CHARACTER_SPAWN` / `LOCATION_SPAWN` 与本回合其它变更**同一事务落库**，
  从下一回合起就是普通世界状态：会被记住、会被检索、和内容包自带的东西一样真实。

具体做到了什么：

| 承诺 | 实现 | 验证 |
|---|---|---|
| 玩家提到世界没有的东西，不会被打回 | `WorldSteward` 辨认 → 创造 → 同事务落库 | `tests/unit/test_steward.py` |
| AI 造物不会破坏世界平衡 | 类型/境界/危险度/数量全部由代码钳制 | `tests/unit/test_steward.py` |
| 不是问答，是小说 | 一次输入推进数个回合，写成一章 + `StoryBeat` | `tests/integration/test_advance.py` |
| 玩家不必逐句下指令 | `Autopilot` 一次规划数步，代角色把该做的事做完 | `tests/integration/test_advance.py` |
| 该停的时候一定会停 | `InterruptDetector` 按已提交事实判定，不问模型 | `tests/unit/test_interrupt.py` |
| 玩家说的话不会被覆盖 | 规划以玩家原话为第一原则，纯「继续」才用角色目标 | `tests/integration/test_advance.py` |
| 开局立刻进入主线 | 血名册、七日倒计时与搜查令先作为物品/Fact 落库，序章只能复述玩家已知事实 | `tests/unit/test_story_setup.py` |
| 人物前后不会判若两人 | 在场人物带身份/性别/说话方式进入叙事上下文 | `prompts/chapter_v1.md` |
| 读档能真正回到那一刻 | 存档是整份世界拷贝，连读过的章节一起还原 | `tests/integration/test_database.py` |
| 合并叙事不合并审计 | 每一步仍是独立提交、独立留痕的 Turn | `tests/integration/test_advance.py` |
| 玩家上来知道自己是谁、能干什么 | `Prologue` 写开局并写入 `short_term_goals` | `tests/unit/test_story_beat.py` |
| 男女玩家都有共同主角 | 男性玩家匹配林清雪、女性玩家匹配赵无极；关系、位置和标签进入 canonical state | `tests/unit/test_story_setup.py` |
| 成年关系不污染主线 | 玩家年龄至少 18；允许克制、非露骨且基于同意的关系张力，玩家可拒绝 | `content/cultivation_v1/pack.yaml` |

| 承诺 | 实现 | 验证 |
|---|---|---|
| 不合理行为世界会拒绝 | `engine/rules/` 12 个规则族 + `ReasonCode` | `tests/unit/test_rules.py` |
| 复杂自然语言不会丢步骤 | 短 ActionPlan 逐 primitive 投影验证、结构化条件、原子 ChangeSet | `tests/unit/test_action_plans.py`、`tests/integration/test_full_turn.py` |
| NPC 只按自己知道的信息行动 | `facts` / `character_knowledge` 分离，`ContextBuilder` 只喂 belief | `tests/unit/test_knowledge_isolation.py` |
| 一次寒暄不会 trust +50 | 关系 8 维 + 按事件重要性分档钳制 + 审计行 | `tests/unit/test_relationships.py` |
| 死亡永久生效 | `ConsistencyGuard` 禁止复活、禁止死人参与新事件 | `tests/evals/test_evals.py` |
| 剧情不会永远高潮 | 张力波形 + `must_de_escalate` 硬约束 | `tests/evals/test_evals.py` |
| 玩家闭关数十年，世界会变 | Temporal Jump 聚合势力/事件，NPC 变老、寿终，任务不会等待 | `tests/unit/test_temporal_jump.py`、`tests/integration/test_full_turn.py` |
| 重要 NPC 离开玩家后仍追求目标 | 持久 Goal→Plan→Action→Result；长跨度聚合重试，结果写 canonical event | `tests/unit/test_npc_goals.py`、`tests/integration/test_database.py` |
| Director 事件不会重复或失约 | 独立生命周期、因果去重、未来调度、到期重校验与每日容量 | `tests/unit/test_director_lifecycle.py`、`tests/integration/test_full_turn.py` |
| 过去影响未来 | append-only event log + `cause_event_ids` + 四层记忆复合检索 | `tests/evals/test_evals.py` |
| 小说修辞不会变成长期事实 | Memory 只持久化 canonical event 描述；投影失败可重试且 owner/event 唯一 | `tests/unit/test_memory_projection.py`、`tests/integration/test_full_turn.py` |
| 模型返回 JSON ≠ 正确 | schema 校验 → 修复重试 → fallback，全程留痕 | `tests/evals/test_evals.py` |
| 叙事失败不能重复行为 | Turn 状态机 + canonical 恢复胶囊；同 key 只补叙事 | `tests/integration/test_full_turn.py` |

---

## 目录

```text
apps/
  api/          FastAPI：REST + SSE + Debug/Inspector 端点
  web/          零构建单页 UI（三栏 + Debug Panel）
engine/         纯领域层，不 import SQLAlchemy / FastAPI
  orchestrator/ 回合调度、事务边界、提案校验、可观测性
  actions/      Action schema、意图解析、行动结算
  rules/        movement / cultivation / combat / skills / inventory /
                economy / interaction / detection / location / time / faction
  rng/          GameRNG：seed 派生 + 全量 trace，可回放
  world/        WorldClock、位置图、状态快照、一致性守卫、世界播种
  knowledge/    truth vs belief，信息传播
  memory/       四层记忆、embedding、复合排序检索、记忆抽取
  characters/   NPC 决策代理（LLM + 启发式）
  relationships/ 8 维关系与钳制
  director/     剧情线程、张力模型、提案校验
  narrative/    叙事渲染、AI 味控制、模板兜底
  context/      逐 Agent 上下文构造 + token 预算
  llm/          Provider 抽象、ModelRouter、结构化输出与修复
  simulation/   LOD 0-3、NPC 日程、离线世界事件
  contentpack/  YAML 内容包加载、校验与版本化 Rule Plugin 装载
database/       SQLAlchemy 2.x models / mappers / repositories / Alembic
                （另含 memory_uow.py：全内存实现，测试与 CLI 用）
content/
  cultivation_v1/  世界观与题材规则：YAML 数据 + 受信任 Rule Plugin
prompts/        版本化 prompt 文件 + registry
tests/          unit / integration / evals
docs/           架构、数据模型、回合、AI 流水线、Prompt、路线图、决策记录
scripts/        seed_world.py / play_cli.py
```

`engine/` 不包含修仙专有的验证或结算分支。通用移动、社交、物品、战斗等规则留在
Engine；修炼与突破由 `content/cultivation_v1/rule_plugin.py` 接管。仅更换 YAML 可以创建
同机制的新世界；更换题材机制需要显式、版本化的受信任 Rule Plugin。现有角色 schema 仍保留
`realm/spiritual_power` 等 V1 兼容字段，尚不能据此声称任意题材零改造即插即用。

---

## 开发

```bash
pytest                       # 以完整测试输出为准
pytest tests/evals -q        # 只跑 AI 行为评测
ruff check .                 # lint
mypy engine database apps prompts   # 类型检查

python scripts/seed_world.py --player 沈砚 --seed demo-1
python scripts/play_cli.py --name 沈砚 --script "我环顾四周" "我闭关修炼3年"
```

Debug Panel（浏览器右下角按钮）可以看到每一回合的：
Intent 解析 / Rule 结果 / RNG / Action 结果 / NPC Decision（含它看到的 Context 快照）/
Director 决策与被驳回原因 / 提案钳制记录 / Memory 写入 / State Changes /
LLM 调用（模型、prompt 版本、token、延迟）/ 各阶段耗时。

World Inspector：`GET /api/admin/world/{id}/inspector`。

---

## 技术选型与偏离说明

宿主环境无 Node.js、无 PostgreSQL 实例，因此：

- **数据库**：SQLAlchemy 2.x 统一抽象，默认 SQLite，生产 PostgreSQL + pgvector。
  向量检索走 `VectorIndex` 接口，SQLite 下用 numpy 余弦。改 `.env` 即可切换。
- **前端**：V1 用零构建 SPA 由 FastAPI 托管，前后端只通过 REST/SSE 契约耦合，
  后续在有 Node 的机器上新建 `apps/web-next/` 可复用全部接口、后端零改动。

完整理由见 `docs/DECISIONS.md`（D-001 ~ D-010）。

---

## 文档

| 文件 | 内容 |
|---|---|
| `docs/ARCHITECTURE.md` | 分层、回合数据流、模块职责、前后端契约、可观测性 |
| `docs/DATA_MODEL.md` | 全部实体、字段、索引、扩展性预留 |
| `docs/GAME_LOOP.md` | 15 个阶段、快路径、时间推进、失败降级矩阵 |
| `docs/AI_PIPELINE.md` | 6 个 Agent 的输入输出、校验链、token 预算、模型路由 |
| `docs/PROMPTS.md` | Prompt 版本管理与记录规范 |
| `docs/ROADMAP.md` | 各阶段完成情况与 V1 之后的计划 |
| `docs/DECISIONS.md` | 重要工程决策与可逆性 |
| `docs/CURRENT_STATE.md` | Phase 0 仓库审计与环境约束 |

`prompt.md` 是本项目的原始需求规格，保持原样。
