"""Cellpose-SAM による核の検出。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from .settings import DetectionSettings


COARSE_UM_PER_PX = 0.45
RESAMPLED_UM_PER_PX = 0.3
CELLPOSE_DIAMETER_PX = 30.0


@dataclass
class Segmentation:
    labels: np.ndarray
    cellprob: np.ndarray | None
    notes: list[str] = field(default_factory=list)


def display_clip(image: np.ndarray, black: float, white: float, full: float) -> np.ndarray:
    """ZEN の表示 Black / White と同じ線形クリップ。0〜1 の float を返す。"""
    if not 0.0 <= black < white <= 1.0:
        raise ValueError(f"表示クリップは 0 ≤ Black < White ≤ 1 にしてください"
                         f"（Black={black}, White={white}）。")
    low, high = black * full, white * full
    return np.clip((image.astype(np.float32) - low) / (high - low), 0.0, 1.0)


@lru_cache(maxsize=2)
def _model(gpu: bool):
    from cellpose import models

    return models.CellposeModel(gpu=gpu)


def cellpose_diameter(settings: DetectionSettings,
                      um_per_px: float | None) -> tuple[float | None, str | None]:
    """Cellpose に渡す核の直径（px）。None は「拡大・縮小せずにそのまま検出」。

    Cellpose は「直径が 30 px になるように」画像を拡大・縮小してから検出する。
    直径の指定が無くても、画素が粗い画像（タイル撮影など）は核が数 px しか無く、
    そのままではほとんど検出できないので、0.3 µm/px 相当まで拡大する。
    実画像（0.73 µm/px、1 枚）で、検出数が 169 個から 692 個に増えた。
    """
    if settings.nucleus_diameter_um:
        if not um_per_px:
            raise ValueError("µm/px が分からないため、核直径を µm で指定できません。")
        return settings.nucleus_diameter_um / um_per_px, None
    if um_per_px and um_per_px > COARSE_UM_PER_PX:
        factor = um_per_px / RESAMPLED_UM_PER_PX
        return CELLPOSE_DIAMETER_PX / factor, (
            f"画素が粗い（{um_per_px:.2f} µm/px）ため、{factor:.1f} 倍に拡大して核を検出しました。"
            "核がうまく拾えないときは、「核の直径」を指定するか、対物・ズームを上げて撮影してください。")
    return None, None


def segment_nuclei(dapi: np.ndarray, settings: DetectionSettings, um_per_px: float | None,
                   full: float) -> Segmentation:
    """DAPI から核を検出する。クリップは検出に渡すコピーにだけ掛かる。"""
    from cellpose import core

    notes = []
    gpu = settings.use_gpu and core.use_gpu()
    if settings.use_gpu and not gpu:
        notes.append("GPU が使えないため、CPU で核を検出しました（時間がかかります）。")

    diameter, note = cellpose_diameter(settings, um_per_px)
    if note:
        notes.append(note)

    clipped = display_clip(dapi, settings.clip_black, settings.clip_white, full)
    masks, flows, _ = _model(gpu).eval(
        clipped, normalize=True, diameter=diameter,
        cellprob_threshold=settings.cellprob_threshold,
        flow_threshold=settings.flow_threshold, min_size=settings.min_size)

    labels = np.asarray(masks, dtype=np.int32)
    cellprob = np.asarray(flows[2], dtype=np.float32) if len(flows) > 2 else None
    if cellprob is not None and cellprob.shape != labels.shape:
        cellprob = None
    return Segmentation(labels, cellprob, notes)
