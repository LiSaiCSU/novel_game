# AI Narrative World Engine / 修仙开放世界 RPG

## Master Engineering Prompt

你现在是本项目的 **首席架构师、游戏系统设计师、AI Agent 工程师、后端工程师、前端工程师和测试工程师**。

你的任务不是制作一个简单的“LLM 小说续写 Demo”，而是设计并实现一个真正可长期运行的：

# AI 原生开放世界文字 RPG 引擎

第一款内容包采用：

**修仙 / 玄幻开放世界**

未来底层引擎应能够扩展至：

* 武侠
* 西幻
* 末日
* 科幻
* 悬疑
* 宫斗
* 历史
* 都市
* 其他文字 RPG

---

# 0. 最重要的产品理念

整个系统必须遵循：

> 世界先存在，剧情是玩家与世界交互之后产生的结果。

不要把产品实现成：

```text
玩家输入
↓
LLM继续写小说
↓
玩家输入
↓
LLM继续写小说
```

这是错误架构。

正确架构是：

```text
玩家行为
↓
理解玩家意图
↓
读取真实世界状态
↓
检查世界规则
↓
执行行为
↓
NPC做出合理决策
↓
世界状态发生改变
↓
剧情导演判断是否发生事件
↓
记录因果和记忆
↓
最后由叙事模型把已经发生的事情写成小说
```

核心原则：

> Code determines what CAN happen.
>
> Database determines what IS true.
>
> AI determines intent, reasoning, behavior and expression.

换句话说：

**程序负责规则。**

**数据库负责事实。**

**AI负责理解、决策和文学表达。**

任何可能导致世界观崩坏、数值作弊、人物复活、境界失控、NPC上帝视角的问题，都不能让LLM拥有最终决定权。

---

# 1. 项目目标

实现一个可运行的 Web MVP。

玩家可以：

1. 创建角色；
2. 进入修仙世界；
3. 看到当前地点、人物、时间和自身状态；
4. 阅读小说形式的剧情；
5. 使用自然语言输入任何合理行为；
6. 与NPC进行完全自由的自然语言交流；
7. 探索地点；
8. 修炼；
9. 学习功法；
10. 使用物品；
11. 与NPC建立关系；
12. 接受任务；
13. 战斗；
14. 影响宗门和世界；
15. 让过去发生的事情持续影响未来；
16. 即使离开某个地方，该地区仍然能够发生变化。

最终目标不是制作“互动小说”。

目标是：

> 构建一个通过自然语言操作的开放世界 RPG。

---

# 2. V1范围

不要第一版就构建无限世界。

先实现一个纵向完整的小型世界。

## V1世界规模

建立一个示例世界：

```text
青云界
│
├── 青云宗
│
├── 青云城
│
├── 黑风山
│
├── 落霞谷
│
├── 赤霞秘境
│
└── 周边村镇
```

主要势力：

```text
青云宗
血魔宗
大周皇朝
散修联盟
```

重要NPC：

约20～30人。

普通背景NPC：

可以通过模板生成。

境界暂时实现：

```text
凡人
炼气
筑基
金丹
```

必须保证架构以后可以继续增加：

```text
元婴
化神
炼虚
合体
大乘
渡劫
仙人
...
```

---

# 3. 推荐技术栈

除非现有项目已经有明确技术栈，否则使用：

## Backend

Python 3.12+

FastAPI

Pydantic v2

SQLAlchemy 2.x

Alembic

PostgreSQL

pgvector

Redis

pytest

asyncio

## Frontend

Next.js

TypeScript

React

Tailwind CSS

可以使用合适的现代UI组件库，但保持界面简洁。

## AI

必须设计统一 LLM Provider abstraction。

禁止业务代码与某一家模型厂商强绑定。

设计：

```text
LLMProvider
├── AnthropicProvider
├── OpenAIProvider
└── CompatibleProvider
```

提供：

```python
generate_text()
generate_structured()
stream_text()
```

模型名称、API地址、API Key全部通过：

```text
.env
```

配置。

禁止硬编码API Key。

---

# 4. 推荐工程目录

建立类似：

```text
ai_narrative_world/
│
├── apps/
│   ├── api/
│   └── web/
│
├── engine/
│   │
│   ├── orchestrator/
│   │
│   ├── actions/
│   │
│   ├── rules/
│   │
│   ├── world/
│   │
│   ├── characters/
│   │
│   ├── relationships/
│   │
│   ├── knowledge/
│   │
│   ├── memory/
│   │
│   ├── simulation/
│   │
│   ├── events/
│   │
│   ├── director/
│   │
│   ├── narrative/
│   │
│   ├── context/
│   │
│   └── llm/
│
├── content/
│   └── cultivation_v1/
│
├── prompts/
│
├── database/
│
├── tests/
│
├── scripts/
│
└── docs/
```

可以根据工程实际情况调整，但必须保持模块职责清晰。

---

# 5. 核心架构

实现：

