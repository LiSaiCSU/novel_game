# ROADMAP

每个 Phase 的完成标准（§67）：实现 → 写测试 → **运行测试** → 修复 → 类型检查 → Lint → 更新文档。

---

## Phase 0 — Repository Audit ✅
- [x] 审计空仓库，产出 `docs/CURRENT_STATE.md`
- [x] 探测宿主环境（conda/python/node/git），记录约束
- [x] 创建 conda env `game` (Python 3.12) 并安装依赖

## Phase 1 — Architecture ✅
- [x] `docs/ARCHITECTURE.md` `DATA_MODEL.md` `GAME_LOOP.md` `AI_PIPELINE.md` `PROMPTS.md` `ROADMAP.md` `DECISIONS.md`
- [x] 目录骨架、`pyproject.toml`、`.env.example`

## Phase 2 — Deterministic Core ✅（不调用 LLM）
- [x] `engine/core`：ids / errors / config / ports / mutations / logging
- [x] `engine/rng`：GameRNG + seed 派生 + RngTrace
- [x] `engine/contentpack`：YAML 加载 + 校验
- [x] `engine/world`：WorldClock、位置图、WorldStateView
- [x] `engine/characters`、`engine/relationships`
- [x] `engine/actions`：Action schema + 注册表 + fallback 解析器
- [x] `engine/rules`：12 个规则族
- [x] `engine/events`：append-only event log
- [x] 单元测试全绿

## Phase 3 — Database ✅
- [x] SQLAlchemy 2.x models（SQLite/Postgres 双方言）
- [x] Alembic 迁移
- [x] repositories 实现 `engine/core/ports.py`
- [x] `scripts/seed_world.py`：从内容包播种一个完整世界
- [x] 集成测试：播种 → 查询 → 一致性

## Phase 4 — Intent AI ✅
- [x] `engine/llm`：Provider 抽象 / ModelRouter / 结构化输出与修复
- [x] `NullProvider` + `ScriptedProvider`
- [x] IntentParser + fallback 解析器
- [x] 测试：自然语言 → Action

## Phase 5 — NPC System ✅
- [x] `engine/knowledge`：facts / character_knowledge / 信息传播
- [x] `engine/context`：ContextBuilder + token 预算
- [x] `engine/characters/npc_agent.py`：LLM 决策 + 启发式 fallback
- [x] **知识隔离测试（核心测试）**

## Phase 6 — Memory ✅
- [x] 4 层记忆
- [x] `VectorIndex` 抽象（Numpy / pgvector）
- [x] 复合排序检索（similarity + importance + recency + relationship + context）
- [x] MemoryExtractor + 确定性前置过滤

## Phase 7 — Director ✅
- [x] PlotThread / NarrativeTension
- [x] Director + proposal 校验
- [x] 测试：死人不能回归、禁止连续高潮

## Phase 8 — Narrative ✅
- [x] NarrativeRenderer + 模板渲染器
- [x] AI 味控制（套路短语频次 + 重写）
- [x] Orchestrator 完整回合打通

## Phase 9 — World Simulation ✅
- [x] NPC 日程
- [x] LOD 0-3
- [x] 势力/经济/冲突离线推演
- [x] 测试：玩家离开的地方仍在变化

## Phase 10 — Frontend ✅
- [x] FastAPI 路由（§50 全部端点）
- [x] SSE 流式叙事
- [x] 三栏 UI + 背包/关系/任务/历史
- [x] Debug Panel（§52）
- [x] World Inspector（§53）

## Evals ✅
- [x] Eval 1 炼气一掌拍死元婴 → 拒绝（目标不存在 + 境界差硬阻断，双路径都测）
- [x] Eval 2 诱导 NPC 承认其不知道的事 → 不承认；且知情者反应不同（证明不是"一律否认"）
- [x] Eval 3 初见索要毕生积蓄 → 拒绝；同样请求来自挚友则概率显著更高
- [x] Eval 4 救命之恩十个月后仍能被检索到（并压过 25 条寒暄）；寒暄不入长期记忆
- [x] Eval 5 死亡 NPC 不能被 Director 复活；虚构因果 / 白名单外事件类型同样被驳回
- [x] 节奏：连续三回合高张力后 Director 被强制降温
- [x] 结构化输出：无效 JSON 重试两次后拒绝入库；被包裹在散文里的合法 JSON 仍接受
- [x] 提案钳制：AI 提出 trust +60，寒暄档位下被钳到内容包上限并记录 `clamped`

---

## V1 验收（§71 Test A–H）

| # | 问题 | 结论 | 证据 |
|---|---|---|---|
| A | 任意自然语言能否被理解？ | 部分 | fallback 解析器覆盖全部 24 种 Action 与复合/欺骗/条件表述的结构位；语义深度需真实模型。`tests/unit/test_fallback_parser.py` |
| B | 不合理行为世界能否拒绝？ | ✅ | 12 个规则族 + 30 种 `ReasonCode`。`tests/unit/test_rules.py` |
| C | NPC 是否只按自己知道的信息行动？ | ✅ | 三层防线：SQL 过滤 → `beliefs_of` → ContextBuilder。`tests/unit/test_knowledge_isolation.py` |
| D | NPC 是否保持长期人格一致？ | ✅（结构上） | 人格与情绪分表；情绪可快变，人格提案被丢弃，长期目标不接受单回合修改 |
| E | 过去行为是否真正影响未来？ | ✅ | append-only event log + `cause_event_ids` + 四层记忆复合检索 |
| F | 玩家离开的地方是否仍发生变化？ | ✅ | 闭关三年后势力资源、NPC 位置、任务归属均变化。`test_a_long_seclusion_changes_the_world` |
| G | 剧情是否来自世界因果？ | ✅ | Director 只能推进已有线程，`causal_basis` 必须指向真实事件或事实 |
| H | 玩几小时后世界是否自洽？ | ✅（程序层） | 每回合 7 类一致性检查 + 单事务提交；长时程人工试玩尚未进行 |

---

## V1 之后（未实现，按优先级）

1. **境界扩展**：元婴/化神/炼虚/合体/大乘/渡劫/仙人（只改 `realms.yaml`）
2. **第二内容包** `content/wuxia_v1/`，验证引擎与内容真正解耦
3. **Next.js 前端**（需 Node 环境，见 D-002）
4. **PostgreSQL + pgvector 生产部署**，ivfflat 索引调优
5. **Redis 分布式锁 / 多世界并发 worker**
6. **离线世界推演 worker**：玩家下线时世界继续运行
7. **AI Critic**：在 ConsistencyGuard 之后增加叙事一致性 LLM 复核
8. **回放系统**：基于 event log + rng_seed 完整重放一局
9. **多人同世界**
