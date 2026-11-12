"""階調の診断（飽和・ダイナミックレンジ不足）。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

LOW_FRACTION = 0.25
HIGH_FRACTION = 0.90


@dataclass
class ChannelQuality:
    p99: float
    p99_fraction: float
    saturated_fraction: float


def full_scale(bits: int) -> float:
    return float(2 ** bits - 1)


def assess(image: np.ndarray, bits: int) -> ChannelQuality:
    full = full_scale(bits)
    p99 = float(np.percentile(image, 99))
    return ChannelQuality(p99, p99 / full, float((image >= full).mean()))


def quality_warning(label: str, quality: ChannelQuality) -> str | None:
    percent = quality.p99_fraction * 100
    if quality.p99_fraction < LOW_FRACTION:
        return (f"{label}: 明るさの 99 パーセンタイルが全階調の {percent:.0f}% しかありません。"
                "階調が足りないため、陽性率は暫定値です。")
    if quality.p99_fraction > HIGH_FRACTION:
        return (f"{label}: 明るさの 99 パーセンタイルが全階調の {percent:.0f}% に達しています"
                f"（飽和した画素 {quality.saturated_fraction * 100:.1f}%）。陽性率は暫定値です。")
    return None