```text
                  PLAYER
                    │
                    ▼
             Game Orchestrator
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
 Intent Parser   Context      World State
        │        Builder          │
        └───────────┼─────────────┘
                    ▼
              Rule Engine
                    │
                    ▼
             Action Resolver
                    │
             实际行动结果
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    NPC Agents   Simulator    Director
        │           │           │
        └───────────┼───────────┘
                    ▼
             Event Validation
                    │
                    ▼
              State Commit
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
    Event Log                 Memory
        │                       │
        └───────────┬───────────┘
                    ▼
             Narrative Renderer
                    │
                    ▼
                  PLAYER
```

---

# 6. Game Orchestrator

Game Orchestrator 是整个回合的程序调度中心。

它本身不写剧情。

必须负责：

* 玩家输入处理
* Context组装
* AI调用顺序
* Rule Engine调用
* Action执行
* NPC响应
* Director调用
* 世界状态事务提交
* Event Log
* Memory
* Narrative生成
* 错误处理
* 重试
* Token预算
* 日志

标准回合：

```text
PlayerInput
↓
IntentParser
↓
Action
↓
RuleValidation
↓
ActionResolver
↓
NPCDecision
↓
WorldSimulation
↓
Director
↓
EventValidation
↓
StateTransaction
↓
EventLog
↓
MemoryExtraction
↓
NarrativeRenderer
↓
PlayerResponse
```

不是每一个回合都必须调用所有AI。

Orchestrator应根据需要决定。

例如：

```text
查看背包
```

直接数据库查询。

不调用LLM。

---

# 7. Action Protocol

所有玩家自然语言必须首先变成结构化 Action。

例如玩家：

```text
“我假装喝醉，过去和药铺老板喝酒，顺便套他的话，
问问昨天有没有人买噬魂草。”
```

Intent AI输出：

```json
{
  "action_type": "conversation",
  "actor_id": "player",
  "target_id": "npc_shopkeeper_001",
  "method": "indirect_questioning",
  "style": "pretend_drunk",
  "goal": {
    "type": "obtain_information",
    "topic": "soul_devouring_grass_purchase"
  },
  "secondary_actions": [
    {
      "type": "drink"
    }
  ]
}
```

Action是游戏世界唯一认可的玩家行为接口。

设计统一Action schema。

至少考虑：

```text
MOVE
TALK
ASK
OBSERVE
FOLLOW
HIDE
SEARCH
ATTACK
DEFEND
USE_ITEM
GIVE_ITEM
STEAL
BUY
SELL
CULTIVATE
BREAKTHROUGH
USE_SKILL
PICKUP
DROP
REST
WAIT
ACCEPT_QUEST
REJECT_QUEST
CUSTOM
```

允许扩展。

---

# 8. Rule Engine

Rule Engine尽可能使用确定性程序。

不要用LLM决定基础游戏规则。

至少建立：

```text
MovementRules
CultivationRules
CombatRules
SkillRules
InventoryRules
EconomyRules
InteractionRules
DetectionRules
LocationRules
TimeRules
FactionRules
```

接口形式类似：

```python
validate_action(...)
resolve_action(...)
calculate_probability(...)
calculate_cost(...)
calculate_damage(...)
calculate_detection(...)
calculate_breakthrough(...)
```

Rule Engine输出结构化结果。

例如：

```json
{
  "allowed": false,
  "reason_code": "REALM_TOO_LOW",
  "reason": "御剑飞行至少需要筑基境"
}
```

LLM不能覆盖这个结果。

---

# 9. 随机系统

游戏需要概率，但必须可调试和可复现。

实现统一：

```text
GameRNG
```

支持：

```text
world_seed
session_seed
event_seed
```

重要随机事件记录随机种子和计算过程。

不要直接在不同模块里随意调用 random。

未来应该能够回放一次事件。

---

# 10. World State

World State是游戏客观现实。

至少包括：

```text
World
Location
Faction
Character
Relationship
Knowledge
Memory
Item
Inventory
Skill
Quest
Event
StoryArc
PlotThread
WorldClock
```

---

# 11. 数据库设计

使用规范化结构，必要字段可以JSONB扩展。

建立至少以下实体。

## worlds

```text
id
name
description
current_time
calendar_config
world_seed
content_pack
rule_version
created_at
updated_at
```

## locations

```text
id
world_id
parent_id
name
location_type
description
coordinates
danger_level
faction_id
metadata
```

支持层级：

```text
大陆
→ 地区
→ 城市
→ 宗门
→ 建筑
→ 房间
```

---

# 12. Character

玩家和NPC共享基础 Character 模型。

```text
characters

id
world_id
name
character_type
age
gender
location_id
faction_id

realm
realm_stage
cultivation_progress

health
max_health

spiritual_power
max_spiritual_power

strength
agility
perception
intelligence
willpower
charisma

personality
values
background

long_term_goal
short_term_goal

current_emotion

alive
created_at
updated_at
```

Character不得只有一段自然语言Profile。

重要属性必须结构化。

---

# 13. NPC Personality

人格建议采用：

```json
{
  "traits": {
    "cautious": 0.8,
    "proud": 0.7,
    "compassionate": 0.4,
    "ambitious": 0.6
  },

  "values": [
    "loyalty",
    "personal_strength",
    "family"
  ],

  "taboos": [
    "betrayal"
  ],

  "speech_style": "冷静克制",

  "risk_tolerance": 0.35
}
```

固定人格变化必须非常缓慢。

