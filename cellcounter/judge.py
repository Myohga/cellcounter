"""陽性判定。測り方と閾値の決め方は、このファイルの 2 つの表だけで決まる。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy import ndimage as ndi

from .channels import ChannelRow
from .markers import AreaSpec, LocationSpec, location_spec
from .model import Judgement
from .quality import full_scale
from .rois import Geometry, local_background, tophat
from .settings import JudgeSettings

_WHOLE_CELL = AreaSpec(include_nucleus=True, reach_um=3.0, percentile=75.0)


@dataclass
class MeasureInput:
    """1 チャンネルを測るための材料。"""

    image: np.ndarray
    background: np.ndarray
    geometry: Geometry
    um_per_px: float
    pseudo: float

    @classmethod
    def build(cls, image: np.ndarray, geometry: Geometry, diameter_px: float,
              um_per_px: float, bits: int, settings: JudgeSettings) -> MeasureInput:
        background = local_background(image, diameter_px, settings.background_radius_factor)
        return cls(image, background, geometry, um_per_px,
                   full_scale(bits) * settings.pseudo_fraction)


def _sums(label_map: np.ndarray, image: np.ndarray,
          ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """核ごとの、明るさの合計と画素数。"""
    size = int(max(label_map.max(), ids.max())) + 1
    flat = label_map.ravel()
    counts = np.bincount(flat, minlength=size)[ids]
    totals = np.bincount(flat, weights=image.ravel().astype(np.float64), minlength=size)[ids]
    return totals, counts


def _nuclear_ratio(inp: MeasureInput, spec: LocationSpec, ids: np.ndarray,
                   settings: JudgeSettings) -> np.ndarray:
    """(核内の平均 + c) ÷ (すぐ外側のリングの平均 + c)。リングが取れない核は nan。"""
    gap = max(1, round(settings.ring_gap_um / inp.um_per_px))
    width = max(3, round(settings.ring_width_um / inp.um_per_px))
    inside, inside_n = _sums(inp.geometry.labels, inp.image, ids)
    ring, ring_n = _sums(inp.geometry.band(gap, gap + width), inp.image, ids)
    usable = (inside_n > 0) & (ring_n >= settings.min_roi_px)
    ratio = np.full(len(ids), np.nan)
    ratio[usable] = ((inside[usable] / inside_n[usable] + inp.pseudo)
                     / (ring[usable] / ring_n[usable] + inp.pseudo))
    return ratio


def _signal(inp: MeasureInput, area: AreaSpec) -> np.ndarray:
    signal = inp.image.astype(np.float32) - inp.background
    if area.tophat_um:
        signal = tophat(signal, max(1, round(area.tophat_um / inp.um_per_px)))
    return signal


def area_percentile(inp: MeasureInput, area: AreaSpec, ids: np.ndarray, settings: JudgeSettings,
                    quantity: np.ndarray) -> np.ndarray:
    """核の周りの範囲で quantity の分位を取る。範囲が小さすぎる核は nan。"""
    reach = max(1, round(area.reach_um / inp.um_per_px))
    region = inp.geometry.band(-1 if area.include_nucleus else 0, reach)

    def pick(values: np.ndarray) -> float:
        if values.size < settings.min_roi_px:
            return np.nan
        return float(np.percentile(values, area.percentile))

    return ndi.labeled_comprehension(quantity, region, ids, pick, float, np.nan)


def _area_signal(inp: MeasureInput, spec: LocationSpec, ids: np.ndarray,
                 settings: JudgeSettings) -> np.ndarray:
    """背景を引いた明るさの分位（陰性対照の同じ値と比べる）。"""
    return area_percentile(inp, spec.area, ids, settings, _signal(inp, spec.area))


def _area_background_ratio(inp: MeasureInput, spec: LocationSpec, ids: np.ndarray,
                           settings: JudgeSettings) -> np.ndarray:
    """局所背景に対する明るさの比の分位（固定値と比べる）。"""
    ratio = 1.0 + _signal(inp, spec.area) / (inp.background + inp.pseudo)
    return area_percentile(inp, spec.area, ids, settings, ratio)


def cell_brightness(inp: MeasureInput, ids: np.ndarray, settings: JudgeSettings) -> np.ndarray:
    """染まる場所によらない細胞全体の明るさ（全チャンネルで明るい核を見つけるのに使う）。"""
    return area_percentile(inp, _WHOLE_CELL, ids, settings, _signal(inp, _WHOLE_CELL))


Measure = Callable[[MeasureInput, LocationSpec, np.ndarray, JudgeSettings], np.ndarray]
MEASURES: dict[str, Measure] = {
    "nuclear_ratio": _nuclear_ratio,
    "area_signal": _area_signal,
    "area_background_ratio": _area_background_ratio,
}


@dataclass
class Decision:
    threshold: float
    detail: dict[str, str]
    warnings: list[str]


def _control_percentile(spec: LocationSpec, settings: JudgeSettings,
                        control_values: list[float] | None) -> Decision:
    if control_values is None:
        raise ValueError("陰性対照の値がありません。")
    values = np.asarray(control_values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("陰性対照に、測定できた細胞が 1 つもありません。")
    threshold = float(np.percentile(values, settings.control_percentile))

    warnings = []
    if values.size < settings.min_control_cells:
        warnings.append(f"陰性対照の細胞が {values.size} 個しかありません"
                        f"（目安 {settings.min_control_cells} 個以上）。閾値が不安定です。")
    if threshold <= float(np.median(values)):
        warnings.append("陰性対照の値がほとんど同じです（階調が足りません）。閾値が意味を持ちません。")
    detail = {"閾値の決め方": f"陰性対照の {settings.control_percentile:g} パーセンタイル",
              "陰性対照の細胞数": str(values.size)}
    return Decision(threshold, detail, warnings)


def _fixed(spec: LocationSpec, settings: JudgeSettings,
           control_values: list[float] | None) -> Decision:
    threshold = (settings.fixed_nuclear_ratio if spec.area is None
                 else settings.fixed_background_ratio)
    return Decision(threshold, {"閾値の決め方": "固定値（陰性対照なし・暫定）"}, [])


@dataclass(frozen=True)
class Rule:
    label: str
    area_measure: str
    provisional: bool
    decide: Callable[[LocationSpec, JudgeSettings, list[float] | None], Decision]


RULES: dict[str, Rule] = {
    "control_percentile": Rule("陰性対照", "area_signal", False, _control_percentile),
    "fixed": Rule("固定値", "area_background_ratio", True, _fixed),
}


def _rule(name: str) -> Rule:
    if name not in RULES:
        raise ValueError(f"未知の判定法です: '{name}'（{' / '.join(RULES)} のいずれか）")
    return RULES[name]


def _measure_name(spec: LocationSpec, rule: Rule) -> str:
    return "nuclear_ratio" if spec.area is None else rule.area_measure


def measure(location: str, rule_name: str, inp: MeasureInput, ids: np.ndarray,
            settings: JudgeSettings) -> np.ndarray:
    """核ごとの値を測る。未知の場所・判定法は例外。"""
    spec = location_spec(location)
    return MEASURES[_measure_name(spec, _rule(rule_name))](inp, spec, ids, settings)


def is_positive(value: float, threshold: float) -> bool:
    """閾値ちょうどは陰性。対照の値が同じ数に固まっていても、対照自身が陽性にならない。"""
    return bool(np.isfinite(value) and value > threshold)


def describe(location: str, rule_name: str, settings: JudgeSettings) -> str:
    """Settings シートに残す測り方の説明。"""
    spec, rule = location_spec(location), _rule(rule_name)
    if spec.area is None:
        return (f"核内の平均 ÷ 核のすぐ外側のリングの平均（縁から {settings.ring_gap_um:g} µm 空けて"
                f"幅 {settings.ring_width_um:g} µm、ほかの核の近くは除く）。"
                f"分子と分母に全階調の {settings.pseudo_fraction * 100:g}% を足す")
    area = spec.area
    where = "核とその外側" if area.include_nucleus else "核の外側"
    what = {"area_signal": "背景を引いた明るさ", "area_background_ratio": "局所背景に対する比"}
    text = (f"{where} {area.reach_um:g} µm の範囲で、{what[rule.area_measure]}の "
            f"{area.percentile:g} パーセンタイル（＝範囲内の画素の {area.min_fraction:g}% 超が"
            "閾値を超えれば陽性）")
    if area.tophat_um:
        text += f"。半径 {area.tophat_um:g} µm のトップハットで輝点を強調"
    return text


def judge_marker(row: ChannelRow, rule_name: str, inp: MeasureInput, ids: np.ndarray,
                 settings: JudgeSettings,
                 control_values: list[float] | None) -> tuple[Judgement, list[str]]:
    spec, rule = location_spec(row.location), _rule(rule_name)
    decision = rule.decide(spec, settings, control_values)
    values = measure(row.location, rule_name, inp, ids, settings)
    detail = {"測り方": describe(row.location, rule_name, settings), **decision.detail,
              "閾値": f"{decision.threshold:.4g}"}
    judgement = Judgement(
        marker=row.marker, channel_index=row.index, location=row.location, rule=rule_name,
        threshold=decision.threshold, provisional=rule.provisional, detail=detail,
        values={int(i): float(v) for i, v in zip(ids, values)},
        auto={int(i): is_positive(v, decision.threshold) for i, v in zip(ids, values)})
    return judgement, [f"{row.marker}: {text}" for text in decision.warnings]
