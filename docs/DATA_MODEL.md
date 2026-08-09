# DATA_MODEL

数据库是“世界的事实”。所有表见 `database/models/`。
JSON 列在 PostgreSQL 上映射为 `JSONB`，在 SQLite 上为 `JSON`。

---

## 1. 实体总览

```text
worlds ─┬─ locations (自引用树)
        ├─ factions
        ├─ characters ─┬─ character_stats(内联)
        │              ├─ inventory_items → items
        │              ├─ character_skills → skills
        │              ├─ character_knowledge → facts
        │              ├─ memories
        │              └─ relationships (a↔b)
        ├─ facts
        ├─ quests
        ├─ events (append-only)
        ├─ plot_threads
        ├─ story_arcs
        ├─ game_sessions ─┬─ turns ─ turn_traces
        │                 └─ narrative_segments
        └─ world_clock(内联 worlds.current_minute)
```

---

## 2. 核心表

### worlds
| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| name | str | |
| description | text | |
| current_minute | BigInt | 世界纪元起点以来的分钟数（D-005） |
| calendar_config | JSON | 来自 content pack |
| world_seed | str | GameRNG 根种子 |
| content_pack | str | 如 `cultivation_v1` |
| rule_version | str | 规则版本，用于回放兼容 |
| narrative_tension | float | 0-100（§25） |
| created_at / updated_at | ts | |

### locations
`id, world_id, parent_id(自引用), key, name, location_type, description,
coordinates(JSON), danger_level(int), faction_id, spirit_density(float),
travel_minutes(JSON: 相邻位置key→分钟), metadata(JSON)`

层级：`大陆 → 地区 → 城市/宗门 → 建筑 → 房间`（`location_type` 枚举来自内容包）。

### factions
`id, world_id, key, name, description, faction_type, headquarters_location_id,
resources(JSON), member_count, territory(JSON), military_power, reputation,
leader_character_id, alliances(JSON), enemies(JSON), goals(JSON),
internal_conflicts(JSON), metadata`

### characters
```text
id, world_id, key, name, character_type(PLAYER|MAJOR_NPC|MINOR_NPC|BACKGROUND)
age, gender, location_id, faction_id, faction_rank

realm, realm_stage, cultivation_progress, cultivation_speed,
spiritual_root(JSON), bottleneck(float), mental_state(float)

health, max_health, spiritual_power, max_spiritual_power
strength, agility, perception, intelligence, willpower, charisma

personality(JSON)   -- traits/values/taboos/speech_style/risk_tolerance
values_(JSON)       -- 冗余快捷访问
background(text)
long_term_goal, short_term_goal(JSON list)
current_emotion(JSON)   -- {valence,arousal,dominant,intensity,updated_at_minute}
injuries(JSON)
schedule(JSON)          -- §32
reputation(JSON)        -- {global, by_faction, by_region}
alive(bool), death_event_id, created_at, updated_at
```

> §12：Character 不得只有一段自然语言 profile —— 上面所有数值字段均为结构化列。
> `personality` 与 `current_emotion` 严格分离（§13）：前者变化极慢（有 `personality_drift_cap`），
> 后者每回合可变。

### relationships
`id, world_id, character_a_id, character_b_id,
affection, trust, respect, fear, hatred, suspicion, dependency, familiarity (均 int, -100..100 或 0..100),
last_interaction_minute, interaction_count, tags(JSON), updated_at`

**有向**（a 对 b 的看法），(a,b) 唯一索引。
每次变化写 `relationship_changes`：`relationship_id, dimension, delta, before, after,
reason, event_id, clamped(bool), minute`（§14 要求“有原因/有幅度限制/有日志/与事件对应”）。

### facts / character_knowledge（§15 核心）
```text
facts:
  id, world_id, key, statement, truth_value(bool|null),
  scope(WORLD|FACTION|PERSONAL), sensitivity(0-1),
  subject_character_id, related_characters(JSON),
  created_at_minute, source_event_id

character_knowledge:
  id, character_id, fact_id,
  knowledge_state(UNKNOWN|HEARD|SUSPECTED|BELIEVED|KNOWN|DISBELIEVED),
  confidence(0-1), source(WITNESSED|TOLD_BY|INFERRED|RUMOR|DOCUMENT|SEED),
  source_character_id, learned_at_minute, notes
  UNIQUE(character_id, fact_id)
```

**安全边界**：`ContextBuilder.build_npc_context()` 只能 join `character_knowledge`
且 `knowledge_state != UNKNOWN`，并按 `confidence` 降级措辞。
`facts.truth_value` 永远不进入 NPC context。

