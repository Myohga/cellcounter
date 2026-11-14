"""マーカー名から染まる場所を推定する辞書と、場所ごとの測る範囲。"""

from __future__ import annotations

from dataclasses import dataclass

from .dyes import normalize


@dataclass(frozen=True)
class AreaSpec:
    """核の周りの範囲と、その中で細胞の値にする分位。"""

    include_nucleus: bool
    reach_um: float
    percentile: float
    tophat_um: float | None = None

    @property
    def min_fraction(self) -> float:
        """陽性に必要な「閾値を超える画素の割合」。分位と同じことを言い換えたもの。"""
        return 100.0 - self.percentile


@dataclass(frozen=True)
class LocationSpec:
    label: str
    area: AreaSpec | None = None
    note: str = ""
    area_metric: bool = False  # 画像全体の陽性面積も出すか（突起は細胞に割り振れないため）


LOCATION_SPECS: dict[str, LocationSpec] = {
    "nuclear": LocationSpec("核"),
    "cytoplasmic": LocationSpec("細胞質", AreaSpec(True, 3.0, 75.0)),
    "membrane": LocationSpec("膜", AreaSpec(False, 3.0, 75.0)),
    "fibrillar": LocationSpec(
        "突起", AreaSpec(False, 2.0, 90.0),
        note="突起のマーカーは核の周り 2 µm だけで測ります。"
             "密な培養では隣の細胞の突起を拾い、陽性に偏ることがあります。",
        area_metric=True),
    "punctate": LocationSpec("点状", AreaSpec(False, 3.0, 97.0, tophat_um=1.0)),
}

_LIBRARY = {
    "nuclear": """pax6 pax7 sox1 sox2 sox9 sox10 nkx61 nkx22 nkx21 ttf1 olig1 olig2 foxg1
        foxa2 otx2 lhx3 isl1 islet1 islet mnx1 hb9 phox2b brn3a pou4f1 tbr1 tbr2 eomes
        ctip2 bcl11b satb2 cux1 neun rbfox3 ki67 mki67 ph3 phosphohistoneh3 oct4 pou5f1
        nanog gata3 chx10 vsx2 tfap2a mef2c myt1l hoxb4 hoxc9 en1 nurr1 nr4a2 pitx3
        ascl1 neurod1 ngn2 neurog2""",
    "cytoplasmic": """chat th tyrosinehydroxylase gfap s100b s100 iba1 aif1 gad67 gad65
        calbindin calretinin parvalbumin somatostatin sst pgp95 uchl1 serotonin 5ht dbh
        vip nestin vimentin cleavedcaspase3 caspase3 aqp4 cnpase""",
    "fibrillar": """map2 tuj1 betaiiitubulin biiitubulin tubb3 tau ptau at8 ep2456y nfh nfm nfl
        neurofilament smi32 smi31 dcx doublecortin gap43 mbp peripherin phalloidin
        factin""",
    "punctate": """synapsin synapsin1 syn1 synaptophysin syp vglut1 vglut2 slc17a7 slc17a6
        vgat vachat vacht psd95 dlg4 bassoon piccolo homer1 gephyrin sv2 snap25 syntaxin
        synaptotagmin""",
    "membrane": "ncam l1cam pdgfra p75 ngfr cd44 ecadherin ncadherin integrin",
}
_LOCATION_OF = {name: location for location, names in _LIBRARY.items() for name in names.split()}
# 短い登録名（th, tau など）は別の単語の一部に紛れ込むので、部分一致には使わない
_MIN_PARTIAL_LENGTH = 4


def location_spec(location: str) -> LocationSpec:
    if location not in LOCATION_SPECS:
        raise ValueError(
            f"染まる場所の指定が不正です: '{location}'（{' / '.join(LOCATION_SPECS)} のいずれか）")
    return LOCATION_SPECS[location]


def location_key(text: str) -> str:
    """「核」などの表示名か内部名を受け取り、内部名を返す。"""
    for key, spec in LOCATION_SPECS.items():
        if text in (key, spec.label):
            return key
    labels = " / ".join(spec.label for spec in LOCATION_SPECS.values())
    raise ValueError(f"染まる場所の指定が不正です: '{text}'（{labels} のいずれか）")


def guess_location(marker: str) -> str | None:
    """辞書から染まる場所を推定する。辞書に無ければ None（利用者に選ばせる）。"""
    name = normalize(marker)
    if name in _LOCATION_OF:
        return _LOCATION_OF[name]
    for key in sorted(_LOCATION_OF, key=len, reverse=True):
        if len(key) >= _MIN_PARTIAL_LENGTH and key in name:
            return _LOCATION_OF[key]
    return None
