# 玩家吸引力、LLM 叙事与创作工具基线（2026-08-13）

这份基线用于约束产品和架构决策。它区分“有证据支持的设计原则”“从原则推导出的工程决策”和“仍需真实用户实验的假设”，避免把模型能力或个人偏好误当成玩家需求。

## 1. 怎样更吸引玩家

### 一手证据

- Self-Determination Theory 的 PENS 研究把持续游戏动机与自主、胜任和联结需要联系起来。易掌握的控制、清晰一致的反馈、目标/策略选择和社会互动会增强这些体验：[PENS 概览与原始研究索引](https://selfdeterminationtheory.org/player-experience-of-needs-satisfaction-pens/)。
- 开放输入并不自动提高游戏体验。它同时增加表达负担、不确定反馈和信任风险。因此“自由输入 + 情境建议”比只有空白输入框更适合作为默认交互；这仍需在本产品玩家中做 A/B 验证。
- Steamworks 把展示、点击和阅读按独立登录用户统计，并允许按曝光位置分析事件效果。这说明内容更新和运营活动必须有可归因的曝光→点击→游玩链路，而不能只看总访问量：[活动可见性统计](https://partner.steamgames.com/doc/marketing/event_tools/stats?l=english)。Steam 也明确说明愿望单、商店访问和转化在其推荐系统中的作用并不等同，不能把单一指标当作增长真相：[Steam 可见性说明](https://partner.steamgames.com/doc/marketing/visibility?language=english)。

### 对本产品的要求

1. 每个可操作页面都同时显示“当前目标、可用行动、行动后果和下一问题”。
2. 首次游戏在 60 秒内完成角色创建，在 3 分钟内产生第一次可见状态变化。
3. 自由输入旁提供 3–5 个来自 canonical state 的情境建议；建议必须说明可能目的，不剧透结果。
4. 人物关系不只显示好感，而要显示信任、尊重、熟悉和边界，以及变化所对应的 canonical event。
5. 回流页面提供“上次发生了什么、哪些承诺未完成、现在最值得做什么”，而不是把玩家扔回空白输入框。
6. 运营指标依次验证：曝光→详情→开局→首次行动→第三回合→章节完成→D1/D7；成本和错误率必须与同一漏斗关联。

## 2. LLM 应当怎样进入游戏

### 一手证据

- Generative Agents 的实验架构把观察记录、动态检索、反思和计划分开，消融实验表明这些部分都会影响行为可信度：[Generative Agents 论文](https://arxiv.org/abs/2304.03442)。这支持“记忆、人物计划与即时台词分层”，不支持让一个超长提示词包办全部世界模拟。
- OpenAI API 的严格结构化输出使用 JSON Schema 约束模型结果；官方兼容性说明同时建议固定模型版本并为应用建立 eval：[结构化输出 API](https://platform.openai.com/docs/api-reference/chat/delete?lang=node.js%EF%BC%89)、[兼容性建议](https://platform.openai.com/docs/api-reference/backward-compatibility?lang=ruby)、[Evals API](https://platform.openai.com/docs/api-reference/evals/deleteRun?lang=python)。其他供应商也应通过相同的内部结构化协议接入，而不是把供应商响应直接传给引擎。

### 对本产品的要求

```text
玩家文本
  → Intent 模型：只返回受类型约束的行动提案
  → 确定性规则/状态机：裁决并提交 canonical event
  → NPC 模型：基于知识边界提出意图，不直接写状态
  → Director：只从允许的事件模板提出节奏建议
  → Narrative：只叙述已经提交的结果
  → Memory：从 canonical event 投影可检索记忆和阶段反思
```

- 任一模型失败都不能造成重复结算；幂等键和世界锁位于模型外部。
- 每种角色独立固定 prompt version、model version、JSON Schema、预算、超时和降级策略。
- Release 固定规则与叙事配置；平台可以升级模型，但升级前必须跑同一组离线回放/eval，并保留回滚目标。
- 评测分三层：结构正确率、世界一致性/知识隔离、文风与玩家偏好。只用“模型觉得好不好”不能替代确定性断言和人工盲测。
- 记忆分为事件事实、人物主观记忆和低频反思；检索必须同时考虑相关度、重要性、时间与可见性。

## 3. 引擎应当怎样架构

稳定边界为：

```text
Content SDK / Studio
        ↓  ContentPackageV2 + Author Tests
Compiler → immutable Release artifact
        ↓
Application service（账号、权限、Playthrough、额度、幂等）
        ↓
Pure engine（状态、规则、时钟、知识、关系、任务、结局）
        ↕ typed proposal ports
LLM adapters / repositories / queue / object storage
```

- `engine/` 不依赖 FastAPI、SQLAlchemy、Redis 或供应商 SDK。
- API 路由只负责 HTTP 契约、鉴权和事务边界；用例应进入 application service，避免 1000 行路由文件继续膨胀。
- Content Pack 不使用题材字段。旧的 realm/spiritual 字段只能存在于 v1 兼容适配器，不能继续出现在新作者契约和 UI。
- Release artifact 是唯一运行时内容源，开发目录不能改变已开始的 Playthrough。
- 读模型与写模型分开：游戏行动是串行写路径；状态、历史、目录和分析使用可缓存读模型。

## 4. 开发者中心和 SDK

### 成熟工具的共同模式

- Yarn Spinner 允许从任意节点开始预览、切换逐行/整段显示并实时查看变量，作者在游戏本体未完成时也能测试内容：[Yarn Spinner 预览](https://docs.yarnspinner.dev/2.3/getting-started/editing-with-vs-code/previewing-your-dialogue)。
- Ren'Py 把 lint、交互控制台、跳转到源码、热重载和样式检查作为开发模式的一部分，并强调 lint 不能替代试玩：[Ren'Py 开发工具](https://www.renpy.org/doc/html/developer_tools.html)。
- ink 的运行时边界很小：继续内容、呈现选择、选择分支、保存/加载 JSON、观察变量；官方建议用组合封装运行时而不是继承内部对象：[ink 运行时](https://github.com/inkle/ink/blob/master/Documentation/RunningYourInk.md)。

### 本产品工作流

1. `narrative init` 从经过编译器验证的题材骨架开始。
2. 编辑器和 CLI 使用同一个 Pydantic JSON Schema 与模板注册表。
3. `narrative validate` 检查 schema、引用、图可达性、表达式、素材和引擎范围。
4. `narrative test` 不调用 LLM，先证明包可以建立确定性 Playthrough。
5. 创作台支持从任意 Scenario/地点/剧情节拍预览、修改测试变量和查看知识边界。
6. 作者测试以输入状态、行动、预期 canonical effects/可见知识/可达结局为断言，发布时必须通过。
7. `narrative compile` 生成带校验和的制品，CI 与服务端发布使用同一编译器。

## 5. 当前代码审计结论

已经满足：Content Pack v2、不可变 Release、确定性规则边界、知识/记忆、固定版本 Playthrough、结构化 LLM provider、额度、SSE、创作台、审核和租户隔离。

仍需持续处理的主要缺口：

| 优先级 | 缺口 | 当前证据 | 目标证据 |
|---|---|---|---|
| P0 | 没有完整产品漏斗与留存分析 | 只有 HTTP/LLM 运维指标 | 经过同意的事件模型、漏斗/分群、作者聚合分析与数据导出/删除 |
| P0 | 没有作者声明的可重复玩法测试 | 编译器只检查静态图 | Release 发布门禁执行作者测试，覆盖行动、知识、关系、拒绝与结局 |
| P0 | 创作者入口只有前端硬编码空白模板 | 新建页内嵌一个巨大对象 | API、CLI、UI 共用经过 CI 编译的模板注册表 |
| P1 | 回流体验缺少摘要和承诺 | 游戏页主要显示当前状态和历史 | 确定性会话摘要、未完成承诺、下一行动建议 |
| P1 | 路由与编辑器文件过大 | `catalog.py`、`creator.py`、创作页均为热点 | application services、分区 router 和编辑器组件边界 |
| P1 | V2 内容实体仍大量是无类型字典 | schema 只强类型化少数实体 | 分批升级地点、人物、事实、任务、线程及迁移器 |
| P2 | 外部开发集成不足 | 没有稳定 CLI/SDK 版本策略 | CLI、Schema、模板、示例、变更日志和兼容矩阵 |

本轮首先交付统一模板注册表和 `narrative` CLI；后续按表中顺序继续，不把“测试全绿”误判为产品已经完美。
