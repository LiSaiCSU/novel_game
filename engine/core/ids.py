"""Identifier helpers.

Entities carry two identifiers:

* ``id``  - a UUID, unique per world instance, generated at seed time.
* ``key`` - a stable content-pack slug (e.g. ``lin_qingxue``). Prompts, tests
  and content YAML always refer to keys; the database joins on ids.
"""

from __future__ import annotations

import uuid

PLAYER_KEY = "player"


def new_id() -> str:
    return str(uuid.uuid4())


def deterministic_id(namespace: str, key: str) -> str:
    """Stable UUID for a (namespace, key) pair.

    Seeding the same world twice with the same seed produces the same ids,
    which makes fixtures and event replay reproducible.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aiworld://{namespace}/{key}"))
