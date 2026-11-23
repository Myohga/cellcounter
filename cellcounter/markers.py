"""抗体マーカーの辞書（染まる場所・判定法の既定・コメント）と、場所ごとの測る範囲。"""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass, fields


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

# 判定法。陽性率は核ごとに陽性・陰性を決めて数える。平均蛍光強度は範囲の中の明るさを平均する
# （ZEN の Measure に出る Intensity Mean Value と同じ値）
METHOD_RATE, METHOD_IMV = "rate", "imv"
METHODS = {METHOD_RATE: "陽性率", METHOD_IMV: "平均蛍光強度"}
# ③ で平均蛍光強度を測るタブの名前（マーカー名には使えない）
IMV_TAB_NAME = METHODS[METHOD_IMV]

# 短い登録名（th, tau など）は別の単語の一部に紛れ込むので、部分一致には使わない
_MIN_PARTIAL_LENGTH = 4
DICTIONARY_FORMAT = 1


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


def marker_key(text: str) -> str:
    """表記の揺れを消した照合用の名前（記号と空白を除き、全角を半角に、大文字を小文字にする）。

    英数字のほか、日本語やギリシャ文字も残す（「βIII-tubulin」や日本語の名前も登録できる）。
    """
    folded = unicodedata.normalize("NFKC", str(text)).casefold()
    return "".join(char for char in folded if char.isalnum())


@dataclass(frozen=True)
class MarkerEntry:
    """辞書の 1 件。location が空なら、染まる場所は利用者が選ぶ。"""

    name: str
    location: str = ""
    counts_nuclei: bool = False  # 選んだとき、そのチャンネルを「核を数える」にする
    imv: bool = False            # 選んだとき、判定法を「平均蛍光強度」にする
    comment: str = ""

    @property
    def key(self) -> str:
        return marker_key(self.name)

    def describe(self) -> str:
        """②のプルダウンで名前にポインターを合わせたときに出す説明。"""
        if self.counts_nuclei:
            facts = "選ぶと「核を数える」チャンネルになります"
        else:
            place = LOCATION_SPECS[self.location].label if self.location else "未設定"
            facts = f"染まる場所: {place} ／ 判定法: {METHODS[METHOD_IMV if self.imv else METHOD_RATE]}"
        return f"{self.comment}\n（{facts}）" if self.comment else f"（{facts}）"


def _entries(location: str, names: tuple[str, ...], **attributes) -> list[MarkerEntry]:
    return [MarkerEntry(name, location, **attributes) for name in names]


_TAU_IMV = "タウのマーカーなので、平均蛍光強度で測ります。"
DEFAULT_ENTRIES: tuple[MarkerEntry, ...] = (
    *_entries("", ("DAPI", "Hoechst", "DRAQ5", "TO-PRO-3"), counts_nuclei=True,
              comment="核の染色。"),
    *_entries("nuclear", (
        "PAX6", "PAX7", "SOX1", "SOX2", "SOX9", "SOX10", "NKX6.1", "NKX2.2", "NKX2.1", "TTF-1",
        "OLIG1", "OLIG2", "FOXG1", "FOXA2", "OTX2", "LHX3", "ISL1", "Islet-1", "Islet", "MNX1",
        "HB9", "PHOX2B", "BRN3A", "POU4F1", "TBR1", "TBR2", "EOMES", "CTIP2", "BCL11B", "SATB2",
        "CUX1", "NeuN", "RBFOX3", "Ki67", "MKI67", "PH3", "phospho-histone H3", "OCT4", "POU5F1",
        "NANOG", "GATA3", "CHX10", "VSX2", "TFAP2A", "MEF2C", "MYT1L", "HOXB4", "HOXC9", "EN1",
        "NURR1", "NR4A2", "PITX3", "ASCL1", "NEUROD1", "NGN2", "NEUROG2")),
    *_entries("cytoplasmic", (
        "ChAT", "TH", "tyrosine hydroxylase", "GFAP", "S100B", "S100", "IBA1", "AIF1", "GAD67",
        "GAD65", "Calbindin", "Calretinin", "Parvalbumin", "Somatostatin", "SST", "PGP9.5", "UCHL1",
        "Serotonin", "5-HT", "DBH", "VIP", "Nestin", "Vimentin", "cleaved caspase-3", "caspase-3",
        "AQP4", "CNPase", "6E10")),
    *_entries("fibrillar", (
        "MAP2", "TUJ1", "beta III-tubulin", "bIII-tubulin", "TUBB3", "NF-H", "NF-M", "NF-L",
        "Neurofilament", "SMI-32", "SMI-31", "DCX", "Doublecortin", "GAP43", "MBP", "Peripherin",
        "Phalloidin", "F-actin")),
    MarkerEntry("Tau", "fibrillar", imv=True, comment=f"タウ。{_TAU_IMV}"),
    MarkerEntry("pTau", "fibrillar", imv=True, comment=f"リン酸化タウ。{_TAU_IMV}"),
    MarkerEntry("EP2456Y", "fibrillar", imv=True,
                comment=f"総タウ（リン酸化の有無によらない）。{_TAU_IMV}"),
    MarkerEntry("AT8", "fibrillar", imv=True,
                comment=f"リン酸化タウ（Ser202/Thr205）。{_TAU_IMV}"),
    *_entries("punctate", (
        "Synapsin", "Synapsin-1", "SYN1", "Synaptophysin", "SYP", "VGLUT1", "VGLUT2", "SLC17A7",
        "SLC17A6", "VGAT", "VAChAT", "VAChT", "PSD-95", "DLG4", "Bassoon", "Piccolo", "Homer1",
        "Gephyrin", "SV2", "SNAP-25", "Syntaxin", "Synaptotagmin")),
    *_entries("membrane", (
        "NCAM", "L1CAM", "PDGFRA", "p75", "NGFR", "CD44", "E-cadherin", "N-cadherin", "Integrin")),
)


