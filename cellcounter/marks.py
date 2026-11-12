"""× の状態（数えるか・陽性か）と、その操作の Undo / Redo。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import Nucleus

AUTO, ADDED, REMOVED = "auto", "added", "removed"
HISTORY_LIMIT = 100


class Marks:
    """自動の結果と、人が直したあとの結果を別々に持つ。"""

    def __init__(self) -> None:
        self.counted_auto: dict[int, bool] = {}
        self.counted: dict[int, bool] = {}
        self.positive_auto: dict[str, dict[int, bool]] = {}
        self.positive: dict[str, dict[int, bool]] = {}

    def set_counted(self, counted_auto: dict[int, bool]) -> None:
        self.counted_auto = dict(counted_auto)
        self.counted = dict(counted_auto)

    def set_judgement(self, marker: str, auto: dict[int, bool]) -> None:
        self.positive_auto[marker] = dict(auto)
        self.positive[marker] = dict(auto)

    def category(self, marker: str | None, nucleus_id: int) -> str | None:
        """その組み合わせのタブでの × の種類。× が無く、消してもいない核は None。

        marker が None なら「DAPI のみ」。数えない核はマーカーのタブに出さない。
        """
        if marker is None:
            auto, final = self.counted_auto[nucleus_id], self.counted[nucleus_id]
        elif not self.counted[nucleus_id]:
            return None
        else:
            auto = self.positive_auto[marker][nucleus_id]
            final = self.positive[marker][nucleus_id]
        if final:
            return AUTO if auto else ADDED
        return REMOVED if auto else None


@dataclass(frozen=True)
class SetCounted:
    nucleus_id: int
    value: bool
    previous: bool

    def apply(self, session) -> None:
        session.marks.counted[self.nucleus_id] = self.value

    def revert(self, session) -> None:
        session.marks.counted[self.nucleus_id] = self.previous


@dataclass(frozen=True)
class SetPositive:
    marker: str
    nucleus_id: int
    value: bool
    previous: bool

    def apply(self, session) -> None:
        session.marks.positive[self.marker][self.nucleus_id] = self.value

    def revert(self, session) -> None:
        session.marks.positive[self.marker][self.nucleus_id] = self.previous


@dataclass(frozen=True, eq=False)
class AddNucleus:
    """手で作った円い核。測った値ごと持つので、やり直しても測り直さない。"""

    nucleus: Nucleus
    pixels: tuple[np.ndarray, np.ndarray]
    values: dict[str, float]
    auto: dict[str, bool]

    def apply(self, session) -> None:
        session.insert_nucleus(self)

    def revert(self, session) -> None:
        session.delete_nucleus(self)


class History:
    """1 回のクリックで起きた変更をひとまとめにして、元に戻す・やり直す。"""

    def __init__(self) -> None:
        self._done: list[tuple] = []
        self._undone: list[tuple] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)

    def run(self, edits: list, session) -> None:
        for edit in edits:
            edit.apply(session)
        self._done.append(tuple(edits))
        del self._done[:-HISTORY_LIMIT]
        self._undone.clear()

    def undo(self, session) -> bool:
        if not self._done:
            return False
        step = self._done.pop()
        for edit in reversed(step):
            edit.revert(session)
        self._undone.append(step)
        return True

    def redo(self, session) -> bool:
        if not self._undone:
            return False
        step = self._undone.pop()
        for edit in step:
            edit.apply(session)
        self._done.append(step)
        return True

    def clear(self) -> None:
        self._done.clear()
        self._undone.clear()
