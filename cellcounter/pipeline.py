"""読み込み → 核の検出 → 判定 の流れ。CLI と GUI が同じ関数を呼ぶ。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .channels import ChannelTable
from .czi import LoadedImage
from .judge import cell_brightness, judge_marker
from .model import ControlData, Nucleus
from .qc import describe_nuclei, pan_channel_ids
from .quality import assess, full_scale, quality_warning
from .rois import Geometry, local_background, standard_diameter
from .segment import Segmentation, segment_nuclei
from .session import Session
from .settings import DetectionSettings, Settings

Segmenter = Callable[[np.ndarray, DetectionSettings, float | None, float], Segmentation]
UNDETERMINED_WARNING_FRACTION = 0.10


@dataclass
class Detection:
    labels: np.ndarray
    nuclei: dict[int, Nucleus]
    diameter_px: float
    notes: list[str]


def detect_nuclei(planes: np.ndarray, dapi_index: int, um_per_px: float | None, bits: int,
                  settings: Settings, segmenter: Segmenter) -> Detection:
    dapi = planes[dapi_index]
    full = full_scale(bits)
    result = segmenter(dapi, settings.detection, um_per_px, full)
    if result.labels.max() == 0:
        raise RuntimeError("核が 1 つも検出されませんでした。"
                           "DAPI のチャンネルとコントラストを確認してください。")
    diameter = standard_diameter(result.labels)
    background = local_background(dapi, diameter, settings.judge.background_radius_factor)
    nuclei, notes = describe_nuclei(result.labels, dapi, result.cellprob, background, full,
                                    settings.qc)
    return Detection(result.labels, nuclei, diameter, [*result.notes, *notes])


def open_session(image: LoadedImage, table: ChannelTable, settings: Settings) -> Session:
    """読み込んだ画像から作業を始める。階調の警告はここで出す。"""
    session = Session(image, table, settings)
    for row in table.rows:
        if row.fluorescence:
            quality = assess(image.planes[row.index], image.meta.bits)
            warning = quality_warning(row.marker or row.dye or row.name, quality)
            if warning:
                session.add_warnings([warning])
    return session


def run_detection(session: Session, segmenter: Segmenter = segment_nuclei) -> None:
    detection = detect_nuclei(session.image.planes, session.table.dapi.index,
                              session.image.meta.um_per_px, session.bits, session.settings,
                              segmenter)
    session.reset_detection(detection.labels, detection.nuclei, detection.diameter_px)
    session.add_warnings(detection.notes)


def run_judgement(session: Session, control: ControlData | None = None) -> None:
    """ON にしたマーカーを自動判定する。陰性対照が無ければ固定値で判定し、暫定とする。

    判定法を平均蛍光強度にしたマーカーは、陽性・陰性を決めない（範囲の明るさを測るだけ）。
    """
    if session.labels is None:
        raise RuntimeError("先に核を検出してください。")
    problems = session.table.problems()
    if problems:
        raise ValueError("チャンネル表に直すところがあります:\n" + "\n".join(problems))

    rule = "control_percentile" if control else "fixed"
    # QC で外れた核も測っておく。人が「数える」に変えたとき、判定がすぐ出せるように
    ids = np.array(sorted(session.nuclei))
    geometry = Geometry(session.labels)
    session.judgements = {}
    # 平均蛍光強度は範囲を描いたときに測るので、ここではどのマーカーを測るかだけを決める
    session.imv_channels = {row.marker: row.index for row in session.table.imv()}
    session.control = control
    session.history.clear()
    session.blind_active, session.blind = False, {}
    brightness = []
    for row in session.table.judged():
        inp = session.measure_input(row, geometry)
        values = control.values.get(row.marker) if control else None
        judgement, warnings = judge_marker(row, rule, inp, ids, session.settings.judge, values)
        session.judgements[row.marker] = judgement
        session.marks.set_judgement(row.marker, judgement.auto)
        session.add_warnings(warnings)
        brightness.append(cell_brightness(inp, ids, session.settings.judge))

        counted = [i for i in ids if session.marks.counted[int(i)]]
        undetermined = sum(not np.isfinite(judgement.values[int(i)]) for i in counted)
        if counted and undetermined / len(counted) > UNDETERMINED_WARNING_FRACTION:
            session.add_warnings([
                f"{row.marker}: 数える核 {len(counted)} 個のうち {undetermined} 個は、"
                "周りに測る場所が無く判定できませんでした（陰性として数えています）。"])

    flagged = pan_channel_ids(brightness, ids, session.settings.qc.pan_channel_percentile)
    for nucleus in session.nuclei.values():
        nucleus.pan_channel = nucleus.id in flagged
    if control:
        session.add_warnings(control.warnings)
