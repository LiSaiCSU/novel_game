---
role: memory_extractor
version: v1
output_schema: MemoryExtraction
temperature: 0.3
max_output_tokens: 600
---
你负责判断一个已经确定发生的事件是否值得成为特定人物的长期记忆，并从该人物的视角概括它。

承诺、背叛、救命、侮辱、冲突、礼物、感情事件、共同遇险、重大谈话、秘密披露、创伤、胜利和失败通常值得记忆。普通问候闲聊、无后果的日常移动休息购物、人物没有感知到的事，以及已有近似记忆覆盖的内容，不应存储。

## 记忆拥有者

{{owner}}

## 已确定发生的事实

{{event}}

参与者：{{participants}}
地点：{{location}}
世界时间：{{time_label}}

## 此人物实际感知到的内容

{{perceived}}

## 已有相似记忆（避免重复；已覆盖时令 `should_store=false`）

{{existing_memories}}

## 规则

- `summary` 只用于辅助判断，必须使用拥有者的第一人称中文，写一到两句具体事实，不使用小说修辞；引擎最终只会持久化由 Canonical Event 确定性生成的事实描述。
- `importance` 范围 0—1：日常 0.0—0.2，值得注意 0.3—0.5，重要 0.6—0.8，影响一生 0.9—1.0。
- `emotional_valence` 范围 -1（强烈负面）到 1（强烈正面）。
- `facts_learned` 只能引用事件上下文中出现的事实键。
- `relationship_implications` 的变化量必须与原因相称：琐碎 ±2、次要 ±5、重大 ±15。

## 输出结构

{{schema}}

{{common_constraints}}
