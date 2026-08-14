# AI Narrative World Engine / 叙事游戏创作平台

这是一个面向玩家与创作者的多用户叙事游戏引擎。现有《七日血契》已迁移为官方 Content Pack v2；《春日坂未完通信》用于验证校园女性向题材、关系边界和非战斗进度系统。玩家端与创作台使用 Next.js，API 与引擎运行时使用 FastAPI。

当前核心能力包括：

- Project → 不可变 Release → 玩家 Playthrough 的完整版本链路；旧存档固定使用创建时的 Release。
- 邮箱账号、会话、CSRF、角色权限、项目/存档/素材所有权以及 PostgreSQL RLS。
- JSON/YAML/安全 ZIP 内容导入、结构化编辑、自动保存、撤销/重做、诊断、预览、发布和只读分享。
- 类型化声明式规则 AST；网页作者不能上传或执行 Python。官方受信任插件仍只由部署管理员安装，并由 Release 内的源码树哈希约束。
- 平台 LLM 与 BYOK、加密密钥、回合/日/月额度、使用台账、流式叙事和无模型确定性降级。
- 管理员 TOTP 二次认证、异常登录审计、异步个人数据导出/注销，以及审核、举报、申诉和紧急下架。
- 本地或 S3 兼容对象存储、Redis 锁/限流/任务队列、ClamAV、缩略图、邮件、指标、追踪和错误聚合接口。
- 编译器验证的创作模板、贯穿 CLI/创作台/发布门禁的确定性玩法测试与 `narrative` CLI；玩家重返游戏回顾，以及默认关闭、可撤回并即时清除的最小化产品分析。

产品方向、用户研究和关键指标见 [产品与引擎策略](docs/PRODUCT_ENGINE_STRATEGY.md)，系统边界见 [架构](docs/ARCHITECTURE.md)，平台接口与生产检查表见 [平台 v2](docs/platform-v2.md)。

## 快速开始

后端在 conda 环境 `game` 中开发和验证：

```powershell
conda activate game
python -m pip install -e ".[dev,postgres,redis,llm,object-store]"
Copy-Item .env.example .env
python -m alembic upgrade head
python -m uvicorn apps.api.main:app --reload
```

启动 Next.js：

```powershell
Set-Location apps/web-next
npm ci
npm run dev
```

访问 `http://localhost:3000`。FastAPI 默认监听 `http://127.0.0.1:8000`；应用启动时会校验并安装官方不可变 Release。默认 `LLM_PROVIDER=null`，没有模型密钥也能运行完整的确定性游戏链路。

需要 PostgreSQL、Redis、MinIO 与邮件捕获器时可使用：

```powershell
docker compose up --build
```

Compose 中的密码只用于本地开发。生产密钥必须由密钥管理服务注入，不能提交到仓库或放进生产 `.env`。

## LLM 接入

平台模型可通过统一配置接入 OpenAI 兼容端点：

```dotenv
LLM_PROVIDER=compatible
LLM_API_KEY=replace-me
LLM_BASE_URL=https://example.com/v1
LLM_MODEL=your-model
```

玩家也可以在设置页保存自己的 provider、model 与密钥。密钥使用主密钥加密，只能测试、轮换和删除，API 不回显明文。平台模型的不同角色可通过 `INTENT_MODEL`、`NPC_MODEL`、`DIRECTOR_MODEL`、`NARRATIVE_MODEL` 等配置单独覆盖；BYOK 的全部文本角色固定使用玩家选择的 model。

LLM 只负责自然语言理解、NPC 提案、导演建议与叙事表达。世界状态、时钟、资源、关系、任务和事实均由确定性引擎校验并提交，模型不能直接写数据库。

真实模型质量不由离线测试冒充。付费、显式确认的整局评估使用：

```bash
python -m evaluation.live_llm --allow-paid-calls --turns 12 --resume-after 6
```

命令逐回合原子写入 `data/evaluations/`，记录延迟、调用、token、成本、canonical 变化和完整转录；默认每回合 180 秒硬超时。自动检查只作烟雾报警，报告在人工评审前保持 `awaiting_human_review`。首次真实基线及失败项见 [docs/LIVE_LLM_BASELINE.md](docs/LIVE_LLM_BASELINE.md)。

