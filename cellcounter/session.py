"""1 枚の画像についての作業状態（核・判定・× の状態）と、クリックの処理。"""

from __future__ import annotations

import numpy as np

from .channels import ChannelRow, ChannelTable
from .czi import LoadedImage
from .judge import MeasureInput, is_positive, measure
from .marks import AddNucleus, History, Marks, SetCounted, SetPositive
from .markers import LOCATION_SPECS
from .model import ControlData, Judgement, Nucleus
from .quality import full_scale
from .rois import Geometry, free_circle, local_background, window_around
from .settings import Settings

TAB_DAPI = "DAPI のみ"


def tab_name(marker: str | None) -> str:
    return TAB_DAPI if marker is None else f"DAPI＋{marker}"


class Session:
    def __init__(self, image: LoadedImage, table: ChannelTable, settings: Settings) -> None:
        self.image = image
        self.table = table
        self.settings = settings
        self.labels: np.ndarray | None = None
        self.nuclei: dict[int, Nucleus] = {}
        self.diameter_px = 0.0
        self.judgements: dict[str, Judgement] = {}
        self.marks = Marks()
        self.history = History()
        self.control: ControlData | None = None
        self.warnings: list[str] = list(image.warnings)
        self.dirty = False
        self.contrast: dict[int, tuple[float, float]] = {}
        self._backgrounds: dict[int, np.ndarray] = {}

    @property
    def um_per_px(self) -> float:
        if not self.image.meta.um_per_px:
            raise ValueError("µm/px がメタデータにありません。値を指定してください。")
        return self.image.meta.um_per_px

    @property
    def bits(self) -> int:
        return self.image.meta.bits

    @property
    def provisional(self) -> bool:
        return any(judgement.provisional for judgement in self.judgements.values())

    def add_warnings(self, warnings: list[str]) -> None:
        self.warnings.extend(text for text in warnings if text not in self.warnings)

    def reset_detection(self, labels: np.ndarray, nuclei: dict[int, Nucleus],
                        diameter_px: float) -> None:
        self.labels, self.nuclei, self.diameter_px = labels, nuclei, diameter_px
        self.judgements = {}
        self.marks = Marks()
        self.marks.set_counted({i: not n.qc_reasons for i, n in nuclei.items()})
        self.history.clear()
        self._backgrounds = {}

    def background(self, channel_index: int) -> np.ndarray:
        if channel_index not in self._backgrounds:
            self._backgrounds[channel_index] = local_background(
                self.image.planes[channel_index], self.diameter_px,
                self.settings.judge.background_radius_factor)
        return self._backgrounds[channel_index]

    def contrast_limits(self, channel_index: int) -> tuple[float, float]:
        """表示の黒点と白点。利用者が決めていなければ 0 〜 99.9 パーセンタイル。"""
        if channel_index not in self.contrast:
            high = float(np.percentile(self.image.planes[channel_index], 99.9))
            self.contrast[channel_index] = (0.0, max(high, 1.0))
        return self.contrast[channel_index]

    def measure_input(self, row: ChannelRow, geometry: Geometry,
                      window: tuple[slice, slice] = (slice(None), slice(None))) -> MeasureInput:
        """window を渡すと、その範囲だけを測る材料を作る（geometry も同じ範囲のもの）。"""
        pseudo = full_scale(self.bits) * self.settings.judge.pseudo_fraction
        return MeasureInput(self.image.planes[row.index][window],
                            self.background(row.index)[window], geometry, self.um_per_px, pseudo)

    def nucleus_at(self, y: float, x: float) -> int | None:
        """その位置の核。核の外でも、× のすぐ近くならその核とみなす。"""
        row, column = int(round(y)), int(round(x))
        height, width = self.labels.shape
        if not (0 <= row < height and 0 <= column < width):
            raise ValueError("画像の外です。")
        under = int(self.labels[row, column])
        if under:
            return under
        reach = max(3.0, 0.15 * self.diameter_px)
        near = [(np.hypot(n.y - y, n.x - x), n.id) for n in self.nuclei.values()]
        distance, nucleus_id = min(near, default=(np.inf, None))
        return nucleus_id if distance <= reach else None

    def click(self, marker: str | None, y: float, x: float) -> str:
        """組み合わせのタブ（marker が None なら「DAPI のみ」）でのクリック 1 回分。"""
        if self.labels is None:
            raise RuntimeError("先に核を検出してください。")
        if marker is not None and marker not in self.judgements:
            raise KeyError(f"マーカー {marker} は判定されていません。")

        nucleus_id = self.nucleus_at(y, x)
        if nucleus_id is None:
            created = self._circle_nucleus(y, x)
            nucleus_id = created.nucleus.id
            edits = [created]
            if marker is not None and not created.auto[marker]:
                edits.append(SetPositive(marker, nucleus_id, True, False))
            message = f"核 {nucleus_id} を作りました"
        elif marker is None:
            counted = self.marks.counted[nucleus_id]
            edits = [SetCounted(nucleus_id, not counted, counted)]
            message = f"核 {nucleus_id} を" + ("数えません" if counted else "数えます")
        elif not self.marks.counted[nucleus_id]:
            edits = [SetCounted(nucleus_id, True, False)]
            if not self.marks.positive[marker][nucleus_id]:
                edits.append(SetPositive(marker, nucleus_id, True, False))
            message = f"核 {nucleus_id} を数え、{marker} 陽性にしました"
        else:
            positive = self.marks.positive[marker][nucleus_id]
            edits = [SetPositive(marker, nucleus_id, not positive, positive)]
            message = f"核 {nucleus_id} を {marker} " + ("陰性" if positive else "陽性") + "にしました"

        self.history.run(edits, self)
        self.dirty = True
        return message

    def undo(self) -> bool:
        changed = self.history.undo(self)
        self.dirty = self.dirty or changed
        return changed

    def redo(self) -> bool:
        changed = self.history.redo(self)
        self.dirty = self.dirty or changed
        return changed

    def _reach_px(self) -> int:
        judge = self.settings.judge
        reach_um = max([judge.ring_gap_um + judge.ring_width_um,
                        *(spec.area.reach_um for spec in LOCATION_SPECS.values() if spec.area)])
        return int(np.ceil(reach_um / self.um_per_px)) + 1

    def _circle_nucleus(self, y: float, x: float) -> AddNucleus:
        """標準の大きさの円い核を作り、判定済みの各マーカーで測って判定する。"""
        ys, xs = free_circle(self.labels, y, x, self.diameter_px)
        nucleus_id = max(self.nuclei, default=0) + 1
        nucleus = Nucleus(nucleus_id, float(ys.mean()), float(xs.mean()), int(ys.size), manual=True)

        # 測る範囲の画素をどの核が取るかは、範囲のさらに外にある核にも左右される
        window = window_around(self.labels.shape, ys, xs, 2 * self._reach_px())
        labels = self.labels[window].copy()
        labels[ys - window[0].start, xs - window[1].start] = nucleus_id
        geometry = Geometry(labels)

        values, auto = {}, {}
        for marker, judgement in self.judgements.items():
            row = self.table.row(judgement.channel_index)
            inp = self.measure_input(row, geometry, window)
            value = float(measure(judgement.location, judgement.rule, inp,
                                  np.array([nucleus_id]), self.settings.judge)[0])
            values[marker] = value
            auto[marker] = is_positive(value, judgement.threshold)
        return AddNucleus(nucleus, (ys, xs), values, auto)

    def insert_nucleus(self, edit: AddNucleus) -> None:
        nucleus_id = edit.nucleus.id
        self.labels[edit.pixels] = nucleus_id
        self.nuclei[nucleus_id] = edit.nucleus
        self.marks.counted_auto[nucleus_id] = False
        self.marks.counted[nucleus_id] = True
        for marker, judgement in self.judgements.items():
            judgement.values[nucleus_id] = edit.values[marker]
            judgement.auto[nucleus_id] = edit.auto[marker]
            self.marks.positive_auto[marker][nucleus_id] = edit.auto[marker]
            self.marks.positive[marker][nucleus_id] = edit.auto[marker]

    def delete_nucleus(self, edit: AddNucleus) -> None:
        nucleus_id = edit.nucleus.id
        self.labels[edit.pixels] = 0
        del self.nuclei[nucleus_id]
        del self.marks.counted_auto[nucleus_id], self.marks.counted[nucleus_id]
        for marker, judgement in self.judgements.items():
            del judgement.values[nucleus_id], judgement.auto[nucleus_id]
            del self.marks.positive_auto[marker][nucleus_id]
            del self.marks.positive[marker][nucleus_id]