情绪则可以快速变化。

不要把：

```text
personality
```

和：

```text
emotion
```

混为一谈。

---

# 14. Relationship System

人物关系禁止只使用：

```text
好感度
```

至少实现：

```text
affection
trust
respect
fear
hatred
suspicion
dependency
familiarity
```

例如：

```json
{
  "character_a": "lin_qingxue",
  "character_b": "player",

  "affection": 47,
  "trust": 31,
  "respect": 52,
  "fear": 4,
  "hatred": 0,
  "suspicion": 21,
  "dependency": 8,
  "familiarity": 53
}
```

关系变化应该：

* 有原因
* 有幅度限制
* 有日志
* 与事件对应

禁止一次普通对话：

```text
trust +50
```

---

# 15. Knowledge System

这是核心模块。

必须严格区分：

# Truth

世界客观事实。

和：

# Belief

人物相信什么。

例如：

```text
FACT_001

“大长老是血魔宗卧底”

truth = TRUE
```

玩家可能：

```text
UNKNOWN
```

林清雪：

```text
SUSPECTED
confidence = 0.35
```

魔宗宗主：

```text
KNOWN
confidence = 1.0
```

实现：

```text
facts
character_knowledge
```

character_knowledge至少包含：

```text
character_id
fact_id
knowledge_state
confidence
source
learned_at
```

状态考虑：

```text
UNKNOWN
HEARD
SUSPECTED
BELIEVED
KNOWN
DISBELIEVED
```

## 强制安全边界

NPC Agent调用时：

Context Builder只能提供：

> NPC实际知道、相信、怀疑的信息。

绝对不能把整个数据库真相塞给NPC。

这是防止：

**NPC上帝视角**

的核心机制。

---

# 16. Memory System

实现至少四层记忆。

## Working Memory

当前场景最近几轮。

## Episodic Memory

人物亲身经历过的重要事件。

## Relationship Memory

与某人物相关的重要经历。

## Semantic Memory

人物总结出来的长期认识。

例如：

```text
玩家曾在黑风谷冒险救下林清雪。
```

保存：

```json
{
  "owner_character_id": "lin_qingxue",

  "memory_type": "episodic",

  "summary": "玩家在黑风谷遭遇妖兽时放弃逃生机会救下了我。",

  "importance": 0.93,

  "emotional_valence": 0.82,

  "related_characters": [
    "player"
  ],

  "related_event_id": "event_1829",

  "created_at_world_time": "..."
}
```

使用 pgvector 保存 embedding。

长期检索依据：

```text
semantic similarity
+
importance
+
recency
+
relationship relevance
+
current context relevance
```

不要单纯向量Top-K。

---

# 17. Event Log

必须实现 Append-only Event Log。

所有改变世界的重要事情都产生 Event。

例如：

```json
{
  "event_type": "BREAKTHROUGH",

  "actor": "player",

  "before": {
    "realm": "炼气后期"
  },

  "after": {
    "realm": "筑基初期"
  },

  "causes": [
    "闭关14日",
    "使用筑基丹"
  ],

  "world_time": "...",

  "rng_seed": "...",

  "importance": 0.88
}
```

不要只保存最终状态。

必须能够回答：

> 为什么世界变成现在这样？

未来用于：

* Debug
* 回档
* 人物记忆
* 世界历史
* 因果追踪
* 剧情总结
* 年鉴
* 数据分析

---

# 18. State Mutation原则

AI禁止直接修改数据库。

AI只能提出：

```text
proposal
```

程序负责：

```text
validate
↓
resolve
↓
commit
```

例如NPC AI返回：

```json
{
  "action": "attack",
  "target": "player"
}
```

程序必须验证：

* NPC是否活着；
* NPC是否在现场；
* 是否拥有攻击能力；
* 是否存在规则限制；
* 行动是否物理可行。

之后才执行。

---

# 19. NPC Agent

NPC Agent是人物决策系统。

不是聊天机器人。

输入：

```text
Identity
Personality
Values
Goals
CurrentEmotion
CurrentSituation
Relationships
KnownFacts
RelevantMemories
AvailableActions
RecentEvents
```

输出：

```json
{
  "reasoning_summary": "...",

  "decision": {
    "action_type": "...",
    "target": "...",
    "parameters": {}
  },

  "speech_intent": "...",

  "emotion_update": {},

  "relationship_change_proposal": {},

  "goal_update_proposal": null
}
```

真正State Update仍由程序验证。

---

# 20. NPC Decision Prompt

建立：

```text
prompts/npc_decision.md
```

核心内容：

```text
You are an NPC decision engine.

You are NOT a novelist.

Determine the most plausible action for this character based only on:

- identity
- personality
- values
- goals
- current emotions
- relationships
- memories
- information actually known by this character
- current physical situation
- risks and rewards

Never use information unavailable to the character.

Never change established world facts.

Never force a character to help the player merely because the player is the protagonist.

Never break personality merely to advance the story.

Characters may refuse, lie, misunderstand, hesitate, manipulate, flee, cooperate, remain silent, or change their mind when sufficiently justified.

Prefer behavioral continuity.

Large personality or relationship changes require major causes.

Return strictly structured output.
```

