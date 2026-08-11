# CURRENT_STATE — Phase 0 Repository Audit

**审计时间**: 2026-08-09
**审计范围**: `c:\Users\28123\Desktop\game`

## 1. 审计结果

审计前仓库内容：

```text
game/
└── prompt.md      (44,806 bytes)  —— 唯一文件，本项目的 Master Engineering Prompt
```

结论：

- **无既有源码**、无 `README`、无 `package config`、无依赖清单、无数据库、无测试。
- 不是 git 仓库（`git init` 尚未执行）。
- 因此 **不存在“不要破坏已有功能”的约束**，按 Prompt §73 “如果项目为空，从零初始化”执行。
- `prompt.md` 被视为**需求规格文档**，全程保留，不修改、不删除。

## 2. 宿主环境探测

| 项目 | 结果 | 影响 |
|---|---|---|
| OS | Windows 10 Pro 19045 | 路径/换行需注意；测试需跨平台 |
| conda | 25.7.0 (miniconda3) | ✅ 按用户要求新建环境 `game` |
| 系统 Python | 3.13.5 (base) | 不直接使用 |
| 目标 Python | 3.12 (env `game`) | 满足 Prompt §3 "Python 3.12+" |
| Node.js / npm | **不存在** | ❗ 无法构建/运行 Next.js，见 `DECISIONS.md` D-002 |
| PostgreSQL | **未探测到本地实例** | ❗ 见 `DECISIONS.md` D-001 |
| Redis | **未探测到本地实例** | ❗ 见 `DECISIONS.md` D-003 |
| git | 2.51.0 | 可用 |

## 3. 由环境推导出的工程约束

1. **数据库必须双后端**：默认 SQLite（开发/测试可零依赖运行），
   PostgreSQL + pgvector 为生产后端。所有 SQL 通过 SQLAlchemy 2.x 抽象，
   向量检索通过 `VectorIndex` 接口抽象（`PgVectorIndex` / `NumpyVectorIndex`）。
2. **前端不能依赖 Node 工具链**：V1 前端为 FastAPI 直接托管的零构建单页应用，
   保留 `apps/web/` 目录结构以便后续无痛迁移到 Next.js。
3. **Redis 可选**：并发锁/幂等键通过 `LockBackend` 接口抽象，
   默认进程内实现，生产切 Redis。
4. **所有代码在 conda env `game` 内运行与测试**（用户强制要求）。

## 4. 交付基线

Phase 0 完成时，仓库从空目录变为：

```text
game/
├── prompt.md            # 原始需求（只读）
├── pyproject.toml
├── .env.example
├── README.md
├── apps/{api,web}/
├── engine/              # 与内容无关的纯引擎
├── content/cultivation_v1/
├── prompts/
├── database/
├── tests/{unit,integration,evals}/
├── scripts/
└── docs/
```

后续状态变化记录在 `docs/ROADMAP.md` 的 Phase 完成勾选中。

---

## 5. 当前实际状态（2026-08-10）

全部 10 个 Phase 已实现、运行并通过验证。以下为**实测**结果，非计划：

| 项目 | 状态 |
|---|---|
| 测试 | `527 passed`（unit 446 / integration 64 / evals 17） |
| Lint | `ruff check .` → All checks passed |
| 类型 | `mypy .` → no issues in 109 source files |
| 迁移 | `alembic upgrade head` → 22 张表 |
| 内容包 | `cultivation_v1`《七日血契》：26 个角色（含玩家）、20 个地点、4 个势力、21 条世界事实、4 条剧情线程、3 个初始任务、4 个 canonical 倒计时事件 |
| API | 全部 §50 端点 + SSE + Debug + Inspector，已对运行中的服务实测通过 |
| 前端 | 三栏 UI + 流式叙事 + Debug Panel + 400—4000 字长度双向控件，由 FastAPI 托管 |
| LLM | 未配置（`LLM_PROVIDER=null`），全链路走确定性 fallback；接入模型只需改 `.env` |

测试分布：

```text
tests/unit/          446   规则、RNG、时钟、Action Plan、内容包/Rule Plugin、关系、事件、一致性、
                           NPC/Director 生命周期、Memory 事实来源/幂等、意图解析、知识隔离、架构守卫
tests/integration/    64   完整回合（内存/SQL）、API、Action Plan（含 SSE、幂等与 post-commit 恢复）
tests/evals/          17   §62 五个场景 + 节奏约束 + 结构化输出纪律
```

### 已知限制

1. **本轮未做真实模型文风 A/B**：所有关键 LLM 契约以 `ScriptedProvider` / `NullProvider` 验证；
   Prompt 本身的措辞质量需要真实 A/B 才能评估。
2. **pgvector 未实机验证**：向量列在 PostgreSQL 分支的 DDL 已写好但只在 SQLite
   上跑过；首次部署 Postgres 时需要执行 `CREATE EXTENSION vector` 并补一条迁移
   把 `memories.embedding` 从 JSON 改为 `vector(N)` + ivfflat 索引。
3. **前端非 Next.js**：见 D-002。当前零构建 SPA 保持 REST/SSE 解耦，可直接由 FastAPI 托管。
4. **单进程锁**：`InMemoryLockBackend` 只在单进程内正确；多 worker 部署需切 Redis。
5. **世界规模为 V1 纵切**：20 个地点、26 个角色。背景 NPC 模板已就绪但尚未批量生成。