class MarkerDictionary:
    """マーカー名から既定の設定を引く辞書。利用者が登録・編集・削除できる。"""

    def __init__(self, entries: list[MarkerEntry] | tuple[MarkerEntry, ...] = DEFAULT_ENTRIES) -> None:
        self.entries: list[MarkerEntry] = []
        for entry in entries:
            self.add(entry)

    def find(self, name: str) -> MarkerEntry | None:
        """名前が一致する登録。無ければ、名前の一部に含まれるいちばん長い登録（4 文字以上）。"""
        key = marker_key(name)
        if not key:
            return None
        by_key = {entry.key: entry for entry in self.entries}
        if key in by_key:
            return by_key[key]
        for candidate in sorted(by_key, key=len, reverse=True):
            if len(candidate) >= _MIN_PARTIAL_LENGTH and candidate in key:
                return by_key[candidate]
        return None

    def exact(self, name: str) -> MarkerEntry | None:
        key = marker_key(name)
        return next((entry for entry in self.entries if entry.key == key), None)

    def check(self, entry: MarkerEntry, replacing: str | None = None) -> None:
        """登録できない内容なら ValueError。replacing は編集する前の名前。"""
        if not entry.key:
            raise ValueError("マーカー名には、文字か数字を 1 つ以上入れてください。")
        if entry.location:
            location_spec(entry.location)
        same = self.exact(entry.name)
        if same is not None and (replacing is None or same.key != marker_key(replacing)):
            raise ValueError(f"「{entry.name}」は「{same.name}」と同じ名前として扱われるため、"
                             "登録できません（大文字・小文字や記号の違いは区別しません）。")

    def add(self, entry: MarkerEntry) -> None:
        self.check(entry)
        self.entries.append(entry)

    def replace(self, old_name: str, entry: MarkerEntry) -> None:
        self.check(entry, replacing=old_name)
        position = self.entries.index(self._get(old_name))
        self.entries[position] = entry

    def remove(self, name: str) -> None:
        self.entries.remove(self._get(name))

    def reset(self) -> None:
        self.entries = list(DEFAULT_ENTRIES)

    def _get(self, name: str) -> MarkerEntry:
        entry = self.exact(name)
        if entry is None:
            raise KeyError(f"マーカー {name} は辞書にありません。")
        return entry

    def to_dict(self) -> dict:
        return {"format": DICTIONARY_FORMAT, "markers": [asdict(entry) for entry in self.entries]}

    @classmethod
    def from_dict(cls, data: dict) -> MarkerDictionary:
        if data.get("format") != DICTIONARY_FORMAT:
            raise ValueError(f"マーカー辞書の形式が違います（format={data.get('format')}）。")
        known = {field.name for field in fields(MarkerEntry)}
        return cls([MarkerEntry(**{key: value for key, value in item.items() if key in known})
                    for item in data["markers"]])


# いま使っている辞書。画面とコマンドラインは、起動したときに利用者の辞書に差し替える
_active = MarkerDictionary()


def use_dictionary(dictionary: MarkerDictionary) -> None:
    global _active
    _active = dictionary


def active_dictionary() -> MarkerDictionary:
    return _active


def lookup(marker: str) -> MarkerEntry | None:
    return _active.find(marker)


def guess_location(marker: str) -> str | None:
    """辞書から染まる場所を推定する。辞書に無ければ None（利用者に選ばせる）。"""
    entry = lookup(marker)
    return (entry.location or None) if entry else None
