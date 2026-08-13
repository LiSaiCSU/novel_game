"""Curated starter projects shared by the web studio and author CLI.

Templates are executable product contracts: every entry is parsed and
compiled in CI. Keeping them in the application authoring package prevents the web client,
API and command-line tools from drifting into three subtly different schemas.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from engine.contentpack.schema_v2 import ContentPackageV2

TemplateComplexity = Literal["starter", "guided", "advanced"]


@dataclass(frozen=True, slots=True)
class ProjectTemplate:
    key: str
    title: str
    description: str
    genre_tags: tuple[str, ...]
    recommended_for: str
    complexity: TemplateComplexity
    build: Callable[[str, str, str, str, str], dict[str, Any]]

    def summary(self) -> dict[str, Any]:
        sample = ContentPackageV2.model_validate(
            self.build("示例作品", "example-story", "", "zh-CN", "16+")
        )
        content = sample.content
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "genre_tags": list(self.genre_tags),
            "recommended_for": self.recommended_for,
            "complexity": self.complexity,
            "counts": {
                "locations": len(content.locations),
                "characters": len(content.characters),
                "facts": len(content.facts),
                "quests": len(content.quests),
                "plot_threads": len(content.plot_threads),
                "author_tests": len(sample.author_tests),
            },
        }


def _base_document(
    title: str,
    slug: str,
    summary: str,
    locale: str,
    rating: str,
) -> dict[str, Any]:
    key = slug.replace("-", "_")
    return {
        "manifest": {
            "schema_version": "2.0",
            "key": key,
            "slug": slug,
            "title": title,
            "summary": summary or "一个等待被写下的互动世界。",
            "version": "0.1.0",
            "locale": locale,
            "rating": rating,
            "engine": {
                "api_version": "2",
                "min_version": "0.2.0",
                "max_version": None,
            },
            "entry_scenario": "main_story",
            "player_fields": [
                {
                    "key": "name",
                    "label": "姓名",
                    "type": "text",
                    "required": True,
                    "default": None,
                    "minimum": None,
                    "maximum": None,
                    "choices": [],
                    "binding": "property",
                }
            ],
            "capabilities": ["free_text", "relationships", "saves"],
            "theme": {
                "accent": "#8d5f73",
                "background": "#f7f1eb",
                "surface": "#fffaf6",
                "text": "#292229",
                "heading_font": "serif",
                "body_font": "sans-serif",
            },
            "assets": [],
            "trusted_rule_plugin": None,
        },
        "content": {
            "world": {
                "name": title,
                "description": summary,
                "start_location": "opening_scene",
                "world_seed_default": f"{key}-seed",
            },
            "story": {},
            "endings": [],
            "scenarios": [
                {
                    "key": "main_story",
                    "title": "序章",
                    "premise": summary,
                    "start_location": "opening_scene",
                    "player_template": {
                        "attributes": {"insight": 10, "empathy": 10},
                        "resources": {"energy": 100},
                        "progressions": {
                            "story": {
                                "track": "story",
                                "tier": "beginning",
                                "stage": "active",
                                "progress": 0,
                            }
                        },
                    },
                    "initial_threads": [],
                }
            ],
            "locations": [
                {
                    "key": "opening_scene",
                    "name": "开场地点",
                    "parent": None,
                    "travel": {},
                    "description": "故事从这里开始。",
                }
            ],
            "organizations": [],
            "characters": [],
            "relationships": [],
            "facts": [],
            "items": [],
            "abilities": [],
            "quests": [],
            "plot_threads": [],
            "event_templates": [],
            "offline_templates": [],
            "npc_templates": {},
            "engine_rules": {},
            "calendar": {},
            "narrative": {
                "style": {
                    "voice": "贴近人物感受的第三人称限知",
                    "dialogue_ratio": 0.45,
                    "max_scene_chars": 1800,
                }
            },
            "vocabulary": {},
            "attributes": [
                {"key": "insight", "label": "洞察", "default": 10},
                {"key": "empathy", "label": "共情", "default": 10},
            ],
            "resources": [
                {"key": "energy", "label": "精力", "minimum": 0, "maximum": 100, "default": 100}
            ],
            "progressions": [
                {
                    "key": "story",
                    "label": "故事阶段",
                    "tiers": [
                        {"key": "beginning", "label": "开端", "order": 0},
                        {"key": "turning_point", "label": "转折", "order": 1},
                        {"key": "resolution", "label": "收束", "order": 2},
                    ],
                }
            ],
            "rules": [],
        },
        "author_tests": [
            {
                "key": "opening_state",
                "name": "Opening state is playable",
                "scenario": "main_story",
                "assertions": [
                    {"path": "player.location", "op": "eq", "expected": "opening_scene"},
                    {"path": "player.resources.energy", "op": "eq", "expected": 100},
                    {"path": "characters.player.alive", "op": "eq", "expected": True},
                ],
            }
        ],
    }


def _blank(title: str, slug: str, summary: str, locale: str, rating: str) -> dict[str, Any]:
    return _base_document(title, slug, summary, locale, rating)


def _relationship_drama(
    title: str,
    slug: str,
    summary: str,
    locale: str,
    rating: str,
) -> dict[str, Any]:
    document = _base_document(title, slug, summary, locale, rating)
    content = document["content"]
    content["world"]["description"] = summary or "一群成年人必须在共同目标与私人选择之间建立信任。"
    content["scenarios"][0].update(
        premise=summary or "你加入一个濒临解散的小组，第一次会议就暴露了彼此并不一致的目标。",
        initial_threads=["shared_project"],
    )
    content["locations"] = [
        {
            "key": "opening_scene",
            "name": "公共休息室",
            "parent": None,
            "travel": {"quiet_cafe": 10, "rooftop_garden": 8},
            "description": "每个人都能经过，却很少有人真正停下来交谈。",
        },
        {
            "key": "quiet_cafe",
            "name": "街角咖啡馆",
            "parent": None,
            "travel": {"opening_scene": 10, "rooftop_garden": 12},
            "description": "适合把重要的话说得慢一点。",
        },
        {
            "key": "rooftop_garden",
            "name": "屋顶花园",
            "parent": None,
            "travel": {"opening_scene": 8, "quiet_cafe": 12},
            "description": "风声给沉默留下了余地。",
        },
    ]
    content["characters"] = [
        _starter_character(
            "steady_partner", "沉稳的合作者", "opening_scene", "先完成共同项目，再决定是否留下"
        ),
        _starter_character("restless_friend", "不安分的朋友", "quiet_cafe", "证明改变方向不是逃避"),
    ]
    content["relationships"] = [
        {
            "a": "steady_partner",
            "b": "player",
            "affection": 0,
            "trust": 5,
            "respect": 8,
            "familiarity": 10,
            "boundaries": 50,
        },
        {
            "a": "restless_friend",
            "b": "player",
            "affection": 2,
            "trust": 3,
            "respect": 4,
            "familiarity": 12,
            "boundaries": 50,
        },
    ]
    content["facts"] = [
        {
            "key": "hidden_deadline",
            "statement": "共同项目真正的截止日期比公开日程早一周",
            "truth_value": True,
            "scope": "PERSONAL",
            "sensitivity": 0.7,
            "subject": "steady_partner",
            "related": ["steady_partner"],
            "initial_knowledge": {
                "steady_partner": {"state": "KNOWN", "confidence": 1, "source": "DOCUMENT"}
            },
        },
    ]
    content["plot_threads"] = [
        {
            "key": "shared_project",
            "name": "必须完成的共同项目",
            "status": "active",
            "importance": 0.9,
            "stage": 0,
            "participants": ["player", "steady_partner", "restless_friend"],
            "unresolved_questions": ["谁愿意承担最后的责任", "隐瞒截止日期的理由是什么"],
            "foreshadowing": ["日程表上有一处被覆盖的日期"],
            "related_facts": ["hidden_deadline"],
            "next_beat_hint": "让玩家在效率、诚实和照顾关系之间作出第一次选择",
            "escalation_pressure": 0.45,
            "scheduled_beats": [],
        },
    ]
    content["quests"] = [
        {
            "key": "first_meeting",
            "name": "完成第一次分工",
            "giver": "steady_partner",
            "status": "offered",
            "goal": {"type": "visit", "location": "opening_scene"},
            "constraints": {},
            "rewards": {},
            "failure_conditions": [],
            "world_consequences": {},
            "plot_thread": "shared_project",
        },
    ]
    document["author_tests"].append(
        {
            "key": "relationship_knowledge_boundaries",
            "name": "Relationship, knowledge, quest and thread fixtures seed correctly",
            "scenario": "main_story",
            "assertions": [
                {"path": "relationships.steady_partner.trust", "op": "eq", "expected": 5},
                {
                    "path": "knowledge.steady_partner.hidden_deadline",
                    "op": "eq",
                    "expected": "KNOWN",
                },
                {
                    "path": "knowledge.player.hidden_deadline",
                    "op": "eq",
                    "expected": "UNKNOWN",
                },
                {"path": "quests.first_meeting.status", "op": "eq", "expected": "offered"},
                {
                    "path": "plot_threads.shared_project.status",
                    "op": "eq",
                    "expected": "active",
                },
            ],
        }
    )
    return document


def _mystery(title: str, slug: str, summary: str, locale: str, rating: str) -> dict[str, Any]:
    document = _relationship_drama(title, slug, summary, locale, rating)
    document["manifest"]["capabilities"] = ["free_text", "knowledge", "quests", "saves"]
    content = document["content"]
    content["world"]["description"] = (
        summary or "一桩没有暴力危险、但每个人都只知道部分真相的失物谜案。"
    )
    content["scenarios"][0]["premise"] = (
        summary or "重要展品在开放日前消失。你必须分辨误会、隐瞒与真正的动机。"
    )
    content["facts"][0].update(
        key="misdated_inventory",
        statement="失物清单的登记时间比闭馆时间晚二十分钟",
        subject="steady_partner",
    )
    content["plot_threads"][0].update(
        key="missing_exhibit",
        name="消失的展品",
        related_facts=["misdated_inventory"],
        unresolved_questions=["谁修改了清单时间", "展品是否真的离开过建筑"],
    )
    content["scenarios"][0]["initial_threads"] = ["missing_exhibit"]
    content["quests"][0].update(
        key="inspect_scene",
        name="检查最初现场",
        plot_thread="missing_exhibit",
    )
    document["author_tests"] = [
        document["author_tests"][0],
        {
            "key": "mystery_knowledge_boundaries",
            "name": "Mystery clue remains isolated at the opening",
            "scenario": "main_story",
            "assertions": [
                {
                    "path": "knowledge.steady_partner.misdated_inventory",
                    "op": "eq",
                    "expected": "KNOWN",
                },
                {
                    "path": "knowledge.player.misdated_inventory",
                    "op": "eq",
                    "expected": "UNKNOWN",
                },
                {"path": "quests.inspect_scene.status", "op": "eq", "expected": "offered"},
                {
                    "path": "plot_threads.missing_exhibit.status",
                    "op": "eq",
                    "expected": "active",
                },
            ],
        },
    ]
    return document


def _starter_character(key: str, name: str, location: str, goal: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "type": "MAJOR_NPC",
        "age": 22,
        "gender": "unspecified",
        "location": location,
        "attributes": {"insight": 11, "empathy": 11},
        "background": "请在这里写下与主线冲突有关、但不依赖玩家存在的人生背景。",
        "personality": {
            "traits": {"observant": 0.7, "cautious": 0.6},
            "values": ["诚实", "自主选择"],
            "taboos": ["用关系施压"],
            "speech_style": "具体、克制，会询问对方的意愿",
            "risk_tolerance": 0.4,
        },
        "emotion": {"dominant": "focused", "valence": 0.1, "arousal": 0.3, "intensity": 0.4},
        "long_term_goal": goal,
        "short_term_goals": ["完成今天的分工"],
        "schedule": {"default": "work", "slots": []},
        "items": [],
        "skills": [],
        "reputation": {"global": 0, "by_faction": {}},
        "secret": "请把秘密改成能产生选择、而不是只制造反转的信息。",
        "capabilities": ["倾听", "协作"],
    }


_TEMPLATES: dict[str, ProjectTemplate] = {
    "blank": ProjectTemplate(
        key="blank",
        title="空白世界",
        description="一个地点和最小通用状态，适合熟悉 Content Pack v2 的创作者。",
        genre_tags=("通用", "最小"),
        recommended_for="已经知道自己要写什么",
        complexity="starter",
        build=_blank,
    ),
    "relationship_drama": ProjectTemplate(
        key="relationship_drama",
        title="人物关系剧",
        description="两个独立目标的主要人物、三处地点、一条共同任务和知识边界。",
        genre_tags=("关系", "群像", "女性向友好"),
        recommended_for="以人物选择和长期关系为核心的作品",
        complexity="guided",
        build=_relationship_drama,
    ),
    "mystery": ProjectTemplate(
        key="mystery",
        title="轻悬疑调查",
        description="从不一致的时间记录开始，演示事实、知识分布、任务和调查线程。",
        genre_tags=("悬疑", "调查", "知识隔离"),
        recommended_for="线索驱动且允许自由调查的作品",
        complexity="guided",
        build=_mystery,
    ),
}


def list_project_templates() -> list[dict[str, Any]]:
    return [template.summary() for template in _TEMPLATES.values()]


def build_project_template(
    template_key: str,
    *,
    title: str,
    slug: str,
    summary: str = "",
    locale: str = "zh-CN",
    rating: Literal["all", "13+", "16+", "18+"] = "16+",
) -> ContentPackageV2:
    try:
        template = _TEMPLATES[template_key]
    except KeyError as exc:
        raise ValueError(f"unknown project template {template_key!r}") from exc
    raw = deepcopy(template.build(title, slug, summary, locale, rating))
    return ContentPackageV2.model_validate(raw)


def project_template_keys() -> tuple[str, ...]:
    return tuple(_TEMPLATES)
