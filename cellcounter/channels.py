"""チャンネル表（どのチャンネルが DAPI で、どのマーカーを判定するか）とプリセット。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .dyes import NUCLEAR_STAINS, color_of_wavelength, identify_dye
from .markers import guess_location, location_spec
from .metadata import ImageMeta

PRESET_FORMAT = 1


@dataclass
class ChannelRow:
    index: int
    name: str
    dye: str
    excitation_nm: float | None
    emission_nm: float | None
    fluorescence: bool
    role: str  # "dapi" | "marker" | "unused"
    marker: str = ""
    location: str = ""
    judge: bool = False
    color: str = "#FFFFFF"

    @property
    def title(self) -> str:
        """画面に出す呼び名（マーカー名があればそれ、無ければ色素名かチャンネル名）。"""
        if self.role == "dapi":
            return f"DAPI（{self.dye or self.name}）"
        return self.marker or self.dye or self.name


class ChannelTable:
    def __init__(self, rows: list[ChannelRow]) -> None:
        self.rows = rows

    def row(self, index: int) -> ChannelRow:
        for row in self.rows:
            if row.index == index:
                return row
        raise KeyError(f"チャンネル {index} はありません。")

    @property
    def dapi(self) -> ChannelRow:
        chosen = [row for row in self.rows if row.role == "dapi"]
        if len(chosen) != 1:
            raise ValueError("DAPI のチャンネルが決まっていません。チャンネル表で選んでください。")
        return chosen[0]

    def judged(self) -> list[ChannelRow]:
        return [row for row in self.rows if row.role == "marker" and row.judge]

    def set_dapi(self, index: int) -> None:
        """核を数えるチャンネルを選び直す。行に入れてあるマーカー名などは消さない。"""
        target = self.row(index)
        if not target.fluorescence:
            raise ValueError(f"{target.name} は蛍光チャンネルではないので DAPI にできません。")
        for row in self.rows:
            if row.role == "dapi":
                row.role = "marker"
        target.role = "dapi"

    def set_marker(self, index: int, marker: str, location: str | None = None,
                   judge: bool = True) -> None:
        """location を省くと辞書から推定する。辞書に無ければ空のまま（problems が指摘する）。"""
        row = self.row(index)
        if row.role != "marker":
            raise ValueError(f"{row.name} にはマーカーを割り当てられません（{row.role}）。")
        if location is None:
            location = guess_location(marker) or ""
        elif location:
            location_spec(location)
        row.marker, row.location, row.judge = marker.strip(), location, judge

    def problems(self) -> list[str]:
        """判定を始める前に直すべき点。空なら問題なし。"""
        found = []
        if sum(row.role == "dapi" for row in self.rows) != 1:
            found.append("DAPI のチャンネルが決まっていません。")
        names = [row.marker for row in self.judged()]
        for row in self.judged():
            if not row.marker:
                found.append(f"{row.name}: マーカー名が空です。")
            elif not row.location:
                found.append(f"{row.name}（{row.marker}）: 染まる場所を選んでください"
                             "（辞書に無い名前なので推定できません）。")
            if row.marker and names.count(row.marker) > 1:
                found.append(f"マーカー名 {row.marker} が重複しています。")
        return list(dict.fromkeys(found))

    def to_list(self) -> list[dict]:
        return [asdict(row) for row in self.rows]

    @classmethod
    def from_list(cls, data: list[dict]) -> ChannelTable:
        return cls([ChannelRow(**row) for row in data])


def build_table(meta: ImageMeta) -> ChannelTable:
    """メタデータから表を作る。核染色が 1 本だけ見つかったときに限り DAPI を自動で決める。"""
    rows = []
    for channel in meta.channels:
        fluorescence = channel.contrast.lower() in ("", "fluorescence")
        dye = identify_dye(channel.name, channel.fluor,
                           emission_nm=channel.emission_nm) if fluorescence else ""
        color = channel.color or color_of_wavelength(channel.emission_nm if fluorescence else None)
        rows.append(ChannelRow(channel.index, channel.name, dye, channel.excitation_nm,
                               channel.emission_nm, fluorescence,
                               role="marker" if fluorescence else "unused", color=color))
    stains = [row for row in rows if row.dye in NUCLEAR_STAINS]
    if len(stains) == 1:
        stains[0].role = "dapi"
    return ChannelTable(rows)


def preset_of(table: ChannelTable, name: str) -> dict:
    channels = [{"channel": row.name, "dye": row.dye, "role": row.role, "marker": row.marker,
                 "location": row.location, "judge": row.judge}
                for row in table.rows if row.fluorescence]
    return {"format": PRESET_FORMAT, "name": name, "channels": channels}


def _match(table: ChannelTable, entry: dict) -> ChannelRow:
    for key, attribute in (("channel", "name"), ("dye", "dye")):
        hits = [row for row in table.rows
                if entry.get(key) and getattr(row, attribute) == entry[key]]
        if len(hits) == 1:
            return hits[0]
    raise ValueError(f"プリセットのチャンネル {entry.get('channel')}（{entry.get('dye')}）に"
                     "対応するチャンネルが、この画像にありません。")


def apply_preset(table: ChannelTable, preset: dict) -> None:
    if preset.get("format") != PRESET_FORMAT:
        raise ValueError(f"プリセットの形式が違います（format={preset.get('format')}）。")
    matched = [(_match(table, entry), entry) for entry in preset["channels"]]
    for row, entry in matched:
        if entry["location"]:
            location_spec(entry["location"])
        row.marker, row.location, row.judge = entry["marker"], entry["location"], entry["judge"]
    for row, entry in matched:
        if entry["role"] == "dapi":
            table.set_dapi(row.index)


def save_preset(path: str, preset: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(preset, handle, ensure_ascii=False, indent=2)


def load_preset(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
