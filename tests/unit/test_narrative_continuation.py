from engine.narrative.style import (
    filter_repeated_paragraphs,
    repeated_opening_length,
    strip_repeated_opening,
)

PREVIOUS = (
    "礼堂的木门在她身后合上。朝仓律把旧账本放到桌面，指着缺失的那一页，"
    "让所有人先不要声张。\n\n"
    "窗外的广播刚好响起，催促企划组去参加下午的预算会议。她收好笔记，答应会准时到场。"
)


def test_exact_previous_paragraphs_are_removed_from_a_continuation() -> None:
    continuation = (
        PREVIOUS + "\n\n预算会议开始时，财务组先投出了修缮费用的新估算。她翻开笔记，直接问起缺口。"
    )

    assert strip_repeated_opening(continuation, PREVIOUS) == (
        "预算会议开始时，财务组先投出了修缮费用的新估算。她翻开笔记，直接问起缺口。"
    )


def test_stream_holds_an_unfinished_possible_duplicate() -> None:
    partial = PREVIOUS[:80]

    assert repeated_opening_length(partial, PREVIOUS) == -1


def test_short_intentional_echo_is_not_removed() -> None:
    callback = "“先不要声张。”她又确认了一遍。\n\n朝仓律点了点头。"

    assert strip_repeated_opening(callback, PREVIOUS) == callback


def test_repeated_scene_is_removed_even_after_a_new_bridge_paragraph() -> None:
    continuation = (
        "你刚把柴房门闩插好，前院的枪托就砸上了门板。\n\n"
        + PREVIOUS
        + "\n\n门外有人开始逐间查房，你把灯图塞进了干草下面。"
    )

    assert filter_repeated_paragraphs(continuation, PREVIOUS) == (
        "你刚把柴房门闩插好，前院的枪托就砸上了门板。\n\n"
        "门外有人开始逐间查房，你把灯图塞进了干草下面。"
    )


def test_response_cannot_repeat_its_own_paragraph() -> None:
    paragraph = "掌柜把账本推过来，让你自己看那一页被撕掉的记录。纸边很新，墨却是十年前的。"
    continuation = f"{paragraph}\n\n{paragraph}\n\n你翻到封底，找到一枚倒着盖的印。"

    assert filter_repeated_paragraphs(continuation, "") == (
        f"{paragraph}\n\n你翻到封底，找到一枚倒着盖的印。"
    )


def test_streaming_filter_never_exposes_a_possible_late_duplicate() -> None:
    bridge = "你刚把柴房门闩插好，前院的枪托就砸上了门板。"
    duplicate = PREVIOUS.split("\n\n")[0]
    partial = f"{bridge}\n\n{duplicate[:80]}"

    assert filter_repeated_paragraphs(partial, PREVIOUS, final=False) == bridge
