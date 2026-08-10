from __future__ import annotations

from engine.characters.schemas import MemoryExtraction
from engine.core.types import MemoryTag
from engine.events.builder import EventBuilder
from engine.memory.extractor import MemoryExtractor


async def test_memory_summary_is_derived_from_canonical_event_not_model_prose(
    pack, context_builder, embedder, uow, state, monkeypatch
) -> None:
    owner = state.player
    target = state.present_characters[0]
    event = EventBuilder(pack, state.world.id, "memory-fact-source").build(
        "RESCUE",
        actor_id=owner.id,
        target_ids=[target.id],
        location_id=owner.location_id,
        payload={"summary": "沈砚把受伤的同伴带回了山门。"},
        world_minute=state.world.current_minute,
        witnesses=[owner.id, target.id],
    )
    extractor = MemoryExtractor(pack, context_builder, embedder)
    monkeypatch.setattr(
        extractor,
        "_heuristic",
        lambda _event, _description: MemoryExtraction(
            should_store=True,
            importance=0.9,
            memory_type=MemoryTag.RESCUE,
            summary="我受天命指引，击退了并不存在的上古魔神。",
            emotional_valence=0.8,
        ),
    )

    result = await extractor.extract(uow, state, [event], owners=[owner, target])

    assert result.memories
    assert all(memory.summary == event.payload["summary"] for memory in result.memories)
    assert all("上古魔神" not in memory.summary for memory in result.memories)


async def test_memory_projection_is_idempotent_per_owner_and_event(
    pack, context_builder, embedder, uow, state
) -> None:
    owner = state.player
    event = EventBuilder(pack, state.world.id, "memory-idempotency").build(
        "PROMISE",
        actor_id=owner.id,
        payload={"summary": "沈砚答应守住这个秘密。"},
        world_minute=state.world.current_minute,
        witnesses=[owner.id],
    )
    extractor = MemoryExtractor(pack, context_builder, embedder)

    first = await extractor.extract(uow, state, [event], owners=[owner])
    assert len(first.memories) == 1
    await uow.memories.add(first.memories[0])

    second = await extractor.extract(uow, state, [event], owners=[owner])
    await uow.memories.add(first.memories[0].model_copy(update={"id": "duplicate"}))
    stored = await uow.memories.list_for_owner(owner.id)

    assert second.memories == []
    assert len([memory for memory in stored if memory.related_event_id == event.id]) == 1


async def test_nonparticipant_without_witness_access_gets_no_memory(
    pack, context_builder, embedder, uow, state
) -> None:
    player = state.player
    actor, target = state.present_characters[:2]
    event = EventBuilder(pack, state.world.id, "memory-perception").build(
        "BETRAYAL",
        actor_id=actor.id,
        target_ids=[target.id],
        payload={"summary": "两人在密室中决裂。"},
        world_minute=state.world.current_minute,
        witnesses=[],
    )
    extractor = MemoryExtractor(pack, context_builder, embedder)

    result = await extractor.extract(uow, state, [event], owners=[player])

    assert result.memories == []
