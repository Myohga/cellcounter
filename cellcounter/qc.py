"""核の特徴量と、ゴミの自動除外。"""

from __future__ import annotations

import numpy as np
from skimage import measure

from .model import Nucleus
from .settings import QcSettings

TOO_SMALL = "面積が小さすぎる"
TOO_LARGE = "面積が大きすぎる"
JAGGED = "形がいびつ"
ELONGATED = "細長すぎる"
LOW_CONFIDENCE = "Cellpose の確信度が低い"
DIM = "DAPI が暗すぎる"
SATURATED = "飽和してのっぺりしている"
ON_BORDER = "画像の端にかかる"


def describe_nuclei(labels: np.ndarray, dapi: np.ndarray, cellprob: np.ndarray | None,
                    background: np.ndarray, full: float,
                    settings: QcSettings) -> tuple[dict[int, Nucleus], list[str]]:
    """検出した核を 1 つずつ測り、除外する理由を付ける。理由が空の核を数える。"""
    corrected = dapi.astype(np.float32) - background
    height, width = labels.shape
    rows = []
    for region in measure.regionprops(labels):
        ys, xs = region.coords[:, 0], region.coords[:, 1]
        top, left, bottom, right = region.bbox
        rows.append({
            "id": int(region.label),
            "y": float(region.centroid[0]),
            "x": float(region.centroid[1]),
            "area": int(region.area),
            "solidity": float(region.solidity),
            "eccentricity": float(region.eccentricity),
            "brightness": float(np.percentile(corrected[ys, xs], 75)),
            "saturated": float((dapi[ys, xs] >= full).mean()),
            "confidence": float(cellprob[ys, xs].mean()) if cellprob is not None else None,
            "on_border": top == 0 or left == 0 or bottom == height or right == width,
        })

    notes = []
    median_area = float(np.median([row["area"] for row in rows]))
    median_brightness = float(np.median([row["brightness"] for row in rows]))
    if median_brightness <= 0:
        notes.append("DAPI が背景と区別できないほど暗いため、「DAPI が暗すぎる」の基準は使っていません。")
    confidence_cut = None
    if cellprob is None:
        notes.append("Cellpose の確信度が得られなかったため、確信度による除外は行っていません。")
    else:
        confidence_cut = float(np.percentile([row["confidence"] for row in rows],
                                             settings.min_cellprob_percentile))

    nuclei = {}
    for row in rows:
        checks = (
            (TOO_SMALL, row["area"] < median_area * settings.min_area_ratio),
            (TOO_LARGE, row["area"] > median_area * settings.max_area_ratio),
            (JAGGED, row["solidity"] < settings.min_solidity),
            (ELONGATED, row["eccentricity"] > settings.max_eccentricity),
            (LOW_CONFIDENCE, confidence_cut is not None and row["confidence"] < confidence_cut),
            (DIM, median_brightness > 0
             and row["brightness"] / median_brightness < settings.min_dapi_relative),
            (SATURATED, row["saturated"] > settings.max_saturated_fraction),
            (ON_BORDER, settings.exclude_border and row["on_border"]),
        )
        nuclei[row["id"]] = Nucleus(
            id=row["id"], y=row["y"], x=row["x"], area_px=row["area"],
            qc_reasons=tuple(reason for reason, hit in checks if hit))
    return nuclei, notes


def pan_channel_ids(signals: list[np.ndarray], ids: np.ndarray, percentile: float) -> set[int]:
    """判定するすべてのチャンネルで集団の上位に入る核（自家蛍光の疑い）。除外はしない。"""
    if len(signals) < 2:
        return set()
    bright = np.ones(len(ids), dtype=bool)
    for signal in signals:
        bright &= signal > np.nanpercentile(signal, percentile)
    return {int(nucleus_id) for nucleus_id in ids[bright]}