`LLM_PRICE_TABLE` 的 `input_per_million` / `output_per_million` 使用“每百万 token 对应的计费货币微单位”（1 元 = 1,000,000 微单位）。价格是部署配置，不应在模型未知或供应商更新后沿用猜测值。

## 内容与版本模型

- `Project`：创作者持续编辑的作品。
- `World`：世界观、地点、日历、组织和基础规则。
- `Scenario`：主角创建字段、初始状态和剧情入口。
- `Release`：经过编译并带 SHA-256 校验和的不可变制品。
- `Playthrough`：一名玩家基于一个固定 Release 创建的一局游戏。
- `Scene`：局内的具体地点、时间或事件场景。

Content Pack v2 由 Pydantic 生成 JSON Schema，支持 JSON/YAML 导入导出。发布编译会检查引用、入口可达性、地点图、公式/条件 AST、写字段白名单、素材、引擎版本和 Python 插件禁用策略，并在隔离内存 Playthrough 中执行作品声明的玩法测试。

本地创作可以直接使用与创作台相同的模板和编译器：

```powershell
narrative templates
narrative init .\my-story --template mystery --title "雾中来信" --slug letters-in-fog
narrative validate .\my-story
narrative test .\my-story --require-declared
narrative compile .\my-story
```

完整流程见 [Content Pack v2 创作指南](docs/AUTHORING.md)。

## 目录

```text
apps/
  api/             FastAPI v1 API、认证、创作、目录、游戏与媒体
  author_cli.py    Content Pack 模板、校验、玩法测试与编译命令
  web-next/        Next.js 玩家端、创作台与分享页
  worker/          Redis 后台任务：邮件、编译/审核、缩略图、导出、注销与过期清理
engine/            不依赖 FastAPI/SQLAlchemy 的领域引擎
  contentpack/     v2 schema、编译器、声明式规则和运行时转换
  orchestrator/    回合调度、校验、提交和流式叙事
  llm/             provider、路由、预算和结构化输出
database/          SQLAlchemy 模型、仓储、RLS 与 Alembic 迁移
content/
  cultivation_v1/ 《七日血契》官方作品
  campus_romance_v1/ 《春日坂未完通信》官方作品
tests/             unit、integration 与确定性的 LLM 边界契约测试
docs/              架构、策略、决策和部署文档
```

## 验证

```powershell
conda activate game
python -m ruff check .
python -m mypy engine database apps scripts
python -m pytest -q
python scripts/load_smoke.py --playthroughs 50 --action-check

Set-Location apps/web-next
npm run lint
npm run build
```

CI 还会执行迁移、前端依赖审计与 Content Pack 编译。最新实测状态记录在 [CURRENT_STATE](docs/CURRENT_STATE.md)。

## 安全与上线边界

- SQLite 仅用于测试和轻量本地开发；生产使用 PostgreSQL，并同时验证应用层所有权和 RLS。
- 私密内容与草稿素材返回 `private, no-store`；只有获批公开 Release 引用的素材才允许公共缓存。
- 上传会限制类型、尺寸、文件数、压缩比和展开体积，拒绝路径穿越、符号链接、加密条目和 YAML alias，并重新编码图片以清除元数据。
- `ADULT_CATALOG_ENABLED=false` 为默认值。18+ 开关不是发布露骨内容的许可，启用前仍需年龄保障、地区政策与正式法律审查。
- “代码完整”不等于“产品完美”。真实留存、模型文风、成本阈值、内容审核运转和备份恢复必须在封闭测试与生产演练中验收。

## 主要文档

- [产品与引擎策略](docs/PRODUCT_ENGINE_STRATEGY.md)
- [系统架构](docs/ARCHITECTURE.md)
- [Content Pack v2 创作指南](docs/AUTHORING.md)
- [平台 v2 与接口](docs/platform-v2.md)
- [路线图](docs/ROADMAP.md)
- [工程决策](docs/DECISIONS.md)
- [当前状态](docs/CURRENT_STATE.md)
