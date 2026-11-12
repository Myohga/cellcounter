""".czi の XML メタデータから、画素サイズ・チャンネル・撮影条件を取り出す。"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_CHANNEL_PATH = ".//Information/Image/Dimensions/Channels/Channel"
_ACQUISITION_FIELDS = (
    ("検出器ゲイン (V)", "DetectorSettings/Voltage"),
    ("ゲイン", "DetectorSettings/Gain"),
    ("デジタルゲイン", "DetectorSettings/DigitalGain"),
    ("オフセット", "DetectorSettings/Offset"),
    ("露光時間", "ExposureTime"),
    ("画素あたりの時間 (s)", "LaserScanInfo/PixelTime"),
    ("平均化の回数", "LaserScanInfo/Averaging"),
)
_RELATIVE_TOLERANCE = 1e-3


@dataclass
class ChannelInfo:
    index: int
    name: str
    fluor: str
    excitation_nm: float | None
    emission_nm: float | None
    contrast: str
    acquisition: dict[str, str] = field(default_factory=dict)


@dataclass
class ImageMeta:
    channels: list[ChannelInfo]
    um_per_px: float | None
    bits: int | None
    objective: str


def _text(element: ET.Element | None, path: str) -> str:
    found = element.find(path) if element is not None else None
    return found.text.strip() if found is not None and found.text else ""


def _number(element: ET.Element | None, path: str) -> float | None:
    text = _text(element, path)
    try:
        return float(text)
    except ValueError:
        return None


def _acquisition(channel: ET.Element) -> dict[str, str]:
    values = {label: _text(channel, path) for label, path in _ACQUISITION_FIELDS}
    for source in channel.findall("LightSourcesSettings/LightSourceSettings"):
        wavelength = _text(source, "Wavelength") or "?"
        for label, tag in (("減衰", "Attenuation"), ("強度", "Intensity")):
            values[f"光源 {wavelength} nm の{label}"] = _text(source, tag)
    return {label: value for label, value in values.items() if value}


def _objective(root: ET.Element) -> str:
    objectives = root.findall(".//Information/Instrument/Objectives/Objective")
    used = root.find(".//Information/Image/ObjectiveSettings/ObjectiveRef")
    if used is not None:
        objectives = [o for o in objectives if o.get("Id") == used.get("Id")]
    return objectives[0].get("Name", "") if len(objectives) == 1 else ""


def parse_metadata(xml: str) -> ImageMeta:
    root = ET.fromstring(xml)
    image = root.find(".//Information/Image")
    channels = []
    for index, channel in enumerate(root.findall(_CHANNEL_PATH)):
        channels.append(ChannelInfo(
            index=index,
            name=channel.get("Name") or channel.get("Id") or f"ch{index}",
            fluor=_text(channel, "Fluor"),
            excitation_nm=_number(channel, "ExcitationWavelength"),
            emission_nm=_number(channel, "EmissionWavelength"),
            contrast=_text(channel, "ContrastMethod"),
            acquisition=_acquisition(channel),
        ))
    if not channels:
        raise ValueError("メタデータにチャンネルの情報がありません。")

    meters = _number(root, ".//Scaling/Items/Distance[@Id='X']/Value")
    bits = _number(image, "ComponentBitCount")
    return ImageMeta(
        channels=channels,
        um_per_px=meters * 1e6 if meters else None,
        bits=int(bits) if bits else None,
        objective=_objective(root),
    )


def _same(a: str, b: str) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=_RELATIVE_TOLERANCE)
    except ValueError:
        return a == b


def compare_acquisition(sample: ImageMeta, control: ImageMeta, control_name: str) -> list[str]:
    """実験画像と陰性対照の撮影条件を比べ、違いと「比べられなかった項目」を文章で返す。"""
    pairs = [
        ("ビット深度", str(sample.bits or ""), str(control.bits or "")),
        ("対物レンズ", sample.objective, control.objective),
        ("µm/px", str(sample.um_per_px or ""), str(control.um_per_px or "")),
    ]
    for ours, theirs in zip(sample.channels, control.channels):
        for label in dict.fromkeys([*ours.acquisition, *theirs.acquisition]):
            pairs.append((f"{ours.name} の{label}",
                          ours.acquisition.get(label, ""), theirs.acquisition.get(label, "")))

    differences, unknown = [], []
    for label, ours, theirs in pairs:
        if not ours or not theirs:
            unknown.append(label)
        elif not _same(ours, theirs):
            differences.append(f"{label}（実験 {ours} / 対照 {theirs}）")

    warnings = []
    if differences:
        warnings.append(f"陰性対照 {control_name} は撮影条件が実験画像と違います: "
                        + "、".join(differences))
    if unknown:
        warnings.append(f"陰性対照 {control_name} の次の撮影条件はメタデータから取得できず、"
                        "比較していません: " + "、".join(unknown))
    return warnings
