"""作業ファイル（.cellcounter）の保存と再開。画像は入れず、元の .czi を読み直す。"""

from __future__ import annotations

import io
import json
import math
import os
import zipfile
from dataclasses import asdict
from datetime import datetime
from typing import Callable

import numpy as np

from . import __version__
from .channels import ChannelTable, build_table
from .czi import LoadedImage, read_scene
from .intensity import Region
from .model import ControlData, Judgement, Nucleus
from .session import Session
from .settings import Settings

FORMAT = 1
EXTENSION = ".cellcounter"
_JSON, _LABELS = "project.json", "labels.npy"


def _keyed(mapping: dict[int, object]) -> dict[str, object]:
    """JSON のキーは文字列だけ。nan は JSON に無いので null にする。"""
    return {str(key): None if isinstance(value, float) and math.isnan(value) else value
            for key, value in mapping.items()}


def _unkeyed(mapping: dict[str, object], missing: object = None) -> dict[int, object]:
    return {int(key): missing if value is None else value for key, value in mapping.items()}


def save_project(session: Session, path: str) -> None:
    image = session.image
    stat = os.stat(image.path) if os.path.isfile(image.path) else None
    marks = session.marks
    data = {
        "format": FORMAT,
        "app_version": __version__,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "source": {"path": image.path, "scene": image.scene, "z_projection": image.z_projection,
                   "um_per_px": image.meta.um_per_px,
                   "size": stat.st_size if stat else None,
                   "mtime": stat.st_mtime if stat else None},
        "table": session.table.to_list(),
        "settings": session.settings.to_dict(),
        "diameter_px": session.diameter_px,
        "nuclei": [asdict(nucleus) for nucleus in session.nuclei.values()],
        "judgements": [{**asdict(j), "values": _keyed(j.values), "auto": _keyed(j.auto)}
                       for j in session.judgements.values()],
        "marks": {
            "counted_auto": _keyed(marks.counted_auto),
            "counted": _keyed(marks.counted),
            "positive_auto": {m: _keyed(v) for m, v in marks.positive_auto.items()},
            "positive": {m: _keyed(v) for m, v in marks.positive.items()},
        },
        "control": asdict(session.control) if session.control else None,
        "contrast": _keyed(session.contrast),
        "shown": session.shown,
        "blind": {marker: _keyed(marked) for marker, marked in session.blind.items()},
        "blind_active": session.blind_active,
        "imv_channels": session.imv_channels,
        "regions": [{"shape": region.shape, "points": [list(point) for point in region.points]}
                    for region in session.regions],
        "warnings": session.warnings,
    }
    labels = io.BytesIO()
    np.save(labels, session.labels)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_JSON, json.dumps(data, ensure_ascii=False, indent=1))
        archive.writestr(_LABELS, labels.getvalue())


def load_project(path: str, czi_path: str | None = None,
                 loader: Callable[[str, int, str], LoadedImage] = read_scene) -> Session:
    """作業ファイルを開く。.czi を移動していたら czi_path で新しい場所を渡す。"""
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read(_JSON).decode("utf-8"))
        labels = np.load(io.BytesIO(archive.read(_LABELS)))
    if data.get("format") != FORMAT:
        raise ValueError(f"この作業ファイルの形式（format={data.get('format')}）には対応していません。")

    source = data["source"]
    settings = Settings.from_dict(data["settings"])
    image = loader(czi_path or source["path"], source["scene"], source["z_projection"])
    image.meta.um_per_px = source["um_per_px"]
    if labels.shape != image.planes.shape[1:]:
        raise ValueError("作業ファイルと .czi で画像の大きさが違います。別のファイルかもしれません。")

    table = ChannelTable.from_list(data["table"])
    # 表示色は作業の状態ではなく画像の性質なので、保存した値ではなく .czi から取り直す
    for row, fresh in zip(table.rows, build_table(image.meta).rows):
        row.color = fresh.color
    session = Session(image, table, settings)
    session.warnings = list(data["warnings"])
    if os.path.isfile(image.path) and source["size"] is not None:
        stat = os.stat(image.path)
        if (stat.st_size, stat.st_mtime) != (source["size"], source["mtime"]):
            session.add_warnings([".czi が作業ファイルを保存したときから変わっています。"])

    session.labels = labels
    session.diameter_px = data["diameter_px"]
    session.nuclei = {n["id"]: Nucleus(**{**n, "qc_reasons": tuple(n["qc_reasons"])})
                      for n in data["nuclei"]}
    for stored in data["judgements"]:
        judgement = Judgement(**{**stored, "values": _unkeyed(stored["values"], math.nan),
                                 "auto": _unkeyed(stored["auto"])})
        session.judgements[judgement.marker] = judgement
    marks = data["marks"]
    session.marks.counted_auto = _unkeyed(marks["counted_auto"])
    session.marks.counted = _unkeyed(marks["counted"])
    session.marks.positive_auto = {m: _unkeyed(v) for m, v in marks["positive_auto"].items()}
    session.marks.positive = {m: _unkeyed(v) for m, v in marks["positive"].items()}
    if data["control"]:
        session.control = ControlData(**data["control"])
        session.control.sources = [tuple(source) for source in session.control.sources]
    session.contrast = {index: tuple(limits)
                        for index, limits in _unkeyed(data["contrast"]).items()}
    # 0.1.0 の途中までに保存した作業ファイルには、この項目が無い
    session.shown = data.get("shown", {})
    session.blind = {m: _unkeyed(v) for m, v in data.get("blind", {}).items()}
    session.blind_active = data.get("blind_active", False)
    # 平均蛍光強度を足す前に保存した作業ファイルには、この 2 つが無い
    session.imv_channels = data.get("imv_channels", {})
    session.regions = [Region.of(stored["shape"], stored["points"])
                       for stored in data.get("regions", [])]
    return session