进一步根据Pydantic schema生成JSON约束。

---

# 21. Intent Parser AI

建立：

```text
prompts/player_intent.md
```

职责只有：

> 将自然语言转成Action。

禁止：

* 决定成功失败
* 修改世界
* 编剧情
* 决定NPC反应

输出严格结构化JSON。

必须正确处理：

```text
复合行为
模糊行为
欺骗
套话
隐瞒
观察
试探
条件行为
```

例如：

```text
“如果守卫转头，我就从窗户翻进去。”
```

应支持condition。

---

# 22. AI Director

Director是长期剧情控制器。

但它不是世界管理员。

它不能修改世界真相。

它主要解决：

> 在当前世界已经存在的因果关系中，哪些值得现在发展成故事？

维护：

```text
NarrativeTension
OpenPlotThreads
CharacterArcs
WorldConflicts
PlayerGoals
Foreshadowing
RecentEventTypes
NarrativePacing
```

---

# 23. Plot Thread

建立剧情线程：

```text
plot_threads
```

例如：

```json
{
  "name": "血魔宗渗透青云宗",

  "status": "active",

  "importance": 0.82,

  "stage": 2,

  "participants": [
    "great_elder",
    "lin_qingxue"
  ],

  "unresolved_questions": [
    "谁是内奸？"
  ],

  "foreshadowing": [
    "灵药失窃",
    "大长老深夜离宗"
  ]
}
```

Director优先发展已有线程。

不要不断随机创造新剧情。

---

# 24. Director Prompt

建立：

```text
prompts/director.md
```

原则：

```text
You are the director of a long-running interactive RPG.

You do NOT write prose.

You do NOT change established facts.

You do NOT control characters against their motivations.

Your job is to evaluate whether existing world conflicts,
character goals, unresolved consequences, promises,
secrets and plot threads should naturally develop now.

Prefer consequences of previous events over random new events.

Prefer existing characters over introducing new characters.

Prefer unresolved threads over creating new threads.

Avoid constant escalation.

Allow quiet periods.

Allow failure.

Allow the player to miss opportunities.

The world does not exist solely for the player.

Major events require sufficient causes.

Do not generate coincidence merely for excitement.

When no event is needed, return NO_EVENT.
```

输出类似：

```json
{
  "decision": "TRIGGER_EVENT",

  "source_plot_thread": "thread_091",

  "event_type": "NPC_RETURN",

  "participants": [
    "lin_qingxue"
  ],

  "proposal": "林清雪重伤返回青云宗",

  "causal_basis": [
    "三日前进入黑风谷",
    "正在调查魔修踪迹"
  ],

  "narrative_purpose": [
    "推进魔宗调查线",
    "回应失踪伏笔"
  ],

  "urgency": "medium"
}
```

程序必须再次验证。

---

# 25. Narrative Tension

维护0～100的剧情张力。

不要让剧情永远处于高潮。

大致：

```text
0-20
平静 / 日常 / 成长

20-40
轻微矛盾

40-60
压力增加

60-80
重大冲突

80-100
高潮
```

Director需要考虑近期张力曲线。

理想剧情类似波浪：

```text
低
↗
中
↗
高
↘
低
↗
中
↗
高潮
↘
恢复
```

禁止：

```text
高潮
高潮
高潮
高潮
高潮
```

---

# 26. Narrative Renderer

Narrative AI是最后执行的模型。

非常重要：

> Narrative Renderer描述已经确定发生的事情。

它不能决定发生什么。

输入：

```text
CurrentScene
RecentNarrative
PlayerAction
ResolvedActionResult
NPCDecisions
ConfirmedWorldEvents
CharacterSpeechIntent
RelevantVisibleInformation
NarrativeStyle
```

---

# 27. Narrative Prompt

建立：

```text
prompts/narrative.md
```

核心：

```text
You are the narrative renderer of a cultivation fantasy RPG.

All important events, actions and outcomes have already been determined by upstream systems.

Your task is to express those facts as immersive Chinese fantasy fiction.

You MAY control:

- prose
- atmosphere
- sensory description
- pacing
- body language
- exact wording of dialogue
- minor non-consequential details

You MUST NOT:

- change success or failure
- create important items
- create major characters
- kill characters unless specified
- revive characters
- change realm or stats
- move characters to impossible locations
- change relationships
- invent important world facts
- reveal secrets unknown to the viewpoint character
- grant rewards
- trigger breakthroughs
- alter NPC decisions

Preserve character speech style and personality.

Prefer concise but vivid writing.

Avoid generic AI fantasy clichés.

Do not repeatedly use exaggerated expressions.

Do not constantly praise the player.

The world should feel indifferent to the existence of the protagonist.
```

---

# 28. Memory Extractor

建立：

```text
prompts/memory_extractor.md
```

判断事件是否值得长期记忆。

保存：

```text
promise
betrayal
rescue
insult
conflict
gift
romantic_event
shared_danger
major_conversation
secret_disclosure
trauma
victory
failure
```

普通寒暄不要进入长期记忆。

输出：

```json
{
  "should_store": true,

  "importance": 0.87,

  "memory_type": "promise",

  "summary": "...",

  "characters": [],

  "facts_learned": [],

  "relationship_implications": {}
}
```

