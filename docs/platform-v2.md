# 多用户叙事游戏平台 v2

本版本把原来的单作品应用拆成四层：Content Pack v2 是作者契约，Release 是带 SHA-256 校验和的不可变制品，Playthrough 固定引用一个 Release，运行时按校验和缓存依赖。`cultivation_v1` 与 `campus_romance_v1` 都作为官方项目安装；旧接口暂时保留，Next.js 仅使用 `/api/v1`。

## 核心边界

- `Project` 是可编辑作品，`ProjectRevision` 通过递增 revision 实现乐观并发，冲突响应同时返回服务器版本。
- `World` 描述内容世界，`Scenario` 是入口，`Scene` 只表示游戏中的地点、时刻或事件。
- `ContentRelease` 发布后不再修改制品；撤回只改变目录可见性。旧 Playthrough 始终锁定原 `release_id`，运行时不会回读当前磁盘内容源。
- 所有玩家数据同时以应用层所有权条件和 PostgreSQL RLS 限制。事务通过 `app.current_user_id` 设置租户上下文；生产策略对租户表启用 `FORCE ROW LEVEL SECURITY` 并覆盖完整 Playthrough 数据图，SQLite 仓储执行相同 owner 条件。
- 作者规则只能使用 `engine/contentpack/declarative.py` 的受限 AST。网页内容不能安装 Python 插件。

## 本地启动

```powershell
docker compose up --build
```

服务地址：玩家/创作端 `http://localhost:3000`，API/OpenAPI `http://localhost:8000/docs`，Mailpit `http://localhost:8025`，MinIO 控制台 `http://localhost:9001`。Compose 中的口令仅供本机；生产必须由密钥管理服务注入 `AUTH_PEPPER`、`CREDENTIAL_ENCRYPTION_KEY`、数据库和对象存储凭据。

不使用容器时：

```powershell
python -m alembic upgrade head
python -m uvicorn apps.api.main:app --reload
cd apps/web-next
npm install
npm run dev
```

## API 范围

- `/api/v1/auth/*`：注册、验证、登录、退出、重置密码、设备会话撤销和管理员 TOTP/恢复码二次认证。
- `/api/v1/catalog/*`：公开目录筛选/排序、详情、未列出邀请和举报。
- `/api/v1/playthroughs/*`：创建、列表、状态、普通行动及 SSE 行动。
- `/api/v1/creator/*`：项目、revision、JSON Schema、校验、素材、导出、Release、审核、举报处置、申诉和审计日志。
- `/api/v1/settings/*`：BYOK 密钥写入/测试/轮换/删除、异步个人数据导出和延迟注销。
- `/api/v1/admin/*`：用户/角色/额度管理、使用概况和审计记录；要求管理员二次认证。

错误统一使用 `application/problem+json`；修改请求需要双提交 CSRF。未列出 Release 的分享令牌只在创建时返回一次，数据库只保存 HMAC。BYOK 密钥只返回末四位提示，密文使用部署主密钥加密。

## 内容包与校园作品

Pydantic 模型位于 `engine/contentpack/schema_v2.py`，编译器位于 `engine/contentpack/compiler.py`。校园官方包《春日坂未完通信》位于 `content/campus_romance_v1`，包含 14 个地点、12 个 NPC、6 条剧情线程、24 个节拍、12 个任务和 9 个结局，不加载 Python 规则插件。

## 生产检查表

1. 使用 PostgreSQL，运行 Alembic 并以非超级用户连接，以确保 RLS 不被绕过。
2. 配置 TLS、Secure Cookie、精确 CORS、Redis、S3 兼容对象存储、SMTP 与上传病毒扫描器。
3. 在网关和 Redis 层配置分布式限流；进程内限流只用于轻量开发。
4. 启用结构化日志、指标、追踪、错误聚合、慢查询与 LLM 成本告警。
5. 配置 PostgreSQL PITR、对象版本控制和恢复演练。18+ 目录保持关闭，直至法律、年龄保障和运营审核完成。

## 验证

```powershell
python -m ruff check .
python -m mypy engine database apps scripts
python -m pytest -q
python scripts/load_smoke.py --playthroughs 50 --action-check
cd apps/web-next
npm run lint
npm run build
```
