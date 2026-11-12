"""陰性対照の .czi から、細胞ごとの値を集める。"""

from __future__ import annotations

import os
from typing import Callable

import numpy as np

from .czi import LoadedImage, read_scene
from .judge import MeasureInput, measure
from .metadata import compare_acquisition
from .model import ControlData
from .pipeline import Segmenter, detect_nuclei
from .rois import Geometry
from .segment import segment_nuclei
from .session import Session

Loader = Callable[[str, int, str], LoadedImage]


def collect_control(session: Session, sources: list[tuple[str, int]],
                    segmenter: Segmenter = segment_nuclei,
                    loader: Loader = read_scene) -> ControlData:
    """実験画像と同じ設定で対照を検出・測定し、QC を通った細胞の値を合計する。

    sources は (ファイル, シーン番号) の並び。読めない対照があれば例外にする。
    """
    if not sources:
        raise ValueError("陰性対照のファイルが指定されていません。")
    rows = session.table.judged()
    settings = session.settings
    values: dict[str, list[float]] = {row.marker: [] for row in rows}
    files, warnings, n_cells = [], [], 0

    for path, scene in sources:
        image = loader(path, scene, settings.z_projection)
        name = f"{os.path.basename(path)}（シーン {scene}）"
        ours = [channel.name for channel in session.image.meta.channels]
        theirs = [channel.name for channel in image.meta.channels]
        if ours != theirs:
            raise ValueError(f"陰性対照 {name} はチャンネルの構成が実験画像と違います"
                             f"（実験 {ours} / 対照 {theirs}）。")
        if not image.meta.um_per_px:
            raise ValueError(f"陰性対照 {name} の µm/px がメタデータにありません。")
        warnings += compare_acquisition(session.image.meta, image.meta, name)

        detection = detect_nuclei(image.planes, session.table.dapi.index, image.meta.um_per_px,
                                  image.meta.bits, settings, segmenter)
        ids = np.array([n.id for n in detection.nuclei.values() if not n.qc_reasons])
        if ids.size == 0:
            raise ValueError(f"陰性対照 {name} に、数えられる核がありません。")
        geometry = Geometry(detection.labels)
        for row in rows:
            inp = MeasureInput.build(image.planes[row.index], geometry, detection.diameter_px,
                                     image.meta.um_per_px, image.meta.bits, settings.judge)
            values[row.marker] += measure(row.location, "control_percentile", inp, ids,
                                          settings.judge).tolist()
        files.append(name)
        n_cells += int(ids.size)

    return ControlData(files, n_cells, values, warnings)
