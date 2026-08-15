from engine.narrative.style import (
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
