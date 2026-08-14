from __future__ import annotations


def test_all_llm_control_prompts_are_written_in_chinese(registry) -> None:
    forbidden_english_instructions = (
        "You are",
        "You MUST",
        "You may",
        "Return ONLY",
        "Never invent",
        "Output schema",
        "Write the scene",
    )
    roles = [role for role, _version in registry.available()]
    assert roles
    for role in roles:
        body = registry.get(role, "v1").body
        assert any("\u4e00" <= char <= "\u9fff" for char in body), role
        assert not any(phrase in body for phrase in forbidden_english_instructions), role

    common = registry.common_constraints()
    assert "只返回一个 JSON 对象" in common


def test_structured_output_repair_instruction_is_chinese(registry) -> None:
    instruction = registry.render(
        "structured_repair", "v1", error="字段缺失", previous="{}", schema="{}"
    )
    assert instruction.startswith("你上一次的输出未通过校验")
    assert "请只返回一个" in instruction
    assert "Your previous response" not in instruction


def test_shared_runtime_prompts_do_not_assume_the_cultivation_genre(registry) -> None:
    shared_roles = (
        "prologue",
        "narrative",
        "chapter",
        "director",
        "world_steward",
        "autopilot",
        "autopilot_run",
    )
    cultivation_terms = (
        "修仙",
        "东方玄幻",
        "宗门",
        "灵石",
        "功法",
        "境界",
        "坊市",
        "灵药",
        "炼气",
        "阵契",
    )

    for role in shared_roles:
        body = registry.get(role, "v1").body
        found = [term for term in cultivation_terms if term in body]
        assert not found, f"{role} contains genre-specific terms: {found}"
