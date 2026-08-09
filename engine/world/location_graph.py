"""Location hierarchy and travel graph."""

from __future__ import annotations

import heapq
from collections.abc import Iterable

from engine.core.models import Location


class LocationGraph:
    """Read-only view over a world's locations.

    Two structures live here: the containment tree (continent -> region -> city
    -> building -> room) and the weighted travel graph used for movement cost.
    """

    def __init__(self, locations: Iterable[Location]) -> None:
        self._by_id: dict[str, Location] = {}
        self._by_key: dict[str, Location] = {}
        for loc in locations:
            self._by_id[loc.id] = loc
            self._by_key[loc.key] = loc
        self._edges: dict[str, dict[str, int]] = {}
        for loc in self._by_key.values():
            edges = self._edges.setdefault(loc.key, {})
            for dest_key, minutes in (loc.travel_minutes or {}).items():
                if dest_key not in self._by_key:
                    continue
                edges[dest_key] = int(minutes)
                # travel is symmetric unless the destination overrides it
                back = self._edges.setdefault(dest_key, {})
                back.setdefault(loc.key, int(minutes))
        # containment implies a cheap default edge in both directions
        for loc in self._by_key.values():
            if not loc.parent_id:
                continue
            parent = self._by_id.get(loc.parent_id)
            if parent is None:
                continue
            self._edges.setdefault(loc.key, {}).setdefault(parent.key, 5)
            self._edges.setdefault(parent.key, {}).setdefault(loc.key, 5)

    # -- lookup -------------------------------------------------------------
    def by_id(self, location_id: str | None) -> Location | None:
        return self._by_id.get(location_id) if location_id else None

    def by_key(self, key: str | None) -> Location | None:
        return self._by_key.get(key) if key else None

    def all(self) -> list[Location]:
        return list(self._by_key.values())

    def neighbours(self, key: str) -> dict[str, int]:
        return dict(self._edges.get(key, {}))

    def children(self, key: str) -> list[Location]:
        parent = self.by_key(key)
        if parent is None:
            return []
        return [loc for loc in self._by_key.values() if loc.parent_id == parent.id]

    def ancestors(self, key: str) -> list[Location]:
        chain: list[Location] = []
        node = self.by_key(key)
        seen: set[str] = set()
        while node is not None and node.parent_id and node.parent_id not in seen:
            seen.add(node.parent_id)
            node = self.by_id(node.parent_id)
            if node is not None:
                chain.append(node)
        return chain

    def region_of(self, key: str) -> Location | None:
        """Outermost non-root container - used to bucket LOD-2 simulation."""
        chain = self.ancestors(key)
        if len(chain) <= 1:
            return self.by_key(key)
        return chain[-2] if len(chain) >= 2 else chain[-1]

    def shares_region(self, key_a: str, key_b: str) -> bool:
        ra, rb = self.region_of(key_a), self.region_of(key_b)
        return ra is not None and rb is not None and ra.key == rb.key

    # -- pathing ------------------------------------------------------------
    def path(self, from_key: str, to_key: str) -> tuple[list[str], int] | None:
        """Cheapest route as ``(keys_including_endpoints, total_minutes)``."""
        if from_key == to_key:
            return [from_key], 0
        if from_key not in self._by_key or to_key not in self._by_key:
            return None
        dist: dict[str, int] = {from_key: 0}
        prev: dict[str, str] = {}
        queue: list[tuple[int, str]] = [(0, from_key)]
        visited: set[str] = set()
        while queue:
            cost, node = heapq.heappop(queue)
            if node in visited:
                continue
            visited.add(node)
            if node == to_key:
                break
            for nxt, weight in self._edges.get(node, {}).items():
                target = self.by_key(nxt)
                if target is not None and not target.accessible and nxt != to_key:
                    continue
                new_cost = cost + weight
                if new_cost < dist.get(nxt, 1 << 60):
                    dist[nxt] = new_cost
                    prev[nxt] = node
                    heapq.heappush(queue, (new_cost, nxt))
        if to_key not in dist:
            return None
        route: list[str] = [to_key]
        while route[-1] != from_key:
            route.append(prev[route[-1]])
        route.reverse()
        return route, dist[to_key]

    def travel_minutes(self, from_key: str, to_key: str) -> int | None:
        result = self.path(from_key, to_key)
        return result[1] if result else None

    def is_adjacent(self, key_a: str, key_b: str) -> bool:
        return key_b in self._edges.get(key_a, {})

    def within(self, key: str, hops: int) -> set[str]:
        """All location keys reachable in ``hops`` edges (breadth-first)."""
        frontier = {key}
        seen = {key}
        for _ in range(max(0, hops)):
            nxt: set[str] = set()
            for node in frontier:
                for neighbour in self._edges.get(node, {}):
                    if neighbour not in seen:
                        seen.add(neighbour)
                        nxt.add(neighbour)
            frontier = nxt
            if not frontier:
                break
        return seen