---

# 29. Context Builder

Context Builder必须独立实现。

不要：

```text
SELECT entire_database
→ prompt
```

针对不同Agent构造不同Context。

## NPC Context

```text
Identity
Personality
Goals
Emotion
CurrentScene
KnownFacts only
Relationships
RelevantMemories Top-K
RecentEvents
```

## Narrative Context

```text
Scene
VisibleCharacters
PlayerAction
ResolvedResults
NPCDecisions
RecentNarrative
VisibleFacts
```

## Director Context

```text
WorldSummary
PlayerProgress
MajorNPCSummary
PlotThreads
RecentMajorEvents
NarrativeTension
OutstandingConsequences
```

## Memory Context

```text
ResolvedEvent
Participants
DialogueMeaning
ExistingSimilarMemories
```

实现Token预算。

---

# 30. NPC知识隔离测试

必须写自动化测试验证：

NPC A知道：

```text
SECRET_X
```

NPC B不知道。

当构造NPC B Context时：

```text
SECRET_X
```

绝对不能出现。

把这个测试视为核心测试。

---

# 31. World Simulation

世界不能只有玩家附近才存在。

但是禁止所有NPC每分钟调用LLM。

采用LOD模拟。

## LOD 0：Active Scene

玩家当前场景。

完整模拟：

```text
NPC Agent
完整行为
完整互动
```

## LOD 1：Nearby

附近区域。

使用：

```text
规则
计划
简化决策
```

## LOD 2：Regional

其他城市/宗门。

模拟：

```text
资源
势力变化
任务结果
人口
贸易
冲突
```

## LOD 3：Global

只模拟：

```text
战争
宗门覆灭
秘境
灾害
皇权变化
大型事件
```

只有重要事件才升级精度。

---

# 32. NPC Schedule

普通NPC应具有基础日程：

```text
sleep
work
eat
cultivate
social
patrol
travel
```

不要让所有NPC永远站在原地等待玩家。

重要NPC增加：

```text
goal-based planning
```

---

# 33. World Clock

实现独立世界时间。

任何动作消耗时间。

例如：

```text
普通对话：5～20分钟
城市移动：10～60分钟
跨区域移动：小时～天
修炼：小时～月
闭关：天～年
```

不要强制真实时间。

游戏世界时间根据行为推进。

---

# 34. Cultivation System

V1实现完整但简单的修炼循环。

人物拥有：

```text
realm
stage
cultivation_xp
cultivation_speed
spiritual_root
technique
bottleneck
mental_state
injuries
```

突破必须经过规则。

例如：

```text
BaseChance
+
TechniqueBonus
+
PillBonus
+
FoundationQuality
+
MentalState
-
InjuryPenalty
```

最终结果由程序计算。

Narrative AI只能描述。

---

# 35. Skills

技能结构：

```text
id
name
category
required_realm
spiritual_cost
cooldown
power
mastery
effects
```

禁止AI凭空创造玩家拥有的技能。

---

# 36. Items

物品结构：

```text
id
name
type
rarity
description
effects
value
stackable
metadata
```

Inventory必须数据库化。

LLM无权直接添加物品。

---

# 37. Combat

第一版无需复杂到MMORPG程度。

但必须系统化。

至少考虑：

```text
realm
stats
skills
equipment
health
spiritual_power
status_effect
environment
strategy
rng
```

AI可以做：

> 战术决策。

程序做：

> 数值裁决。

---

# 38. Social Actions

玩家可以：

```text
persuade
deceive
intimidate
flirt
negotiate
bribe
ask
threaten
comfort
promise
```

结果不要简单依赖Charisma。

考虑：

```text
relationship
personality
known facts
risk
request size
interests
player reputation
context
```

---

# 39. Faction System

宗门不是文本描述。

建立：

```text
resources
members
territory
military_power
reputation
leadership
alliances
enemies
goals
internal_conflicts
```

NPC属于Faction。

玩家行为可以改变Faction关系。

---

# 40. Reputation

玩家至少拥有：

```text
global_reputation
faction_reputation
regional_reputation
```

不同人知道玩家声望的程度不同。

不能玩家刚做一件秘密事情：

> 全世界立刻知道。

信息传播也应该遵循世界逻辑。

---

# 41. Quest System

Quest可以来自：

```text
人工预设
世界事件
NPC目标
Director
```

任务不要完全写死。

采用：

```text
goal
constraints
participants
rewards
failure_conditions
expiration
world_consequences
```

例如：

```text
护送灵药
```

玩家拒绝：

任务仍可能发生。

NPC可能找别人。

结果可能失败。

世界继续。

---

# 42. 玩家不是世界中心

这是核心体验原则。

如果玩家错过：

```text
宗门大比
```

比赛照常进行。

其他NPC获得冠军。

如果玩家没有去救某个人：

NPC可能：

```text
死亡
受伤
自己逃生
被其他人救
```

根据世界规则决定。

不要等待玩家。

---

# 43. Character Death

角色死亡必须永久影响世界。

```text
alive = false
```

普通情况下禁止复活。

其：

```text
职位
关系
任务
资产
仇恨
秘密
```

都应产生后续影响。

---

# 44. 世界因果

