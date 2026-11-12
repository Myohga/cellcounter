"""検出・QC・判定の設定と既定値。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

Z_PROJECTIONS = ("max", "mean", "best")


@dataclass
class DetectionSettings:
    nucleus_diameter_um: float | None = None
    cellprob_threshold: float = 0.0
    flow_threshold: float = 0.4
    min_size: int = 15
    clip_black: float = 0.0
    clip_white: float = 0.25
    use_gpu: bool = True


@dataclass
class QcSettings:
    min_area_ratio: float = 0.30
    max_area_ratio: float = 3.50
    min_solidity: float = 0.85
    max_eccentricity: float = 0.96
    min_cellprob_percentile: float = 2.0
    min_dapi_relative: float = 0.15
    max_saturated_fraction: float = 0.90
    exclude_border: bool = False
    pan_channel_percentile: float = 99.0


@dataclass
class JudgeSettings:
    control_percentile: float = 99.0
    min_control_cells: int = 300
    fixed_nuclear_ratio: float = 1.5
    fixed_background_ratio: float = 2.0
    pseudo_fraction: float = 0.01
    ring_gap_um: float = 0.3
    ring_width_um: float = 1.5
    min_roi_px: int = 20
    background_radius_factor: float = 3.0


@dataclass
class Settings:
    z_projection: str = "max"
    detection: DetectionSettings = field(default_factory=DetectionSettings)
    qc: QcSettings = field(default_factory=QcSettings)
    judge: JudgeSettings = field(default_factory=JudgeSettings)

    def __post_init__(self) -> None:
        if self.z_projection not in Z_PROJECTIONS:
            raise ValueError(
                f"Z 投影の指定が不正です: {self.z_projection}（{' / '.join(Z_PROJECTIONS)} のいずれか）")
        if not 50.0 <= self.judge.control_percentile < 100.0:
            raise ValueError(
                f"陰性対照のパーセンタイルは 50 以上 100 未満にしてください: {self.judge.control_percentile}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        parts = {"detection": DetectionSettings, "qc": QcSettings, "judge": JudgeSettings}
        _reject_unknown(cls, data, "設定")
        built = {name: _build(part, data.get(name, {}), f"設定の {name}")
                 for name, part in parts.items()}
        return cls(z_projection=data.get("z_projection", "max"), **built)


def _reject_unknown(cls: type, data: dict, where: str) -> None:
    unknown = sorted(set(data) - {f.name for f in fields(cls)})
    if unknown:
        raise ValueError(f"{where}に未知の項目があります: {', '.join(unknown)}")


def _build(cls: type, data: dict, where: str):
    _reject_unknown(cls, data, where)
    return cls(**data)
