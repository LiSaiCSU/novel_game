# 系统架构

本文件是代码依赖和运行时边界的契约。

## 分层

```text
apps/web-next   Next.js 玩家端、作品库、创作台、审核/设置界面
       ↓ REST + SSE (/api/v1)
apps/api        FastAPI DTO、认证、租户、运行时组装、Redis/S3/邮件适配器
       ↓                       ↓
engine          纯领域层       database
规则/回合/AI/内容端口          SQLAlchemy、Alembic、RLS、Repository、备份
       ↑                       ↑
       └──── engine/core/ports ┘

apps/worker     邮件、编译、素材、导出、过期预览等后台任务
content         官方内容源；发布后转为不可变 Content Pack v2 制品
```

自动化约束 `tests/unit/test_engine_purity.py` 保证 `engine/` 不依赖 Web、ORM、Redis 或数据库。

## 平台对象关系

```text
User ─┬─ Project ─ ProjectRevision ─ ContentRelease(immutable)
      │                                  │
      ├─ Asset                            └─ Playthrough ─ World/GameSession
      ├─ LlmCredential(encrypted)                         ├─ Turn/Event/Memory
      ├─ AuthSession                                      └─ SaveSlot
      ├─ UsageLedger
      └─ ProductEvent（主动同意、白名单字段、可即时清除）
```

- `Project` 是持续编辑对象；`revision` 处理乐观并发。
- `World` 是内容世界；`Scenario` 是入口；`Scene` 只是局内地点、时间或事件。
- `Release` 制品不可修改；下架只修改可见性元数据。
- `Playthrough` 永久固定 `release_id`，新版本默认新开一局。
- 玩家数据以 `user_id` 与 `playthrough_id` 归属；应用查询和 PostgreSQL RLS 双重约束。生产策略对租户表启用 `FORCE ROW LEVEL SECURITY`，并沿 World、角色、事件、记忆、回合、叙事与存档的完整关联图验证所属 Playthrough。

## 请求级运行时

旧的全局内容包/Orchestrator 单例不参与 v1 请求。

```text
request
  → owner-checked Playthrough
  → Release artifact + checksum（不回读当前磁盘内容源）
  → ReleaseContentCache（仅缓存不可变 ContentPack）
  → request-scoped provider / LLMClient / Orchestrator
  → RedisLockBackend(playthrough world) 或本地锁
  → canonical transaction
  → UsageLedger
```

这样用户密钥、LLM 调用记录、token 预算和错误不会跨用户或跨请求泄漏。

## 回合流水线

```text
玩家文本
  → IntentParser（LLM 或确定性 fallback）
  → RuleEngine.validate
  → ActionResolver + GameRNG
  → NPC / Simulation / Director proposals
  → ProposalValidator
  → 声明式 Content Pack rules
  → ConsistencyGuard
  → canonical state + EventLog + recovery capsule 原子提交
  → Memory projection
  → NarrativeRenderer（只描述已提交事实）
  → SSE narrative/state/done
```

关键不变量：

1. LLM 没有数据库写句柄。
2. AI proposal 未经验证不能成为 `StateChange`。
3. 叙事失败不能重做 canonical action。
4. NPC context 只包含其知识与可感知事件。
5. 同一世界的行动通过锁串行；数据库事务和幂等 Turn 行仍是最终正确性来源。

## Content Pack v2

Pydantic 契约位于 `engine/contentpack/schema_v2.py`，编译器位于 `compiler.py`。

发布编译执行：schema、稳定 key、重复 key、引擎 API 与版本范围、交叉引用、地点可达性、资源范围、表达式/效果白名单、素材完整性校验和确定性作者玩法测试。规范 JSON 以 SHA-256 标识；校验和是内容身份和缓存键，不是所有权标识，因此不同创作者可各自发布相同制品。

`author_tests` 与作品一起版本化。每条测试在隔离的 `MemoryUnitOfWork` 中建立固定种子 Playthrough，可预置玩家、关系、知识、任务和剧情线，并通过真实 Orchestrator 执行有限行动。断言只能读取白名单 canonical state，不包含生成正文或调试上下文；整套测试最多执行 80 个行动。CLI、创作台校验与 Release API 共享同一个 runner，公开发布必须至少声明一条测试。

作者规则由 `DeclarativeRule` 表示：

- 条件：无 I/O 的受限 AST；
- 效果：玩家通用数据、资源、关系、背包、任务、线程和地点标记的白名单操作；
- 限制：递归深度、操作步数、参数数量、可写字段和关系变化钳制；
- 禁止：`eval`、脚本、文件、网络、数据库和反射路径。

官方受信任作品仍可由管理员安装版本化 Python Rule Plugin；网页上传永远不可用。插件源码树哈希会编译进 Release，运行时只有系统所有者且本地源码哈希仍匹配时才会加载；普通 Release 完全从不可变制品还原。

## 基础设施

- PostgreSQL：生产事实源、RLS、自动备份与 PITR。
- Redis：跨进程世界锁、限流、Release/任务状态。
- S3 兼容存储：清洗后的不可变素材；读取同时校验所有者或公开 Release 引用。
- Worker：Redis 任务入口和过期预览清理；邮件、缩略图、编译与导出任务仍按路线图逐项迁入。
- SMTP/Mailpit：验证、重置与本地邮件捕获。
- Next.js：独立部署，`/api` 与 `/media` 反向代理到 FastAPI。

SQLite 只用于测试和本地轻量开发，由仓储和 API 所有权条件模拟租户隔离。

## 产品反馈与回顾

- 玩家回顾由玩家已见叙事、当前场景、公开任务与剧情提示确定性生成，不调用 LLM，也不读取秘密事实。
- 产品分析默认关闭；开启后只接受服务器定义的事件名和属性白名单，不保存玩家输入、生成正文、邮箱、密钥或 IP。
- 撤回同意会立即删除该用户的事件；幂等回合使用 `turn_id` 去重。管理端只读取聚合漏斗，不返回身份或逐条事件。
- 公共目录、玩家 Playthrough 生命周期、canonical gameplay/SSE、创作者图片管线与审核/举报分属独立模块；拆分只改变应用内部边界，不改变 `/api/v1` URL。

## 兼容层

`/api/game/*` 仅在 `DEBUG_MODE=true` 时注册，用于迁移测试。生产和 Next.js 只使用 `/api/v1`。旧 `apps/web` 已删除，避免维护两份玩家契约。
