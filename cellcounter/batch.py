"""一括処理。複数の画像を同じ設定で判定し、1 つの Excel にまとめる。"""

from __future__ import annotations

import copy
import json
import os
import re
import statistics
from dataclasses import asdict, dataclass, replace
from typing import Callable

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference, Series
from openpyxl.chart.data_source import NumDataSource, NumRef
from openpyxl.chart.error_bar import ErrorBars
from openpyxl.styles import Font

from .channels import apply_preset, build_table, preset_of
from .control import Loader, collect_control
from .czi import list_scenes, read_scene
from .export import export_results
from .metadata import compare_acquisition
from .pipeline import Segmenter, open_session, run_detection, run_judgement
from .project import EXTENSION, load_project
from .segment import segment_nuclei
from .session import Session, tab_name
from .tally import summarize

BATCH_NAME, MANIFEST_NAME = "batch.xlsx", "batch.json"
_BOLD = Font(bold=True)


@dataclass
class BatchItem:
    path: str
    scene: int
    condition: str


@dataclass
class BatchRow:
    """画像 1 枚分の結果。rates はマーカー名 → 陽性率（%）。"""

    condition: str
    file: str
    scene: int
    folder: str
    total: int
    rates: dict[str, float | None]
    provisional: bool
    warnings: int


