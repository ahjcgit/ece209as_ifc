from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable


@dataclass(frozen=True)
class Label:
    level: str
    categories: FrozenSet[str]

    def __str__(self) -> str:
        if not self.categories:
            return self.level
        return f"{self.level}+{','.join(sorted(self.categories))}"


class Lattice:
    def __init__(self, levels: Iterable[str]) -> None:
        self._levels = list(levels)
        self._rank = {level: idx for idx, level in enumerate(self._levels)}
        if len(self._rank) != len(self._levels):
            raise ValueError("Levels must be unique.")

    def join_level(self, a: str, b: str) -> str:
        return a if self._rank[a] >= self._rank[b] else b

    def can_flow(self, src: Label, dst: Label) -> bool:
        # Level dominance + category containment.
        return (
            self._rank[src.level] <= self._rank[dst.level]
            and src.categories.issubset(dst.categories)
        )
    # For validation purposes.
    def is_valid_level(self, level: str) -> bool:
        return level in self._rank
    

def make_label(level: str, categories: Iterable[str] | None = None) -> Label:
    return Label(level=level, categories=frozenset(categories or []))


def join_labels(lattice: Lattice, labels: Iterable[Label]) -> Label:
    levels: list[str] = []
    categories: set[str] = set()
    for label in labels:
        levels.append(label.level)
        categories.update(label.categories)
    if not levels:
        raise ValueError("Cannot join an empty label set.")
    level = levels[0]
    for other in levels[1:]:
        level = lattice.join_level(level, other)
    return Label(level=level, categories=frozenset(categories))

def is_valid_level(self, level: str) -> bool:
    return level in self._rank