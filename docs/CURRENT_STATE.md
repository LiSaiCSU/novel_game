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
- PostgreSQL、Redis、MinIO、Mailpit、ClamAV、worker 的本地 Compose 编排；`novegame.online` 的生产 Compose、Caddy 自动 HTTPS、迁移前备份、镜像回滚与首位管理员授权；Python/TypeScript CI 依赖审计。
- 三种编译器验证的创作模板、可安装的 `narrative` CLI、机器可读 Schema、创作者声明式玩法测试和独立创作指南；测试可预置关系/知识/任务/线程，执行真实回合并断言 canonical state，失败会阻断 Release。
- 玩家重返游戏回顾；默认关闭的产品分析、白名单事件、幂等去重、撤回即时删除、个人导出和仅聚合的管理员漏斗。
- 公共目录、玩家私有 Playthrough 生命周期、canonical gameplay/SSE、创作素材和审核/举报路由已拆分为独立模块，保持原 `/api/v1` 契约不变。

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
