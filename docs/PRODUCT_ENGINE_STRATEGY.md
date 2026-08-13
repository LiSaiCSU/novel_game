# 产品、LLM 与创作平台策略

## 1. 调研结论

2026-08-13 的调研同时检查了近 30 天公开讨论、AI 原生游戏研究和成熟叙事工具。原始检索记录保存在 `docs/research/`。

结论不是“让模型说得更多”，而是让开放语义产生稳定、可理解、可追溯的游戏后果：

1. 生成内容本身不是游戏循环。AI 原生玩法仍需要明确目标、规则、状态、反馈、节奏和玩家能动性。参考 [AI Native Games: A Survey and Roadmap](https://arxiv.org/abs/2607.00527)。
2. 完全开放输入会提高自主感，也会提高表达负担和响应不确定性。一项 N=130 的随机实验没有观察到总体游戏体验显著提升，且可用性与信任下降。参考 [The Double-Edged Sword of Open-Ended Interaction](https://arxiv.org/abs/2604.10107)。
3. 创作者需要“快速写—立即验证—立即试玩—定位错误”的短反馈环，而不是只能面对全局巨型节点图。Yarn Spinner 的局部图、变量查看和编辑器内试玩提供了可参考的工作流：[预览](https://docs.yarnspinner.dev/2.3/getting-started/editing-with-vs-code/previewing-your-dialogue)、[编辑与分组](https://docs.yarnspinner.dev/2.4/getting-started/editing-with-vs-code/writing-yarn-in-vs-code)。

因此，本产品采用以下设计：

- 玩家端是“自由输入 + 情境建议”的双轨交互，选择建议不是限制，而是降低空白输入框负担。
- 每次行动必须产生阶段反馈，最终叙事只描述已经提交的 canonical state。
- 目标、时间、人物、资源、任务和关系始终可见；章节和存档刷新后可恢复。
- LLM 负责理解、角色决策和表达，不能直接改数据库，也不能覆盖规则结果。
- 创作台默认结构化编辑；JSON/YAML 是高级模式和交换格式，不是唯一入口。

## 2. 玩家留存循环

```text
看到当前目标/关系/线索
        ↓
选择建议或自由行动
        ↓
即时阶段反馈（理解 → 裁决 → 世界推进 → 叙事）
        ↓
可见后果（状态、关系、任务、时间、章节）
        ↓
新的问题、承诺或选择点
```

产品指标应按下列顺序验证：

| 层级 | 指标 | 目的 |
|---|---|---|
| 可用性 | 首次行动完成率、首次响应时间、失败重试率 | 玩家是否能开始 |
| 理解 | 建议选择率、自由输入率、澄清率、撤回率 | 输入负担是否合理 |
| 可信度 | 重复/矛盾举报、降级率、存档恢复成功率 | 世界是否可靠 |
| 参与 | 每局回合数、D1/D7 回访、章节完成率 | 是否形成持续循环 |
| 内容 | 各 Scenario 完成率、结局分布、拒绝路线正确率 | 作品是否真正可玩 |
| 成本 | 每回合 token、每完成章节成本、超时率 | 玩法能否持续运营 |

首版不以无限聊天时长作为成功指标。长但没有状态变化的对话属于产品失败。

## 3. LLM 管理策略

一次请求创建一个 `ReleaseRuntime`，只共享不可变内容缓存和锁适配器，不共享 `LLMClient`、调用记录或用户密钥。

```text
Playthrough.release_id
        ↓
Release checksum → immutable ContentPack cache
        ↓
选择平台额度或本局 BYOK
        ↓
BudgetedProvider（单回合预留上限）
        ↓
Intent / NPC / Director / Narrative / Memory
        ↓
UsageLedger（用户、Playthrough、模型、tokens、结果）
```

规则：

- 平台额度按日/月计算，管理员可以为用户设置月额度；额度耗尽在调用前拒绝。
- BYOK 密钥使用部署主密钥加密，响应只返回末四位提示，不进入日志。
- 每个 Playthrough 固定选择 `platform` 或某个 BYOK provider，避免运行中隐式切换模型。
- 单回合预算按“输入估算 + 最大输出”预留并跨该回合所有调用累计。
- 供应商失败可降级为确定性解析/模板叙事，但 canonical action 只结算一次。
- SSE 使用 `open/progress/narrative/state/done` 契约和心跳；断流不重做已经提交的行动。

## 4. 引擎边界

`engine/` 是纯领域层，不能 import FastAPI、SQLAlchemy、Redis 或对象存储 SDK。基础设施适配器位于 `apps/` 与 `database/`。

Content Pack v2 包含：

- manifest：版本、引擎兼容、语言、分级、标签、主题、素材、入口和玩家字段；
- world/scenario：世界规则和可开始入口；
- locations/organizations/characters/relationships/facts；
- items/abilities/resources/progressions/properties；
- quests/plot_threads/event_templates/calendar/narrative/vocabulary；
- 声明式规则：受限表达式 AST + 白名单 canonical effects。

网页内容不能安装 Python 插件。声明式规则限制深度、操作步数、参数数量、可写命名空间和可写字段；其效果在 action 裁决之后、ConsistencyGuard 之前加入同一个 `ChangeSet`。

## 5. 创作台工作流

```text
向导或导入
  → 结构化编辑（世界/地点/人物/秘密/线程/规则/素材）
  → 900ms 自动保存 + revision 乐观并发 + 撤销/重做
  → 实时诊断（key、引用、可达性、规则、素材、引擎兼容）
  → 隔离预览 Playthrough
  → 只读草稿分享
  → 不可变 Release
  → 审核 / 公开 / 下架
```

导入支持 UTF-8 JSON/YAML/ZIP。ZIP 拒绝路径穿越、符号链接、加密条目、过高压缩比、过多文件和超量展开。图片经解码验证、尺寸限制、重新编码和元数据清除后存入本地或 S3 兼容对象存储；未发布素材仅所有者可读取。

## 6. 下一轮产品验证

工程正确性不等于“完美游戏”。公开测试前仍需真实用户验证：

1. 5–8 名目标玩家完成校园作品前 60 分钟，记录首次行动、理解偏差和无聊点。
2. 3–5 名没有接触过仓库的创作者，从空白项目完成一个 10 分钟可玩场景。
3. 对自由输入、建议按钮数量、章节长度和阶段反馈做可逆实验。
4. 对校园作品四条关系线、拒绝恋爱、友情和独立结局执行人工长局测试。
5. 上线前完成真实 PostgreSQL RLS、Redis、S3、SMTP、备份恢复和供应商故障演练。
