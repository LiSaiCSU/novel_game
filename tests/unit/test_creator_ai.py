from __future__ import annotations

import pytest

from apps.api.creator_ai import (
    StoryBlueprint,
    blueprint_document,
    decode_story_text,
)


def _blueprint() -> StoryBlueprint:
    return StoryBlueprint.model_validate(
        {
            "title": "雨夜失物招领处",
            "summary": "一封没有收件人的信逼迫夜班管理员寻找真相。",
            "tags": ["悬疑", "都市"],
            "world_name": "旧城雨季",
            "world_description": "连日大雨让旧城的秘密重新浮出水面。",
            "opening_title": "失物柜里的来信",
            "opening_premise": "玩家在打烊前发现一封写着明天日期的信。",
            "central_conflict": "有人想让那封信永远消失。",
            "central_question": "寄信的人为何知道明天会发生什么？",
            "next_story_beat": "追查雨伞上的车站编号。",
            "narrative_tone": "克制、潮湿、带一点时间压力。",
            "source_summary": "夜班管理员发现一封来自未来的信。",
            "locations": [
                {"name": "失物招领处", "description": "潮湿的柜台和编号凌乱的储物柜。"},
                {"name": "末班车站", "description": "站台上只有雨声和闪烁的时刻表。"},
            ],
            "characters": [
                {"name": "林雾", "role": "夜班管理员", "goal": "找出寄信人", "tension": "她害怕信里预言成真"},
                {"name": "周澈", "role": "失物常客", "goal": "拿回雨伞", "tension": "他知道车站编号的意义"},
            ],
        }
    )


def test_decode_story_text_accepts_writer_encodings_and_bounds_source() -> None:
    assert decode_story_text("第一章\n雨落下来".encode("utf-8-sig"), "story.txt") == "第一章\n雨落下来"
    assert decode_story_text("设定集".encode("gb18030"), "outline.TXT") == "设定集"
    with pytest.raises(ValueError, match=r"only \.txt"):
        decode_story_text(b"not a document", "story.docx")
    with pytest.raises(ValueError, match="empty"):
        decode_story_text(b" \n\t", "empty.txt")


def test_ai_blueprint_becomes_a_safe_editable_content_pack() -> None:
    package = blueprint_document(
        _blueprint(),
        slug="rainy-lost-and-found",
        title="雨夜失物招领处",
        rating="16+",
    )

    assert package.manifest.slug == "rainy-lost-and-found"
    assert package.manifest.title == "雨夜失物招领处"
    assert package.content.scenarios[0].title == "失物柜里的来信"
    assert len(package.content.locations) >= 2
    assert package.manifest.trusted_rule_plugin is None
