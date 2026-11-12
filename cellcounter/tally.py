"""集計（組み合わせごとの数・共発現・核ごとの表・設定の記録）。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import product

import numpy as np

from . import __version__
from .judge import RULES
from .marks import ADDED, REMOVED
from .markers import LOCATION_SPECS
from .session import Session, tab_name


@dataclass
class SummaryRow:
    name: str
    total: int
    positive: int
    rate: float | None
    auto_positive: int
    auto_rate: float | None
    added: int
    removed: int
    undetermined: int


@dataclass
class CoexpressionRow:
    name: str
    cells: int
    rate: float | None


def _percent(part: int, whole: int) -> float | None:
    return round(part / whole * 100.0, 2) if whole else None


def counted_ids(session: Session) -> list[int]:
    return sorted(i for i, counted in session.marks.counted.items() if counted)


def _edits(session: Session, marker: str | None, kind: str) -> int:
    return sum(session.marks.category(marker, i) == kind for i in session.nuclei)


def summarize(session: Session) -> list[SummaryRow]:
    marks = session.marks
    counted = counted_ids(session)
    auto_counted = [i for i, auto in marks.counted_auto.items() if auto]
    rows = [SummaryRow(tab_name(None), len(counted), len(counted), None, len(auto_counted), None,
                       _edits(session, None, ADDED), _edits(session, None, REMOVED), 0)]
    for marker, judgement in session.judgements.items():
        positive = sum(marks.positive[marker][i] for i in counted)
        auto_positive = sum(marks.positive_auto[marker][i] for i in auto_counted)
        rows.append(SummaryRow(
            name=tab_name(marker), total=len(counted), positive=positive,
            rate=_percent(positive, len(counted)), auto_positive=auto_positive,
            auto_rate=_percent(auto_positive, len(auto_counted)),
            added=_edits(session, marker, ADDED), removed=_edits(session, marker, REMOVED),
            undetermined=sum(not np.isfinite(judgement.values[i]) for i in counted)))
    return rows


def coexpression(session: Session) -> list[CoexpressionRow]:
    """判定したマーカーの陽性・陰性の全組み合わせ。数える核を重なりなく分ける。"""
    markers = list(session.judgements)
    if not markers:
        return []
    counted = counted_ids(session)
    rows = []
    for pattern in product((True, False), repeat=len(markers)):
        wanted = dict(zip(markers, pattern))
        cells = sum(all(session.marks.positive[m][i] == w for m, w in wanted.items())
                    for i in counted)
        name = "/".join(f"{m}{'＋' if w else '−'}" for m, w in wanted.items())
        rows.append(CoexpressionRow(name, cells, _percent(cells, len(counted))))
    return rows


def _yes(flag: bool) -> str:
    return "はい" if flag else "いいえ"


def cell_table(session: Session) -> tuple[list[str], list[list]]:
    """核 1 個につき 1 行。数えない核も、理由と一緒に残す。"""
    um = session.um_per_px
    marks = session.marks
    header = ["ID", "X (px)", "Y (px)", "X (µm)", "Y (µm)", "面積 (px)", "面積 (µm²)",
              "手で作った核", "自動で数えた", "数える", "QC の除外理由", "全チャンネルで明るい"]
    for marker in session.judgements:
        header += [f"{marker} 値", f"{marker} 自動判定", f"{marker} 確定判定", f"{marker} 手で直した"]

    rows = []
    for nucleus_id in sorted(session.nuclei):
        nucleus = session.nuclei[nucleus_id]
        counted = marks.counted[nucleus_id]
        row = [nucleus_id, round(nucleus.x, 1), round(nucleus.y, 1), round(nucleus.x * um, 2),
               round(nucleus.y * um, 2), nucleus.area_px, round(nucleus.area_px * um * um, 2),
               _yes(nucleus.manual), _yes(marks.counted_auto[nucleus_id]), _yes(counted),
               "; ".join(nucleus.qc_reasons), _yes(nucleus.pan_channel)]
        for marker, judgement in session.judgements.items():
            value = judgement.values[nucleus_id]
            auto = marks.positive_auto[marker][nucleus_id]
            final = marks.positive[marker][nucleus_id]
            measured = np.isfinite(value)
            row += [round(value, 4) if measured else None,
                    ("陽性" if auto else "陰性") if measured else "判定不能",
                    ("陽性" if final else "陰性") if counted else "—",
                    _yes(counted and auto != final)]
        rows.append(row)
    return header, rows


def notes(session: Session) -> list[str]:
    """Summary に添える注記（突起マーカーの偏りなど）。"""
    found = []
    for marker, judgement in session.judgements.items():
        note = LOCATION_SPECS[judgement.location].note
        if note:
            found.append(f"{marker}: {note}")
    return found


def settings_record(session: Session) -> list[tuple[str, str]]:
    """Settings シートに残す、結果の出どころの記録。"""
    image, meta = session.image, session.image.meta
    status = "マーカーの判定なし"
    if session.judgements:
        status = "暫定（陰性対照なし）" if session.provisional else "陰性対照を基準に判定"
    record = [
        ("ソフトの版", f"cellcounter {__version__}"),
        ("出力した日時", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("元ファイル", os.path.basename(image.path)),
        ("元ファイルの場所", os.path.dirname(image.path)),
        ("シーン", str(image.scene)),
        ("Z 投影", f"{image.z_projection}（Z {image.n_z} 枚）"),
        ("µm/px", f"{session.um_per_px:.4f}"),
        ("ビット深度", str(meta.bits)),
        ("対物レンズ", meta.objective or "取得できず"),
        ("判定の状態", status),
        ("標準の核直径 (px)", f"{session.diameter_px:.1f}"),
    ]
    for row in session.table.rows:
        if row.role == "dapi":
            role = "DAPI（核・分母）"
        elif row.role == "marker" and row.marker:
            location = LOCATION_SPECS[row.location].label if row.location else "未選択"
            role = f"{row.marker}／{location}／判定 {'ON' if row.judge else 'OFF'}"
        else:
            role = "使わない"
        record.append((f"チャンネル {row.index}: {row.name}（{row.dye or '色素不明'}）", role))

    for group, values in (("検出", session.settings.detection), ("QC", session.settings.qc),
                          ("判定", session.settings.judge)):
        record += [(f"{group}: {key}", str(value)) for key, value in asdict(values).items()]

    for marker, judgement in session.judgements.items():
        record.append((f"{marker}: 判定法", RULES[judgement.rule].label))
        record += [(f"{marker}: {key}", value) for key, value in judgement.detail.items()]
    if session.control:
        record.append(("陰性対照のファイル", "、".join(session.control.files)))
        record.append(("陰性対照の細胞数（合計）", str(session.control.n_cells)))
    record += [(f"警告 {number}", text) for number, text in enumerate(session.warnings, 1)]
    return record
