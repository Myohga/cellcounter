"""1 枚の画像についての作業状態（核・判定・× の状態）と、クリックの処理。"""

from __future__ import annotations

import numpy as np

from .channels import ChannelRow, ChannelTable
from .czi import LoadedImage
from .intensity import (ALL_REGIONS, WHOLE_IMAGE, ChannelStats, IntensityRow, Region,
                        channel_stats, union_mask)
from .judge import MeasureInput, is_positive, measure
from .marks import (ADDED, AddNucleus, History, Marks, SetBlind, SetCounted, SetPositive,
                    SetRegions)
from .markers import IMV_TAB_NAME, LOCATION_SPECS
from .model import ControlData, Judgement, Nucleus
from .quality import full_scale
from .rois import Geometry, free_circle, local_background, window_around
from .settings import Settings

TAB_DAPI = "DAPI のみ"
# 平均蛍光強度で測るマーカーは、まとめて 1 つのタブで範囲を描いて測る
IMV_TAB = IMV_TAB_NAME


def tab_name(marker: str | None) -> str:
    if marker is None:
        return TAB_DAPI
    return IMV_TAB if marker == IMV_TAB else f"DAPI＋{marker}"


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
        self.shown: dict[str, list[int]] = {}
        # 目視判定モード: 自動判定を隠して人が付けた判定（マーカー名 → 核 ID → 陽性か）
        self.blind_active = False
        self.blind: dict[str, dict[int, bool]] = {}
        # 平均蛍光強度: 判定したときに測ると決めていたマーカー（名前 → チャンネル）と、測る範囲
        self.imv_channels: dict[str, int] = {}
        self.regions: list[Region] = []
        self._backgrounds: dict[int, np.ndarray] = {}
        self._centroids: tuple[np.ndarray, np.ndarray] | None = None
        self._region_stats: dict[object, tuple[int, dict[int, ChannelStats]]] = {}

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
        self.blind_active, self.blind = False, {}
        self._backgrounds = {}
        self._centroids = None

    def background(self, channel_index: int) -> np.ndarray:
        if channel_index not in self._backgrounds:
            self._backgrounds[channel_index] = local_background(
                self.image.planes[channel_index], self.diameter_px,
                self.settings.judge.background_radius_factor)
        return self._backgrounds[channel_index]

    def marker_channel(self, marker: str) -> int:
        """マーカーが乗っているチャンネル。判定済みなら、判定したときのチャンネル。"""
        if marker in self.judgements:
            return self.judgements[marker].channel_index
        for row in self.table.judged():
            if row.marker == marker:
                return row.index
        raise KeyError(f"マーカー {marker} はチャンネル表にありません。")

    def imv_markers(self) -> dict[str, int]:
        """平均蛍光強度で測るマーカー。判定前は、チャンネル表で決めてあるもの。

        判定したあとは、判定したときのもの（チャンネル表を変えても、判定し直すまでは変えない）。
        """
        if self.imv_channels or self.labels is not None:
            return self.imv_channels
        return {row.marker: row.index for row in self.table.imv() if row.marker}

    def shown_channels(self, marker: str | None) -> list[int]:
        """その組み合わせで背景に出すチャンネル。選び直していなければ DAPI とそのマーカー。

        平均蛍光強度のタブでは、DAPI と、平均蛍光強度で測るマーカーすべて。
        """
        chosen = self.shown.get(tab_name(marker))
        if chosen is not None:
            return chosen
        default = [row.index for row in self.table.rows if row.role == "dapi"]
        if marker == IMV_TAB:
            default += [index for index in self.imv_markers().values() if index not in default]
        elif marker is not None:
            default.append(self.marker_channel(marker))
        return default

    def set_shown(self, marker: str | None, channel_index: int, visible: bool) -> None:
        chosen = [i for i in self.shown_channels(marker) if i != channel_index]
        self.shown[tab_name(marker)] = sorted([*chosen, channel_index] if visible else chosen)

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
        if self._centroids is None:
            self._centroids = (np.array(list(self.nuclei)),
                               np.array([(n.y, n.x) for n in self.nuclei.values()]).reshape(-1, 2))
        ids, points = self._centroids
        if not len(ids):
            return None
        distance = np.hypot(points[:, 0] - y, points[:, 1] - x)
        nearest = int(distance.argmin())
        return int(ids[nearest]) if distance[nearest] <= max(3.0, 0.15 * self.diameter_px) else None

    def category(self, marker: str | None, nucleus_id: int) -> str | None:
        """画面に出す × の種類。目視判定モードのマーカーのタブでは、人が付けた × だけを出す。"""
        if self.blind_active and marker is not None:
            marked = self.marks.counted[nucleus_id] and self.blind[marker].get(nucleus_id, False)
            return ADDED if marked else None
        return self.marks.category(marker, nucleus_id)

    def set_blind(self, active: bool) -> None:
        """目視判定モードの入り切り。付けた判定は、切っても残る（一致率の計算に使う）。"""
        self.blind_active = active
        if active:
            for marker in self.judgements:
                self.blind.setdefault(marker, {})

    def _blind_click(self, marker: str, nucleus_id: int | None) -> str:
        if nucleus_id is None or not self.marks.counted[nucleus_id]:
            return "目視判定モードでは、数える核だけをクリックできます。"
        marked = self.blind[marker].get(nucleus_id, False)
        self.history.run([SetBlind(marker, nucleus_id, not marked, marked)], self)
        self.dirty = True
        return f"核 {nucleus_id} を目視で {marker} " + ("陰性" if marked else "陽性") + "にしました"

    def click(self, marker: str | None, y: float, x: float) -> str:
        """組み合わせのタブ（marker が None なら「DAPI のみ」）でのクリック 1 回分。"""
        if self.labels is None:
            raise RuntimeError("先に核を検出してください。")
        if marker == IMV_TAB:
            raise ValueError("平均蛍光強度のタブでは、クリックで核を直せません。")
        if marker is not None and marker not in self.judgements:
            raise KeyError(f"マーカー {marker} は判定されていません。")

        nucleus_id = self.nucleus_at(y, x)
        if self.blind_active and marker is not None:
            return self._blind_click(marker, nucleus_id)
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

    # ---- 平均蛍光強度 -------------------------------------------------------

    def set_regions(self, regions: list[Region]) -> bool:
        """測る範囲を置き換える（元に戻せる）。変わらなければ何もせず False。"""
        regions = list(regions)
        if regions == self.regions:
            return False
        self.history.run([SetRegions(tuple(regions), tuple(self.regions))], self)
        self.dirty = True
        return True

    def intensity_channels(self) -> list[int]:
        """Excel に出すチャンネル。平均蛍光強度で測るマーカーを先に、ほかの蛍光チャンネルをあとに。"""
        first = list(self.imv_markers().values())
        rest = [row.index for row in self.table.rows if row.fluorescence and row.index not in first]
        return [*first, *rest]

    def _stats(self, key: object, mask_of) -> tuple[int, dict[int, ChannelStats]]:
        """範囲ごとの明るさは、画像が変わらないので一度測れば済む。"""
        if key not in self._region_stats:
            mask = mask_of()
            area = int(self.image.planes[0].size if mask is None else mask.sum())
            channels = [row.index for row in self.table.rows if row.fluorescence]
            self._region_stats[key] = (area, channel_stats(self.image.planes, channels, mask))
        return self._region_stats[key]

    def intensity(self) -> list[IntensityRow]:
        """範囲ごとの平均蛍光強度。範囲が無ければ画像全体。範囲が 2 つ以上なら、合わせた行も足す。"""
        shape = self.image.planes.shape[1:]
        pixel_um2 = self.um_per_px ** 2
        centroids = None
        if self.labels is not None:
            centroids = np.array([(n.y, n.x) for i, n in self.nuclei.items()
                                  if self.marks.counted.get(i)]).reshape(-1, 2)

        def row(name: str, shape_label: str, key: object, mask_of, inside, bounds: str):
            area, stats = self._stats(key, mask_of)
            nuclei = None if centroids is None else int(inside(centroids).sum())
            return IntensityRow(name, shape_label, area, round(area * pixel_um2, 2), nuclei,
                                bounds, stats)

        if not self.regions:
            return [row(WHOLE_IMAGE, "—", None, lambda: None,
                        lambda points: np.ones(len(points), bool),
                        f"x 0–{shape[1] - 1}, y 0–{shape[0] - 1}")]
        rows = [row(f"範囲 {number}", region.label, region,
                    lambda region=region: region.mask(shape), region.contains, region.bounds())
                for number, region in enumerate(self.regions, 1)]
        if len(self.regions) > 1:
            regions = tuple(self.regions)
            rows.append(row(ALL_REGIONS, "—", regions, lambda: union_mask(list(regions), shape),
                            lambda points: np.any([r.contains(points) for r in regions], axis=0),
                            "—"))
        return rows

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
        self._centroids = None
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
        self._centroids = None
        del self.marks.counted_auto[nucleus_id], self.marks.counted[nucleus_id]
        for marker, judgement in self.judgements.items():
            del judgement.values[nucleus_id], judgement.auto[nucleus_id]
            del self.marks.positive_auto[marker][nucleus_id]
            del self.marks.positive[marker][nucleus_id]
        for marked in self.blind.values():
            marked.pop(nucleus_id, None)