def condition_of(path: str) -> str:
    """条件の名前の既定。ファイル名から、末尾の通し番号（_1、 02、-3 など）を除いたもの。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[\s_\-]*\d+$", "", stem) or stem


def list_items(paths: list[str]) -> list[BatchItem]:
    """ファイルごとに、中にある全シーンを 1 件ずつ並べる。フォルダを渡すと中の .czi を使う。"""
    files = []
    for path in paths:
        if os.path.isdir(path):
            files += sorted(os.path.join(path, name) for name in os.listdir(path)
                            if name.lower().endswith(".czi"))
        else:
            files.append(path)
    return [BatchItem(os.path.abspath(file), scene.index, condition_of(file))
            for file in files for scene in list_scenes(file)]


def _row(item: BatchItem, folder: str, session: Session) -> BatchRow:
    rows = summarize(session)
    return BatchRow(item.condition, os.path.basename(item.path), item.scene, folder, rows[0].total,
                    {marker: row.rate for marker, row in zip(session.judgements, rows[1:])},
                    session.provisional, len(session.warnings))


def run_batch(items: list[BatchItem], template: Session, control_sources: list[tuple[str, int]],
              out_folder: str, segmenter: Segmenter = segment_nuclei, loader: Loader = read_scene,
              progress: Callable[[str], None] = lambda text: None) -> list[BatchRow]:
    """template のチャンネル表と設定で、items を順に判定して書き出す。

    画像ごとのフォルダに結果一式と作業ファイルを置くので、あとで 1 枚ずつ開いて修正できる。
    修正したあとは refresh_batch で batch.xlsx を作り直す。
    """
    if not items:
        raise ValueError("一括処理する画像がありません。")
    preset = preset_of(template.table, "一括処理")
    z_projection = template.settings.z_projection
    controls = {source: loader(source[0], source[1], z_projection) for source in control_sources}
    measured = None
    rows = []
    for number, item in enumerate(items, 1):
        progress(f"{number} / {len(items)}: {os.path.basename(item.path)}（シーン {item.scene}）")
        image = loader(item.path, item.scene, z_projection)
        if not image.meta.um_per_px:
            image.meta.um_per_px = template.image.meta.um_per_px
        table = build_table(image.meta)
        apply_preset(table, preset)
        session = open_session(image, table, copy.deepcopy(template.settings))
        run_detection(session, segmenter)

        control = None
        if controls:
            if measured is None:
                # 対照の値はサンプルによらないので、測るのは最初の 1 回だけ
                measured = collect_control(session, control_sources, segmenter,
                                           lambda path, scene, z: controls[path, scene])
            warnings = [text for source, control_image in controls.items()
                        for text in compare_acquisition(
                            image.meta, control_image.meta,
                            f"{os.path.basename(source[0])}（シーン {source[1]}）")]
            control = replace(measured, warnings=warnings)
        run_judgement(session, control)

        stem = os.path.splitext(os.path.basename(item.path))[0]
        folder = os.path.join(out_folder, f"{stem}_scene{item.scene}")
        export_results(session, folder)
        rows.append(_row(item, folder, session))

    with open(os.path.join(out_folder, MANIFEST_NAME), "w", encoding="utf-8") as handle:
        json.dump([asdict(item) | {"folder": row.folder} for item, row in zip(items, rows)],
                  handle, ensure_ascii=False, indent=1)
    write_batch(rows, os.path.join(out_folder, BATCH_NAME))
    return rows


def refresh_batch(out_folder: str, loader: Loader = read_scene) -> list[BatchRow]:
    """画像を 1 枚ずつ開いて修正したあと、各フォルダの作業ファイルから集計し直す。"""
    manifest = os.path.join(out_folder, MANIFEST_NAME)
    if not os.path.isfile(manifest):
        raise FileNotFoundError(f"一括処理のフォルダではありません（{MANIFEST_NAME} がありません）: "
                                f"{out_folder}")
    with open(manifest, encoding="utf-8") as handle:
        entries = json.load(handle)
    rows = []
    for entry in entries:
        projects = [name for name in os.listdir(entry["folder"]) if name.endswith(EXTENSION)]
        if len(projects) != 1:
            raise FileNotFoundError(f"作業ファイルが見つかりません: {entry['folder']}")
        session = load_project(os.path.join(entry["folder"], projects[0]), loader=loader)
        item = BatchItem(entry["path"], entry["scene"], entry["condition"])
        rows.append(_row(item, entry["folder"], session))
    write_batch(rows, os.path.join(out_folder, BATCH_NAME))
    return rows


def condition_stats(rows: list[BatchRow]) -> tuple[list[str], list[list]]:
    """条件ごとの、画像の枚数と、マーカーごとの陽性率の平均・SD。"""
    markers = list(dict.fromkeys(marker for row in rows for marker in row.rates))
    header = ["条件", "画像の枚数"]
    for marker in markers:
        header += [f"{marker} 平均 (%)", f"{marker} SD (%)"]
    table = []
    for condition in dict.fromkeys(row.condition for row in rows):
        group = [row for row in rows if row.condition == condition]
        line = [condition, len(group)]
        for marker in markers:
            rates = [row.rates[marker] for row in group if row.rates.get(marker) is not None]
            mean = round(statistics.mean(rates), 2) if rates else None
            deviation = round(statistics.stdev(rates), 2) if len(rates) > 1 else None
            line += [mean, deviation]
        table.append(line)
    return header, table


def _write_table(sheet, top: int, header: list[str], rows: list[list]) -> None:
    for column, text in enumerate(header, 1):
        cell = sheet.cell(top, column, text)
        cell.font = _BOLD
        sheet.column_dimensions[cell.column_letter].width = max(14, len(text) * 2)
    for offset, row in enumerate(rows, 1):
        for column, value in enumerate(row, 1):
            sheet.cell(top + offset, column, value)


def write_batch(rows: list[BatchRow], path: str) -> None:
    book = Workbook()
    images = book.active
    images.title = "Images"
    markers = list(dict.fromkeys(marker for row in rows for marker in row.rates))
    header = ["条件", "ファイル", "シーン", "総核数", *[f"{tab_name(m)} 陽性率 (%)" for m in markers],
              "暫定（陰性対照なし）", "警告の数", "結果のフォルダ"]
    _write_table(images, 1, header, [
        [row.condition, row.file, row.scene, row.total, *[row.rates.get(m) for m in markers],
         "はい" if row.provisional else "いいえ", row.warnings, row.folder] for row in rows])

    conditions = book.create_sheet("Conditions")
    header, table = condition_stats(rows)
    _write_table(conditions, 1, header, table)
    last = 1 + len(table)
    chart = BarChart()
    chart.type = "col"
    chart.title = "条件ごとの陽性率（平均 ± SD）"
    chart.y_axis.title = "%"
    chart.y_axis.scaling.min = 0
    chart.y_axis.scaling.max = 100
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    for number, marker in enumerate(markers):
        mean_column = 3 + 2 * number
        series = Series(Reference(conditions, min_col=mean_column, min_row=2, max_row=last),
                        title=marker)
        letter = conditions.cell(1, mean_column + 1).column_letter
        deviation = NumDataSource(numRef=NumRef(f=f"'Conditions'!${letter}$2:${letter}${last}"))
        series.errBars = ErrorBars(errDir="y", errBarType="both", errValType="cust",
                                   plus=deviation, minus=deviation)
        chart.series.append(series)
    chart.set_categories(Reference(conditions, min_col=1, min_row=2, max_row=last))
    chart.width, chart.height = 20, 10
    conditions.add_chart(chart, f"A{last + 3}")
    book.save(path)
