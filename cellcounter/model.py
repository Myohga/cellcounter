"""モジュール間で受け渡すデータの形。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Nucleus:
    id: int
    y: float
    x: float
    area_px: int
    manual: bool = False
    qc_reasons: tuple[str, ...] = ()
    pan_channel: bool = False


@dataclass
class Judgement:
    """マーカー 1 つ分の自動判定。values の nan は「判定不能」。"""

    marker: str
    channel_index: int
    location: str
    rule: str
    threshold: float
    provisional: bool
    detail: dict[str, str]
    values: dict[int, float] = field(default_factory=dict)
    auto: dict[int, bool] = field(default_factory=dict)


@dataclass
class ControlData:
    """陰性対照の細胞ごとの値（マーカー名ごと）。"""

    files: list[str]
    n_cells: int
    values: dict[str, list[float]]
    warnings: list[str] = field(default_factory=list)
    sources: list[tuple[str, int]] = field(default_factory=list)