### memories（§16）
```text
id, world_id, owner_character_id,
memory_type(WORKING|EPISODIC|RELATIONSHIP|SEMANTIC),
memory_tag(promise|betrayal|rescue|insult|conflict|gift|romantic_event|
           shared_danger|major_conversation|secret_disclosure|trauma|victory|failure|other),
summary, importance(0-1), emotional_valence(-1..1),
related_characters(JSON), related_event_id, related_location_id,
created_at_minute, last_recalled_minute, recall_count, decay(0-1),
embedding(JSON | vector(N))
```

检索得分（不是纯 Top-K）：

```text
score = w_sim*cosine
      + w_imp*importance
      + w_rec*recency_decay(minutes_since)
      + w_rel*relationship_relevance
      + w_ctx*context_overlap
```

权重来自 `content/<pack>/rules.yaml::memory.retrieval_weights`。

### events（§17，append-only）
```text
id, world_id, turn_id, event_type, actor_id, target_ids(JSON), location_id,
before(JSON), after(JSON), causes(JSON: 文本原因), cause_event_ids(JSON: 因果链 §44),
payload(JSON), world_minute, rng_seed, importance(0-1),
visibility(PUBLIC|LOCAL|FACTION|PRIVATE|SECRET), witnesses(JSON),
created_at
```
**永不 UPDATE / DELETE**（ORM 层加 `__mapper_args__` + 仓储层禁写守卫 + 测试断言）。

### plot_threads / story_arcs（§23）
`id, world_id, key, name, status(dormant|active|resolved|failed|abandoned),
importance, stage, participants(JSON), unresolved_questions(JSON),
foreshadowing(JSON), last_advanced_minute, next_beat_hint, metadata`

### quests（§41）
`id, world_id, key, name, giver_character_id, assignee_character_id,
status(offered|active|completed|failed|expired|taken_by_other),
goal(JSON), constraints(JSON), participants(JSON), rewards(JSON),
failure_conditions(JSON), expires_at_minute, world_consequences(JSON), plot_thread_id`

> 玩家拒绝任务后，任务仍可由 NPC 承接（`taken_by_other`）并产生世界后果。

### items / inventory_items / skills / character_skills
```text
items:            id, world_id, key, name, item_type, rarity, description,
                  effects(JSON), value, stackable, metadata
inventory_items:  id, character_id, item_id, quantity, equipped, bound, acquired_at_minute
skills:           id, world_id, key, name, category, required_realm, required_stage,
                  spiritual_cost, cooldown_minutes, power, effects(JSON), metadata
character_skills: id, character_id, skill_id, mastery(0-1), learned_at_minute,
                  last_used_minute
```

### game_sessions / turns / turn_traces / narrative_segments
```text
game_sessions: id, world_id, player_character_id, session_seed, status,
               created_at, last_active_at
turns:         id, session_id, turn_number, player_input, intent(JSON),
               action(JSON), rule_result(JSON), outcome(JSON),
               npc_decisions(JSON), director_decision(JSON),
               state_changes(JSON), world_minute_before, world_minute_after,
               idempotency_key(UNIQUE), created_at
turn_traces:   id, turn_id, request_id, stage_timings(JSON), llm_calls(JSON),
               rng_traces(JSON), context_snapshots(JSON), errors(JSON),
               token_usage(JSON)
narrative_segments: id, session_id, turn_id, kind(scene|chapter_summary|long_term),
               text, world_minute, created_at
```
`narrative_segments` 实现 §45 的 raw transcript / scene summary / chapter summary / long-term history 分层。

---

## 3. 索引要点

```sql
idx_characters_world_location        (world_id, location_id, alive)
idx_relationships_pair               (character_a_id, character_b_id) UNIQUE
idx_knowledge_char_fact              (character_id, fact_id) UNIQUE
idx_memories_owner_importance        (owner_character_id, importance DESC)
idx_events_world_minute              (world_id, world_minute)
idx_events_actor                     (actor_id, world_minute)
idx_turns_session_number             (session_id, turn_number) UNIQUE
idx_turns_idem                       (idempotency_key) UNIQUE
-- postgres only
idx_memories_embedding  USING ivfflat (embedding vector_cosine_ops)
```

---

## 4. 扩展性预留

- `realm` / `realm_stage` 存 **字符串 key**（如 `qi_refining`），显示名来自内容包。
  新增元婴/化神/…只需改 `realms.yaml`，无需迁移（§2）。
- 所有枚举在 DB 中存字符串，Python 侧用 `StrEnum` 校验。
- `metadata` JSON 列作为内容包私有扩展点，引擎不解释其内容。
