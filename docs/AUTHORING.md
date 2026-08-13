# Content Pack v2 创作指南

创作者可以使用网页创作台，也可以把作品作为普通 YAML/JSON 项目放进 Git。两种入口使用同一套 Pydantic Schema、模板注册表和发布编译器，所以本地通过的作品不会在网页端换一套规则。

## 从模板开始

安装开发依赖后，命令行会提供 `narrative`：

```powershell
narrative templates
narrative init .\my-story --template relationship_drama --title "未寄出的夏信" --slug summer-letters
narrative validate .\my-story
narrative test .\my-story
narrative compile .\my-story
```

- `blank`：最小世界，适合从结构开始。
- `relationship_drama`：带人物、关系、任务和剧情线程的关系叙事模板。
- `mystery`：带事实、知识边界、线索任务和悬疑线程的模板。

`init` 会生成 `content-pack.yaml` 与对应的 `content-pack.schema.json`。命令不会覆盖非空目录。`validate` 检查 Schema、悬空引用、地点可达性、规则类型和引擎版本；`test` 会用固定种子执行内容包声明的玩法测试；`compile` 只有在编译和玩法测试都通过后，才生成带 SHA-256 校验和的规范 Release 制品。

## 把作品承诺写成玩法测试

`author_tests` 与 `manifest`、`content` 同级。每条测试运行在独立的内存 Playthrough 中，不调用外部模型。可以预置玩家属性、关系、知识、任务与剧情线，执行真实玩家行动，再断言公开的 canonical state：

```yaml
author_tests:
  - key: secret_stays_hidden
    name: 玩家开场不知道账目秘密
    scenario: main_story
    assertions:
      - {path: player.location, op: eq, expected: international_dorm}
      - {path: knowledge.player.fact_missing_funds, op: eq, expected: UNKNOWN}
      - {path: knowledge.ren.fact_missing_funds, op: eq, expected: KNOWN}
  - key: consent_unlocks_romance
    name: 明确同意和关系条件共同解锁恋爱结局
    player:
      properties:
        romance_consent: {haruto: accepted}
    fixtures:
      relationships:
        haruto: {affection: 40, trust: 45, respect: 35, familiarity: 45, boundaries: 50}
      quests: {quest_final_performance: completed}
    assertions:
      - {path: endings.romance_haruto.available, op: eq, expected: true}
```

支持 `eq`、`ne`、`gt`、`gte`、`lt`、`lte`、`contains`、`not_contains`、`exists` 和 `not_exists`。可断言根路径为 `world`、`player`、`characters`、`relationships`、`knowledge`、`quests`、`plot_threads`、`endings`、`events` 和 `last_turn`。编译器会提前拒绝测试里的悬空人物、事实、任务、剧情线和结局引用；单套测试最多执行 80 个行动。

CI 或公开发布门禁应使用 `narrative test .\my-story --require-declared`。没有声明测试时，普通 `test` 仍会执行内置开场冒烟测试，但不能公开发布。

## 推荐工作流

1. 用模板建立第一条可玩的最短路径，只保留一个入口 Scenario。
2. 每增加地点、人物、任务或规则，立即运行 `narrative validate`。
3. 每完成一条关键路径就补一条 `author_tests`，提交代码前运行 `narrative test --require-declared`，并把 `release.compiled.json` 当作构建产物而非手写源文件。
4. 在创作台导入 YAML/JSON，检查地点图、知识矩阵、关系边界、版本差异和预览试玩。
5. 发布后创建新版本继续编辑；既有 Release 和玩家存档不会被原地修改。

## 引擎边界

- 世界状态只由 canonical event 与受校验 effect 改变；叙事文本不是事实源。
- 普通作品只能使用声明式条件、公式、触发器和效果，不能使用 `eval`、Python、文件、网络或数据库访问。
- 人物的题材数据放在 `attributes`、`resources`、`progressions` 与 `properties`；引擎不会识别“灵力”“学业”等题材词汇。
- 秘密必须声明知识持有者。玩家 API、回顾卡和导出只返回玩家已经可见的信息。
- 浪漫关系需要作品定义的明确同意；拒绝后规则和模型都不能继续强制推进。

机器可读契约还可以从创作 API 的 `GET /api/v1/creator/content-pack-schema` 获取。模板列表由 `GET /api/v1/creator/templates` 返回。
