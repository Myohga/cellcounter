"""Cellpose-SAM による核の検出。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from .settings import DetectionSettings


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


def segment_nuclei(dapi: np.ndarray, settings: DetectionSettings, um_per_px: float | None,
                   full: float) -> Segmentation:
    """DAPI から核を検出する。クリップは検出に渡すコピーにだけ掛かる。"""
    from cellpose import core

    notes = []
    gpu = settings.use_gpu and core.use_gpu()
    if settings.use_gpu and not gpu:
        notes.append("GPU が使えないため、CPU で核を検出しました（時間がかかります）。")

    diameter = None
    if settings.nucleus_diameter_um:
        if not um_per_px:
            raise ValueError("µm/px が分からないため、核直径を µm で指定できません。")
        diameter = settings.nucleus_diameter_um / um_per_px

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