重要事件建立：

```text
cause_event_ids
```

例如：

```text
玩家杀死韩青
↓
韩青死亡
↓
韩家调查
↓
韩墨产生仇恨
↓
韩墨拜入宗门
↓
十二年后寻找玩家复仇
```

不要要求LLM记住全部链条。

数据库保存。

---

# 45. Narrative History

保存：

```text
raw transcript
structured events
scene summary
chapter summary
long-term history
```

不要每次把完整小说历史塞给模型。

---

# 46. Prompt版本管理

所有Prompt保存文件。

例如：

```text
prompts/
    player_intent_v1.md
    npc_decision_v1.md
    director_v1.md
    narrative_v1.md
    memory_v1.md
```

记录：

```text
prompt_version
model
temperature
token_usage
latency
```

方便A/B测试。

---

# 47. Structured Output

除Narrative之外，AI调用尽量使用严格JSON Schema。

使用Pydantic验证。

如果失败：

```text
parse
↓
repair/retry
↓
fallback
```

禁止未经验证的模型输出进入世界数据库。

---

# 48. AI调用成本

实现 Model Router。

不同任务使用不同模型等级。

例如：

```text
Intent
→ fast / cheap model

Memory Extraction
→ fast / cheap model

普通NPC
→ medium model

关键NPC
→ strong model

Director
→ strong model

Narrative
→ medium/strong model
```

具体模型不得写死。

通过配置：

```text
INTENT_MODEL=
NPC_MODEL=
DIRECTOR_MODEL=
NARRATIVE_MODEL=
MEMORY_MODEL=
```

---

# 49. Streaming

Narrative可以流式输出。

但是：

> 必须先完成世界状态裁决和事务提交，再开始Narrative Streaming。

不能边写小说边决定世界结果。

---

# 50. API设计

至少提供：

```text
POST /worlds
GET  /worlds/{id}

POST /characters
GET  /characters/{id}

POST /game/start

POST /game/{session_id}/action

GET /game/{session_id}/state

GET /game/{session_id}/history

GET /characters/{id}/relationships

GET /characters/{id}/memories

GET /player/inventory
```

action接口返回：

```json
{
  "narrative": "...",
  "state_changes": {},
  "visible_updates": {},
  "choices": []
}
```

choices可选。

玩家永远允许自由输入。

---

# 51. 前端

V1不要做复杂3D。

目标是高质量小说游戏UI。

建议：

```text
┌─────────────┬────────────────────────┬─────────────┐
│             │                        │             │
│ 角色信息     │      小说剧情区          │ 当前场景     │
│             │                        │             │
│ 境界         │                        │ NPC         │
│ HP           │                        │ 地点        │
│ 灵力         │                        │ 时间        │
│ 状态         │                        │            │
│             │                        │            │
├─────────────┴────────────────────────┴─────────────┤
│                                                  │
│         [玩家输入任何行动................]          │
│                                                  │
├──────────────────────────────────────────────────┤
│ 可选快捷行为                                      │
└──────────────────────────────────────────────────┘
```

支持：

* 流式文本
* Markdown
* 人物头像占位
* 地点
* 时间
* 境界
* 状态
* 背包
* 人物关系
* 任务
* 历史记录
* Debug模式

---

# 52. Debug UI

开发版本一定增加：

```text
Debug Panel
```

可以查看：

```text
Intent解析结果
Rule结果
RNG
Action结果
NPC Decision
Director Decision
Memory写入
Context
Token Usage
State Changes
Event Log
```

这是开发AI游戏最重要的工具之一。

---

# 53. Admin / World Inspector

最好建立简单后台：

```text
World Inspector
```

查看：

```text
人物
人物位置
人物关系
人物知识
人物记忆
Faction
Plot Threads
Events
World Time
```

不要等出Bug之后只能查SQL。

---

# 54. 第一个示例剧情

不要设计固定线性主线。

设计“初始冲突”。

例如：

玩家是一名刚进入：

```text
青云宗外门
```

的普通炼气修士。

世界存在：

```text
青云宗与血魔宗关系持续恶化。

青云宗近期频繁出现灵药失窃。

大长老真实身份存在秘密。

林清雪正在暗中调查。

黑风山出现异常魔气。

数月后赤霞秘境即将开启。
```

这些构成：

```text
World Seeds
```

而不是固定：

```text
第一章
第二章
第三章
```

玩家可以：

```text
加入调查
完全不调查
离开宗门
修炼
赚钱
追求某NPC
加入其他宗门
成为散修
甚至与青云宗敌对
```

世界必须继续运行。

---

# 55. Seed NPC

至少设计5个高度完整的重要NPC。

例如：

```text
林清雪
青云宗年轻天才

陆玄
青云宗宗主

韩墨
外门弟子

大长老
隐藏秘密

赵无极
竞争型天才
```

每个人必须有：

```text
background
personality
values
goals
secret
knowledge
relationships
schedule
speech_style
resources
capabilities
```

他们不能只是剧情工具。

---

# 56. AI味控制

Narrative必须避免：

```text
“嘴角勾起一抹弧度”
“眼中闪过一丝异色”
“心中暗道”
“恐怖如斯”
```

等固定模板被高频重复。

