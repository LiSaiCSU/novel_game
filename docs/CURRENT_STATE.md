# 当前工程状态

更新时间：2026-08-14

## 已实现

- FastAPI + Next.js/TypeScript 的玩家端、创作台和公开目录。
- Content Pack v2、不可变 Release、固定版本 Playthrough，以及《七日血契》v1→v2 兼容转换。
- 《春日坂未完通信》官方校园女性向包：14 个地点、12 个重要 NPC、6 条剧情线程、24 个节拍、12 个任务、9 个可判定结局、关系同意与拒绝语义；全程使用声明式规则。
- 当前公开官方 Release：《七日血契》`2.3.0`、《春日坂未完通信》`1.5.0`。数据库保留旧的 `2.1.0`/`2.2.0` 与 `1.2.0`/`1.3.0`/`1.4.0` 不可变制品并标记下架，因此当前为 2 个项目、7 个 Release、2 个可新建版本；重复初始化不会增加记录。
- 邮箱注册登录、验证/重置令牌、服务器会话、CSRF、设备会话撤销、角色权限、管理员 TOTP/恢复码二次认证、异常登录审计和接口限流。
- 共享 PostgreSQL 租户模型、应用层所有权检查，以及覆盖项目、版本、素材和完整 Playthrough 数据图的强制 PostgreSQL RLS；SQLite 保留同等仓储检查供测试。
- 平台 LLM/BYOK、加密密钥、额度预算、使用台账、无模型 fallback 和 SSE 回合恢复。
- 项目自动保存、乐观 revision、双方内容保留、撤销/重做、地点图、知识矩阵、结局编辑、字段级差异、预览、诊断、导入导出、素材与发布流程。
- 未列出作品的一次性邀请链接、公开目录筛选/排序，以及封面、头像、背景图的清洗、病毒扫描、缩略图和对象存储。
- 异步个人数据导出和延迟注销；导出明确排除凭据密文、令牌哈希、内部 trace、秘密状态和完整存档载荷。
- Redis 任务队列/死信、邮件、审核扫描、过期预览和导出清理、结构化日志、指标、traceparent、慢查询、Sentry 接口和 LLM 成本告警。
- PostgreSQL、Redis、MinIO、Mailpit、ClamAV、worker 的本地 Compose 编排；`novelgame.online` 的生产 Compose、Caddy/宿主机 Nginx 自动 HTTPS、迁移前备份、镜像回滚与首位管理员授权；Python/TypeScript CI 依赖审计。
- 三种编译器验证的创作模板、可安装的 `narrative` CLI、机器可读 Schema、创作者声明式玩法测试和独立创作指南；测试可预置关系/知识/任务/线程，执行真实回合并断言 canonical state，失败会阻断 Release。
- 玩家重返游戏回顾；默认关闭的产品分析、白名单事件、幂等去重、撤回即时删除、个人导出和仅聚合的管理员漏斗。
- 公共目录、玩家私有 Playthrough 生命周期、canonical gameplay/SSE、创作素材和审核/举报路由已拆分为独立模块，保持原 `/api/v1` 契约不变。

## 本轮实测修复（真实模型试玩）

这一轮的问题全部来自用真实 OpenAI 兼容模型逐回合试玩，而不是读代码：确定性测试
永远走不到这些分支，所以 716 项测试全绿的同时，实际游戏体验是坏的。

按影响排序：

- **每回合推理预算从不重置**。`BudgetedProvider` 用真实用量替换预留额度，计数器
  只增不减，所以它是"整个进程的累计用量"而不是"一回合的上限"。累计超过上限之后
  每次调用都被拒绝——而章节是一回合里最后写的，于是玩家真正会读的那段正文被静默
  降级成一行模板，此后每回合都是。另外 `llm_turn_token_limit` 的代码默认值
  (20000) 比一个健康回合的实际开销还小，而 `.env.example` 写的是 120000。
- **记忆投影引用了不存在的提示词文件**。`prompts/memory_v1.md` 的 `role` 是
  `memory_extractor`，抽取器按 role 找文件，于是 `PromptRenderError` 被抛到
  `_ensure_memory_projection` 之外，把一个**已经提交**的回合永久打成失败。平时看不
  见，是因为普通玩法根本没有事件跨得过记忆阈值。
- **PlotSteward 的 `generate_structured` 参数顺序写反**，抛出未被捕获的
  `ValidationError`；任何 CUSTOM 行动或每 8 回合的例行复查都会让整个回合 500。
- **"去找某人说话"退化成一次单纯的走路**：目标和台词在改写成 MOVE 时被丢掉，
  对话没有发生、关系没有变化、事件没有落库，而叙述者照样把这段对话写了出来。
- **纯查询被当成剧情来写**：`QUERY_STATUS` / `QUERY_INVENTORY` 在章节渲染器里没有
  短路，模型会为一次"看看背包"凭空编出一整场戏。
- **世界管家会覆盖玩家点名的目的地**：认出人物时顺带写入对方所在地，于是
  "去演武场找林清雪"把人送去了后山。
- **开局没有任何建议行动**：序章的 beat 被存了下来，但 `/history`、`/recap` 和创建
  接口都只从"上一回合"取，新开的一局没有上一回合。
- **长期记忆在正常游戏里从不产生**：所有日常事件的重要度都在 `min_importance`
  之下，和主要人物的第一次谈话只有 0.10。
