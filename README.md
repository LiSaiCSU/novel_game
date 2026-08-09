# AI Narrative World Engine

一个 **AI 原生开放世界文字 RPG 引擎**。第一个内容包是修仙 / 玄幻的《青云界》。

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

# 2. 配置
cp .env.example .env            # 默认 LLM_PROVIDER=null，无需任何 API Key 即可运行

# 3. 建表
python -m alembic upgrade head

# 4. 玩（终端）
python scripts/play_cli.py --name 沈砚

# 5. 玩（浏览器）
python -m uvicorn apps.api.main:app --reload
#   → http://127.0.0.1:8000
```

不配置任何 LLM 也能完整游玩：意图解析、NPC 决策、剧情导演、叙事全部有确定性
实现兜底（见 `docs/DECISIONS.md` D-007）。想接入模型，只需在 `.env` 里填
`LLM_PROVIDER` 与各角色的模型名——**代码中不出现任何模型名**。

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-...
INTENT_MODEL=...
NPC_MODEL=...
NPC_MAJOR_MODEL=...
DIRECTOR_MODEL=...
NARRATIVE_MODEL=...
MEMORY_MODEL=...
```

---

## 它到底做了什么

一个回合走完这条流水线（`docs/GAME_LOOP.md`）：

```text
玩家自然语言
  → IntentParser        自然语言 → Action（不决定成败）
  → RuleEngine          12 个确定性规则族裁决，LLM 无权推翻
  → ActionResolver      GameRNG 结算，产出事实
  → NPCAgent            在场 NPC 决策（只能提 proposal）
  → WorldSimulator      LOD 0-3 推进世界，玩家不在的地方照样变化
  → Director            判断哪条已有因果值得现在发展
  → ProposalValidator   AI 提案二次校验 + 幅度钳制
  → ConsistencyGuard    7 类一致性检查
  → 单事务提交          失败整体回滚
  → MemoryExtractor     值得记住的才写入长期记忆
  → NarrativeRenderer   把已定稿的事实写成小说（可流式）
```

具体做到了什么：

| 承诺 | 实现 | 验证 |
|---|---|---|
| 不合理行为世界会拒绝 | `engine/rules/` 12 个规则族 + `ReasonCode` | `tests/unit/test_rules.py` |
| NPC 只按自己知道的信息行动 | `facts` / `character_knowledge` 分离，`ContextBuilder` 只喂 belief | `tests/unit/test_knowledge_isolation.py` |
| 一次寒暄不会 trust +50 | 关系 8 维 + 按事件重要性分档钳制 + 审计行 | `tests/unit/test_relationships.py` |
| 死亡永久生效 | `ConsistencyGuard` 禁止复活、禁止死人参与新事件 | `tests/evals/test_evals.py` |
| 剧情不会永远高潮 | 张力波形 + `must_de_escalate` 硬约束 | `tests/evals/test_evals.py` |
| 玩家闭关三年，世界会变 | LOD 2/3 势力漂移、NPC 行程、任务被别人接走 | `tests/integration/test_full_turn.py` |
| 过去影响未来 | append-only event log + `cause_event_ids` + 四层记忆复合检索 | `tests/evals/test_evals.py` |
| 模型返回 JSON ≠ 正确 | schema 校验 → 修复重试 → fallback，全程留痕 | `tests/evals/test_evals.py` |

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
  contentpack/  YAML 内容包加载与校验
database/       SQLAlchemy 2.x models / mappers / repositories / Alembic
                （另含 memory_uow.py：全内存实现，测试与 CLI 用）
content/
  cultivation_v1/  世界观全部在这里：境界、规则数值、地点、势力、NPC、
                   物品、技能、事实、剧情线程、事件模板、叙事模板
prompts/        版本化 prompt 文件 + registry
tests/          unit / integration / evals
docs/           架构、数据模型、回合、AI 流水线、Prompt、路线图、决策记录
scripts/        seed_world.py / play_cli.py
```

**引擎不知道自己在跑修仙。** `engine/` 里没有任何中文实体名、没有"境界"这个概念的
硬编码——只有"有序的进阶阶梯"。换 `content/wuxia_v1/` 就是换一个世界。
这一点由 `tests/unit/test_engine_purity.py` 静态强制。

---

## 开发

```bash
pytest                       # 374 个测试
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
