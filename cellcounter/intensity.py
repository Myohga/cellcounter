"""平均蛍光強度（ZEN の Measure に出る Intensity Mean Value）。測る範囲の形と、範囲の中の明るさ。

ZEN と同じく、範囲の中の画素の明るさをそのまま平均する（背景は引かない）。
範囲が 1 つも無いときは画像全体を測る。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage.draw import polygon2mask
from skimage.measure import points_in_poly

SHAPE_LABELS = {"rectangle": "四角形", "ellipse": "円・楕円", "polygon": "多角形・フリーハンド"}
WHOLE_IMAGE = "画像全体"
ALL_REGIONS = "すべての範囲（重なりは 1 回）"
_CORNERS = 4
_ELLIPSE_SEGMENTS = 128


@dataclass(frozen=True)
class Region:
    """測る範囲 1 つ。points は画素の (y, x)。

    四角形と楕円は、外接する四角形の 4 つの角（napari の図形と同じ持ち方。回してあってもよい）。
    多角形は頂点を順に並べたもの。
    """

    shape: str
    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if self.shape not in SHAPE_LABELS:
            raise ValueError(f"範囲の形の指定が不正です: '{self.shape}'（{' / '.join(SHAPE_LABELS)}）")
        if self.shape == "polygon" and len(self.points) < 3:
            raise ValueError("多角形の範囲には、頂点が 3 つ以上要ります。")
        if self.shape != "polygon" and len(self.points) != _CORNERS:
            raise ValueError(f"{SHAPE_LABELS[self.shape]}の範囲は、4 つの角で表します。")

    @classmethod
    def of(cls, shape: str, points) -> Region:
        """配列から作る。3 次元以上の座標なら、最後の 2 つ（y, x）を使う。"""
        array = np.asarray(points, dtype=float)[:, -2:]
        return cls(shape, tuple((round(float(y), 3), round(float(x), 3)) for y, x in array))

    @property
    def label(self) -> str:
        return SHAPE_LABELS[self.shape]

    def _ellipse_axes(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """中心と、半径の向きと長さを持つ 2 本の軸（napari の楕円と同じ決め方）。"""
        corners = np.array(self.points)
        center = corners.mean(axis=0)
        return center, (corners[1] - corners[0]) / 2.0, (corners[2] - corners[1]) / 2.0

    def outline(self) -> np.ndarray:
        """縁をなぞる多角形の頂点 (N, 2)。確認用画像に線を描くのに使う。"""
        if self.shape != "ellipse":
            return np.array(self.points)
        center, first, second = self._ellipse_axes()
        angle = np.linspace(0.0, 2.0 * np.pi, _ELLIPSE_SEGMENTS, endpoint=False)[:, None]
        return center + np.cos(angle) * first + np.sin(angle) * second

    def contains(self, points: np.ndarray) -> np.ndarray:
        """(N, 2) の (y, x) が範囲の中にあるか。"""
        points = np.asarray(points, dtype=float).reshape(-1, 2)
        if not len(points):
            return np.zeros(0, bool)
        if self.shape == "ellipse":
            return self._in_ellipse(points)
        return points_in_poly(points, np.array(self.points))

    def _in_ellipse(self, points: np.ndarray) -> np.ndarray:
        center, first, second = self._ellipse_axes()
        axes = np.stack([first, second])
        if abs(np.linalg.det(axes)) < 1e-9:
            return np.zeros(len(points), bool)
        # 点 = 中心 + a・軸1 + b・軸2 と書いたとき、a² + b² ≤ 1 なら中
        local = (points - center) @ np.linalg.inv(axes)
        return (local ** 2).sum(axis=1) <= 1.0

    def mask(self, shape: tuple[int, int]) -> np.ndarray:
        """画像の大きさの真偽値の配列。画素の中心が範囲の中（縁を含む）なら True。"""
        if self.shape != "ellipse":
            return polygon2mask(shape, np.array(self.points))
        result = np.zeros(shape, bool)
        outline = self.outline()
        top, left = np.maximum(np.floor(outline.min(axis=0)).astype(int), 0)
        bottom, right = np.minimum(np.ceil(outline.max(axis=0)).astype(int) + 1, shape)
        if top >= bottom or left >= right:
            return result
        ys, xs = np.mgrid[top:bottom, left:right]
        inside = self._in_ellipse(np.column_stack([ys.ravel(), xs.ravel()]))
        result[top:bottom, left:right] = inside.reshape(ys.shape)
        return result

    def bounds(self) -> str:
        """外接する四角形（画素）。Excel で位置の見当を付けるため。"""
        outline = self.outline()
        (top, left), (bottom, right) = outline.min(axis=0), outline.max(axis=0)
        return f"x {left:.0f}–{right:.0f}, y {top:.0f}–{bottom:.0f}"


def same_regions(first: list[Region | None], second: list[Region | None],
                 tolerance_px: float = 0.01) -> bool:
    """同じ範囲の並びか。napari は座標を 32 ビットの小数で持つので、ごくわずかな違いは同じとみなす。"""
    if len(first) != len(second):
        return False
    for one, other in zip(first, second):
        if one is None or other is None:
            if one is not other:
                return False
        elif one.shape != other.shape or len(one.points) != len(other.points) or not np.allclose(
                one.points, other.points, rtol=0.0, atol=tolerance_px):
            return False
    return True


@dataclass(frozen=True)
class ChannelStats:
    """1 チャンネル分の、範囲の中の明るさ（ZEN の Intensity Mean / Std Dev / Minimum / Maximum）。"""

    mean: float
    sd: float
    minimum: float
    maximum: float


@dataclass
class IntensityRow:
    """範囲 1 つ分の結果。stats はチャンネル番号 → 明るさ。nuclei は判定前なら None。"""

    name: str
    shape: str
    area_px: int
    area_um2: float
    nuclei: int | None
    bounds: str
    stats: dict[int, ChannelStats]


def channel_stats(planes: np.ndarray, channels: list[int],
                  mask: np.ndarray | None) -> dict[int, ChannelStats]:
    """mask が None なら画像全体。範囲に画素が 1 つも無ければ nan。"""
    stats = {}
    for index in channels:
        values = planes[index] if mask is None else planes[index][mask]
        if values.size == 0:
            stats[index] = ChannelStats(np.nan, np.nan, np.nan, np.nan)
            continue
        values = values.astype(np.float64, copy=False)
        stats[index] = ChannelStats(float(values.mean()), float(values.std()),
                                    float(values.min()), float(values.max()))
    return stats


def union_mask(regions: list[Region], shape: tuple[int, int]) -> np.ndarray:
    combined = np.zeros(shape, bool)
    for region in regions:
        combined |= region.mask(shape)
    return combined