- **存档不含压力时钟**：读档把世界退回去，界面上的倒计时却停在读档前的格数。
- **《七日血契》没有定义任何结局**，默认作品无法通关。

其余修复见 diff：叙事截断会切断引号、beat 块丢失标记时的回退、自动推进步数与
schema 上限不一致、张力被走路推高、关系变化标错人名、每回合虚报境界变化、
管理员 inspect 接口读不存在的字段、SSE 泄漏内部异常文本等。

### 本轮验证

- Python：`730 passed, 2 skipped`（含 14 项新增回归测试）
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 153 source files`（修复前有 4 项既有错误）
- Next.js：28 项 Vitest、ESLint、生产构建通过
- 真实模型连打 10 回合：无一回合降级，章节长度 819–1316 字，`继续` 一次推进 6 步，
  关系、事件、时钟、张力均按预期变化

官方 Release 版本随内容改动上调：`cultivation_v1 2.8.0`、`campus_romance_v1 1.9.0`、
`tomb_lantern_v1 1.4.0`、`fog_harbor_v1 1.4.0`、`spirit_pact_v1 1.4.0`。

## 最近验证基线

本轮最终实测结果：

- Python：`643 passed in 76.73s`，其中 2 项使用真实 PostgreSQL 17 验证 RLS 与单查询快照
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 145 source files`
- Next.js：9 项 Vitest、Prettier、ESLint 通过，Next.js 16.3.0 生产构建通过
- 迁移：空 SQLite、开发 SQLite 与空 PostgreSQL 17 均位于 Alembic `e91c37a2b604 (head)`
- 烟测：独立 FastAPI 进程的 `/api/health` 为 `ok`，数据库 `/api/ready` 为 `ready`，Content Pack v2 JSON Schema 可读取
- 回合起始状态从同一 AsyncSession 的 10 次串行读取改为单条 `UNION ALL` 快照；SQLite 与真实 PostgreSQL/RLS 连接均断言只执行 1 条 SQL。
- PostgreSQL RLS：应用角色为 `NOSUPERUSER NOBYPASSRLS`；跨用户列举、直接对象读取、更新和伪造所有权插入均已在数据库层拒绝。迁移 owner 与 API/Worker 运行角色已分离。
- 本机 SQLite 验收：普通状态读取 p95 `12.2ms`；50 个 Playthrough 同时读取全部成功（p95 `637.3ms`）；同一 Playthrough 的两次并发行动均成功并经过串行锁。生产规格 PostgreSQL/Redis 压测仍未完成。
- Compose：Docker Desktop、PostgreSQL 17 容器、迁移、官方 Release 初始化与 RLS 测试实际运行通过；开发和生产 Compose 均通过 `docker compose config --quiet`。生产镜像构建、Caddy 校验，以及独立 PostgreSQL/Redis/MinIO、全量 Alembic 迁移和 API readiness 冒烟测试已通过；ClamAV、真实 SMTP/Sentry 与公网 HTTPS 仍待目标 Ubuntu 实机验收。
- 真实 LLM：12 回合首次整局完成但人工评审失败；修复调用追踪和玩家代理权后，单回合从 7 次调用/61.3 秒/约 2.3 万 token 降至 2 次调用/17.9 秒/8172 token/估算 0.032664 元。模型仍会违背精确事实，已加入声明式叙事不变量和失败降级，尚未达到发布门槛。
- Python wheel 构建通过，并确认包含创作模板、Content Pack 编译器、提示词资源与 `narrative` 控制台入口。

复现命令：

```powershell
C:\ProgramData\miniconda3\envs\game\python.exe -m ruff check .
C:\ProgramData\miniconda3\envs\game\python.exe -m mypy engine database apps scripts
C:\ProgramData\miniconda3\envs\game\python.exe -m pytest -q
C:\ProgramData\miniconda3\envs\game\python.exe scripts/load_smoke.py --playthroughs 50 --action-check
Set-Location apps/web-next
npm run lint
npm run build
```

Alembic 已在空 SQLite、重建后的开发库和真实 PostgreSQL 17 上升级到当前 head。迁移前备份为 `data/game.pre-engine-refactor.20260813-025150.db`，SHA-256 为 `4AEA79A6B89469BE376BFE3134526EFD35E6D4F1A4F8354F8923906506615DED`，文件属性为只读。重建库中没有迁移旧匿名 Playthrough；系统账号持有两个官方项目及其七个不可变 Release，当前版本为 `2.3.0` 与 `1.5.0`。

## 尚需外部环境验收

- PostgreSQL RLS 隔离已经实测；PITR 与备份恢复演练仍未执行。
- PostgreSQL 容器已实测；Redis/S3/邮件/ClamAV/KMS/Sentry 仍需在目标环境做集成、故障和权限演练。
- 已完成一次真实模型整局和多次单回合诊断，但质量评审失败；仍需在叙事不变量保护下重新做 12 回合与多模型 A/B。
- 用邀请用户验证首日完成率、章节继续率、7 日回访、拒绝恋爱体验和创作者首次发布耗时。
- 上线公共 UGC 前落实人工审核、举报、申诉、证据留存和地区法律审查。

这些是“完美产品”不能由单元测试代替的上线门槛；详细顺序见 [ROADMAP](ROADMAP.md)。
