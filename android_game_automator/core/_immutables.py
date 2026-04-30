"""Internal immutable container helpers for core contracts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from typing import TypeVar

_K = TypeVar("_K")
_V = TypeVar("_V")


class FrozenMapping(Mapping[_K, _V]):
    """Small immutable mapping with defensive-copy semantics."""

    __slots__ = ("_data",)

    def __init__(self, source: Mapping[_K, _V] | None = None) -> None:
        self._data: dict[_K, _V] = dict(source or {})

    def __getitem__(self, key: _K) -> _V:
        return self._data[key]

    def __iter__(self) -> Iterator[_K]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenMapping({self._data!r})"

    def __deepcopy__(self, memo: dict[int, object]) -> FrozenMapping[_K, _V]:
        return FrozenMapping(deepcopy(self._data, memo))


def freeze_mapping[K, V](source: Mapping[K, V] | None = None) -> FrozenMapping[K, V]:
    """Copy into an immutable mapping wrapper."""
    return FrozenMapping(source)
