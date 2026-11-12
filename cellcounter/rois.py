"""核の周りの範囲・局所背景・手で作る円い核。"""

from __future__ import annotations

from functools import cached_property

import cv2
import numpy as np
from scipy import ndimage as ndi


class Geometry:
    """ラベル画像から、各画素の「いちばん近い核」とそこまでの距離を引けるようにする。"""

    def __init__(self, labels: np.ndarray) -> None:
        self.labels = labels

    @cached_property
    def _nearest(self) -> tuple[np.ndarray, np.ndarray]:
        distance, index = ndi.distance_transform_edt(self.labels == 0, return_indices=True)
        return distance, self.labels[index[0], index[1]]

    def band(self, inner_px: float, outer_px: float) -> np.ndarray:
        """核の縁からの距離が inner より大きく outer 以下の画素を、いちばん近い核に割り当てる。

        核の中は距離 0 なので、inner を負にすると核そのものも含む。
        どの核からも inner 以内の画素は除かれるので、隣の核とそのにじみは入らない。
        """
        distance, nearest = self._nearest
        return np.where((distance > inner_px) & (distance <= outer_px), nearest, 0)


def _disk(radius_px: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius_px + 1,) * 2)


def local_background(image: np.ndarray, nucleus_diameter_px: float,
                     radius_factor: float) -> np.ndarray:
    """核より十分大きい範囲でならした背景。細胞が密で空き地が無い画像でも使える。"""
    radius = max(5, round(nucleus_diameter_px * radius_factor))
    opened = cv2.morphologyEx(image.astype(np.float32), cv2.MORPH_OPEN, _disk(radius))
    return cv2.GaussianBlur(opened, (0, 0), sigmaX=radius / 2.0)


def tophat(image: np.ndarray, radius_px: int) -> np.ndarray:
    """radius より小さい輝点だけを残す（点状のマーカー用）。"""
    return cv2.morphologyEx(image.astype(np.float32), cv2.MORPH_TOPHAT, _disk(radius_px))


def standard_diameter(labels: np.ndarray) -> float:
    """検出した核の直径（同じ面積の円に直したもの）の中央値。"""
    areas = np.bincount(labels.ravel())[1:]
    areas = areas[areas > 0]
    if areas.size == 0:
        raise ValueError("核が 1 つもありません。")
    return float(2.0 * np.sqrt(np.median(areas) / np.pi))


def free_circle(labels: np.ndarray, y: float, x: float,
                diameter_px: float) -> tuple[np.ndarray, np.ndarray]:
    """(y, x) を中心とする円のうち、まだどの核にも属していない画素の座標。"""
    radius = diameter_px / 2.0
    top, left = max(0, int(y - radius)), max(0, int(x - radius))
    bottom = min(labels.shape[0], int(y + radius) + 2)
    right = min(labels.shape[1], int(x + radius) + 2)
    ys, xs = np.mgrid[top:bottom, left:right]
    inside = ((ys - y) ** 2 + (xs - x) ** 2 <= radius ** 2) & (labels[top:bottom, left:right] == 0)
    return ys[inside], xs[inside]


def window_around(shape: tuple[int, int], ys: np.ndarray, xs: np.ndarray,
                  margin_px: int) -> tuple[slice, slice]:
    return (slice(max(0, int(ys.min()) - margin_px), min(shape[0], int(ys.max()) + margin_px + 1)),
            slice(max(0, int(xs.min()) - margin_px), min(shape[1], int(xs.max()) + margin_px + 1)))