建立：

```text
NarrativeStyleConfig
```

并记录近期表达，降低重复。

优先：

* 具体行为
* 环境
* 动作
* 有信息量的对话

减少无意义修辞。

---

# 57. 游戏状态与小说状态分离

永远区分：

```text
Canonical State
```

和：

```text
Narrative Representation
```

小说出现的一切关键事实必须来自Canonical State。

Narrative只是View。

---

# 58. 数据事务

一个玩家行动必须尽量形成一个原子事务。

例如：

```text
Action
NPC Responses
Event
StateChanges
EventLog
```

失败则：

```text
rollback
```

防止模型或网络异常造成世界半更新。

---

# 59. 并发

设计时考虑：

未来同一个World可能出现：

```text
多个AI任务
```

避免重复执行事件。

使用：

```text
transaction
locking
idempotency key
```

关键世界事件必须幂等。

---

# 60. Observability

记录：

```text
request_id
session_id
world_id
turn_id

LLM model
prompt_version
latency
token usage
structured result
validation result
state mutation
errors
```

不要把调试完全建立在print上。

---

# 61. Testing

必须写测试。

至少覆盖：

## Rule Tests

```text
炼气修士不能使用筑基技能
死亡NPC不能行动
没有物品不能使用物品
不在同地点不能近战
```

## Knowledge Tests

```text
NPC不能获得未知道秘密
```

## Memory Tests

```text
普通寒暄不会变重要记忆
重大救命事件应该进入长期记忆
```

## Relationship Tests

```text
普通对话不会导致巨大关系变化
```

## Event Tests

```text
死人不能参与新事件
```

## Context Tests

```text
秘密不会泄露给未知NPC
```

## Orchestrator Tests

完整模拟一个玩家回合。

---

# 62. AI Evaluation

增加：

```text
tests/evals/
```

至少建立场景：

### Eval 1

玩家炼气期：

```text
“我一掌拍死元婴老祖。”
```

正确：

系统拒绝/行动失败。

### Eval 2

玩家：

```text
“林清雪，你其实知道大长老是魔宗卧底对吧？”
```

但她不知道。

正确：

她不应该突然承认事实。

### Eval 3

玩家第一次见NPC：

```text
“把你的毕生积蓄送给我。”
```

正确：

NPC拒绝。

### Eval 4

玩家救NPC一命。

未来检索应该能够回忆。

### Eval 5

NPC已经死亡。

Director不能让其正常回归。

---

# 63. Consistency Guard

实现程序级Consistency Checker。

在状态提交前验证至少：

```text
alive consistency
location consistency
inventory consistency
realm consistency
knowledge consistency
faction consistency
time consistency
```

以后可以增加AI Critic，但程序检查优先。

---

# 64. 配置驱动

修仙规则不要全部写在Python里。

例如：

```text
content/cultivation_v1/rules.yaml
content/cultivation_v1/realms.yaml
content/cultivation_v1/items.yaml
content/cultivation_v1/skills.yaml
content/cultivation_v1/factions.yaml
```

这样未来换世界包：

```text
content/wuxia_v1
content/apocalypse_v1
```

可以复用引擎。

---

# 65. Content Pack接口

底层设计：

```text
Engine
+
ContentPack
```

ContentPack包含：

```text
world lore
rules
classes/realms
locations
characters
items
skills
factions
event templates
narrative style
seed conflicts
```

禁止把“青云宗”等内容硬编码到底层engine。

---

# 66. 开发阶段

不要试图一次把全部复杂功能写完。

按照以下顺序推进。

## Phase 0 — Repository Audit

如果仓库已经存在：

首先完整阅读：

```text
README
docs
package config
dependencies
database
existing source
tests
```

禁止直接覆盖已有工程。

输出：

```text
docs/CURRENT_STATE.md
```

记录当前项目情况。

---

## Phase 1 — Architecture

首先建立：

```text
docs/ARCHITECTURE.md
docs/DATA_MODEL.md
docs/GAME_LOOP.md
docs/AI_PIPELINE.md
docs/PROMPTS.md
docs/ROADMAP.md
```

然后建立项目骨架。

但是：

不要停在设计文档。

继续实现。

---

## Phase 2 — Deterministic Core

先不调用LLM。

实现：

```text
World
Character
Location
Inventory
Rules
Action
EventLog
WorldClock
```

确保纯程序测试通过。

---

## Phase 3 — Database

建立：

```text
SQLAlchemy models
Alembic migrations
seed system
repositories
services
```

建立测试世界。

---

## Phase 4 — Intent AI

接入：

```text
Player Input
→ Intent
→ Action
```

但仍使用程序裁决。

---

## Phase 5 — NPC System

实现：

```text
Personality
Goals
Relationship
Knowledge
NPC Decision
```

首先测试知识隔离。

---

## Phase 6 — Memory

实现：

```text
pgvector
Memory extraction
Memory retrieval
Memory ranking
```

---

## Phase 7 — Director

实现：

```text
PlotThread
NarrativeTension
Director
Event proposals
Validation
```

---

## Phase 8 — Narrative

最后接Narrative Renderer。

此时应该已经能够：

```text
玩家输入
→ 世界真正变化
→ 最后生成小说
```

