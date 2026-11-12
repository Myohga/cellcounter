"""results.xlsx の出力（グラフは Excel 上で編集できるもの）。"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference, Series
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from .session import Session
from .tally import cell_table, coexpression, notes, settings_record, summarize

PROVISIONAL = ("暫定（陰性対照なし）: 固定の閾値で判定しています。"
               "陰性対照を指定して判定し直すまで、陽性率は参考値です。")
SUMMARY_HEADER = ["組み合わせ", "総核数", "陽性数（× の数）", "自動判定のみの陽性数", "人が足した数",
                  "人が消した数", "判定不能", "自動判定の陽性率 (%)", "確定後の陽性率 (%)"]
TABLE_TOP = 4
_BOLD = Font(bold=True)


def _start(sheet: Worksheet, title: str, session: Session) -> None:
    sheet.title = title
    sheet["A1"] = title
    sheet["A1"].font = _BOLD
    if session.provisional:
        sheet["A2"] = PROVISIONAL
        sheet["A2"].font = Font(bold=True, color="C00000")


def _table(sheet: Worksheet, header: list[str], rows: list[list]) -> int:
    """TABLE_TOP の行から表を書き、最後の行番号を返す。"""
    for column, text in enumerate(header, 1):
        cell = sheet.cell(TABLE_TOP, column, text)
        cell.font = _BOLD
        sheet.column_dimensions[cell.column_letter].width = max(12, len(text) * 2)
    for offset, row in enumerate(rows, 1):
        for column, value in enumerate(row, 1):
            sheet.cell(TABLE_TOP + offset, column, value)
    return TABLE_TOP + len(rows)


def _percent_chart(sheet: Worksheet, title: str, first: int, last: int, columns: list[int],
                   anchor: str) -> None:
    chart = BarChart()
    chart.type = "col"
    chart.title = title
    chart.y_axis.title = "%"
    chart.y_axis.scaling.min = 0
    chart.y_axis.scaling.max = 100
    # openpyxl は軸を既定で「削除」として書き出すため、明示しないと Excel で軸が出ない
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    for column in columns:
        values = Reference(sheet, min_col=column, min_row=first, max_row=last)
        chart.series.append(Series(values, title=sheet.cell(TABLE_TOP, column).value))
    chart.set_categories(Reference(sheet, min_col=1, min_row=first, max_row=last))
    chart.width, chart.height = 18, 9
    sheet.add_chart(chart, anchor)


def _summary(sheet: Worksheet, session: Session) -> None:
    _start(sheet, "Summary", session)
    rows = [[r.name, r.total, r.positive, r.auto_positive, r.added, r.removed, r.undetermined,
             r.auto_rate, r.rate] for r in summarize(session)]
    last = _table(sheet, SUMMARY_HEADER, rows)
    for offset, note in enumerate(notes(session), 2):
        sheet.cell(last + offset, 1, f"注: {note}")
    if len(rows) > 1:
        # 1 行目は「DAPI のみ」で陽性率が無いので、グラフはマーカーの行から
        _percent_chart(sheet, "陽性率（自動判定と確定後）", TABLE_TOP + 2, last, [8, 9], "K4")


def _coexpression(sheet: Worksheet, session: Session) -> None:
    _start(sheet, "Coexpression", session)
    rows = [[r.name, r.cells, r.rate] for r in coexpression(session)]
    last = _table(sheet, ["組み合わせ", "細胞数", "割合 (%)"], rows)
    if rows:
        _percent_chart(sheet, "共発現（数える核に占める割合）", TABLE_TOP + 1, last, [3], "E4")


def _cells(sheet: Worksheet, session: Session) -> None:
    _start(sheet, "Cells", session)
    header, rows = cell_table(session)
    _table(sheet, header, rows)
    sheet.freeze_panes = sheet.cell(TABLE_TOP + 1, 2)


def _settings(sheet: Worksheet, session: Session) -> None:
    _start(sheet, "Settings", session)
    _table(sheet, ["項目", "値"], [list(pair) for pair in settings_record(session)])
    sheet.column_dimensions["A"].width = 44
    sheet.column_dimensions["B"].width = 90


def write_results(session: Session, path: str) -> None:
    book = Workbook()
    _summary(book.active, session)
    _coexpression(book.create_sheet(), session)
    _cells(book.create_sheet(), session)
    _settings(book.create_sheet(), session)
    book.save(path)
