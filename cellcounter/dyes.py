"""チャンネル名と蛍光波長から色素を見分ける。"""

from __future__ import annotations

import re

NUCLEAR_STAINS = ("DAPI", "Hoechst")
EMISSION_TOLERANCE_NM = 20.0

_ALIASES = {
    "Hoechst": ("hoechst", "h3342", "h33342", "h33258", "bisbenzimide", "nucblue"),
    "DAPI": ("dapi",),
    "AF488": ("fitc", "gfp", "cy2"),
    "AF555": ("cy3", "tritc", "rhodamine"),
    "AF594": ("texasred", "mcherry"),
    "AF647": ("cy5", "apc"),
    "AF750": ("cy7",),
}
_EMISSION_NM = {
    "DAPI": 461.0, "AF405": 421.0, "AF488": 519.0, "AF546": 573.0, "AF555": 565.0,
    "AF568": 603.0, "AF594": 617.0, "AF633": 647.0, "AF647": 668.0, "AF680": 702.0,
    "AF750": 775.0,
}
_ALEXA = re.compile(r"(?:alexafluor|alexa|af)(\d{3})")
# ZEN は色素を指定していないチャンネルに "Dye5" のような名前を付ける
_PLACEHOLDER = re.compile(r"dye\d+")


def normalize(text: str) -> str:
    """表記の揺れを消す（英数字だけを残して小文字にする）。"""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def identify_dye(*names: str, emission_nm: float | None = None) -> str:
    """名前、蛍光波長の順に照合して色素名を返す。分からなければ空文字。"""
    for name in names:
        text = normalize(name)
        if not text or _PLACEHOLDER.fullmatch(text):
            continue
        alexa = _ALEXA.search(text)
        if alexa:
            return f"AF{alexa.group(1)}"
        for dye, aliases in _ALIASES.items():
            if any(alias in text for alias in aliases):
                return dye
    if emission_nm:
        dye, peak = min(_EMISSION_NM.items(), key=lambda item: abs(item[1] - emission_nm))
        if abs(peak - emission_nm) <= EMISSION_TOLERANCE_NM:
            return dye
    return ""