---

## Phase 9 — World Simulation

增加：

```text
NPC schedules
Faction simulation
LOD
remote events
```

---

## Phase 10 — Frontend

完成真正可玩的Web MVP。

---

# 67. 每阶段完成标准

每一个阶段：

1. 实现代码；
2. 写测试；
3. 运行测试；
4. 修复错误；
5. 检查类型；
6. 检查Lint；
7. 更新文档；
8. 提交清晰的阶段总结。

不要仅告诉我：

```text
“建议接下来实现……”
```

如果条件允许，就直接继续实现。

---

# 68. 自主工作原则

在开发过程中：

如果遇到普通工程决策：

> 自己做合理判断。

不要因为：

```text
文件名
目录名
变量名
UI小细节
普通依赖选择
```

频繁停止询问。

将重要假设记录到：

```text
docs/DECISIONS.md
```

只有真正涉及：

```text
产品方向重大变化
不可逆数据操作
用户必须提供的外部凭据
完全无法推断的重要需求
```

时才需要人工输入。

---

# 69. 不允许的做法

禁止：

### 1

实现为：

```text
一个巨大Prompt + 一个LLM调用
```

### 2

让Narrative AI直接修改数据库。

### 3

把整个数据库全部放入Context。

### 4

所有NPC共享上帝视角。

### 5

所有游戏逻辑都由LLM决定。

### 6

每个NPC每个时间单位调用一次LLM。

### 7

只写几十个if形成不可扩展剧情树。

### 8

将修仙内容硬编码到底层引擎。

### 9

因为AI返回JSON就默认其正确。

必须验证。

### 10

做大量UI，却没有稳定世界引擎。

---

# 70. 优先级

出现冲突时，优先级为：

```text
1 世界逻辑一致性

2 数据正确性

3 人物行为合理性

4 玩家行为自由度

5 长期因果

6 游戏性

7 小说质量

8 UI视觉效果
```

漂亮文字不能掩盖错误世界逻辑。

---

# 71. V1核心验证目标

第一版不是验证：

> AI能不能写漂亮小说。

现在的大模型已经能够做到这一点。

真正验证：

### Test A

玩家说任何自然语言行为，系统能否理解？

### Test B

不合理行为，世界能否拒绝？

### Test C

NPC是否只根据自己知道的信息行动？

### Test D

NPC是否保持长期人格一致性？

### Test E

玩家过去行为是否真正影响未来？

### Test F

玩家离开的地方是否仍发生变化？

### Test G

剧情是否来自世界因果，而不是随机续写？

### Test H

玩几个小时以后世界是否仍然自洽？

---

# 72. 最重要的最终体验

最终玩家应该产生：

不是：

> “AI正在给我生成小说。”

而是：

> “这个世界真的存在，而AI让我能够用自然语言生活在里面。”

玩家十小时前：

```text
救了某个人
```

十小时后：

这个人仍然记得。

玩家杀死一个人：

他的朋友可能仇恨玩家。

玩家错过一场比赛：

别人会夺冠。

玩家闭关三年：

世界已经发生变化。

玩家离开宗门：

宗门不会暂停。

玩家失败：

世界接受失败并继续发展。

这才是产品核心。

---

# 73. 第一阶段现在开始执行

现在开始实际工作。

首先：

1. 检查当前Repository；
2. 理解所有已有代码；
3. 不要破坏已有功能；
4. 建立`docs/ARCHITECTURE.md`；
5. 建立`docs/DATA_MODEL.md`；
6. 建立`docs/GAME_LOOP.md`；
7. 建立`docs/AI_PIPELINE.md`；
8. 建立`docs/ROADMAP.md`；
9. 明确V1模块依赖；
10. 建立项目目录；
11. 实现 deterministic core；
12. 建立测试；
13. 实际运行测试；
14. 修复测试；
15. 继续推进下一阶段。

不要只生成规划。

在完成架构设计后直接开始实现。

如果项目为空，从零初始化。

如果项目已有代码，在现有结构上合理演进。

---

# 74. 工作方式

在开发过程中始终遵循：

```text
Inspect
↓
Understand
↓
Plan
↓
Implement
↓
Test
↓
Inspect Result
↓
Fix
↓
Document
↓
Continue
```

不要：

```text
Plan
↓
大量生成代码
↓
不运行
↓
声称完成
```

必须真实检查代码和测试结果。

---

# 75. 最终架构目标

最终项目应该形成：

```text
                 AI WORLD ENGINE
                       │
          ┌────────────┼────────────┐
          │            │            │
      World State   Rule Engine   Event Engine
          │            │            │
          ├────────────┼────────────┤
          │            │            │
      NPC System    Memory       Director
          │            │            │
          └────────────┼────────────┘
                       │
                 Context Engine
                       │
                     LLM
                       │
               Narrative Renderer

================================================

                   CONTENT PACKS

        Cultivation / Wuxia / Sci-Fi / Apocalypse
```

**Engine不应该知道自己运行的是“修仙”。**

修仙应该只是第一个Content Pack。

这是项目长期可扩展性的核心。

现在开始检查Repository并执行Phase 0与Phase 1，然后继续实现，不要停留在概念讨论。
