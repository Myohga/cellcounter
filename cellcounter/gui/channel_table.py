"""チャンネル表の編集（核を数えるチャンネル・マーカー名・染まる場所・判定法・判定の ON/OFF）。"""

from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QHeaderView,
                            QRadioButton, QTableWidget, QTableWidgetItem)

from ..channels import ChannelRow, ChannelTable
from ..markers import (LOCATION_SPECS, METHOD_IMV, METHOD_RATE, METHODS, active_dictionary,
                       lookup, marker_key)

COLUMNS = ("チャンネル", "核を数える", "マーカー名", "染まる場所", "判定法", "判定")
UNSELECTED = "（未選択）"
DAPI_ROW_TEXT = "このチャンネルで核を検出して数えます（陽性率の分母）"
DAPI_TOOLTIP = ("核を検出して数えるチャンネルを 1 つ選びます（ふつうは DAPI / Hoechst）。\n"
                "画面に出す画像を選ぶボタンではありません。")
METHOD_TOOLTIP = ("陽性率: 核ごとに陽性・陰性を決めて数えます。\n"
                  "平均蛍光強度: ③ の「平均蛍光強度」のタブで範囲を描き、その中の明るさの平均を測ります"
                  "（ZEN の Intensity Mean Value）。染まる場所は使いません。")
NAME_TOOLTIP = ("マーカー名を入れるか、▼ から選びます。▼ の一覧で名前にポインターを合わせると、"
                "辞書のコメントが出ます（辞書は「操作 → 辞書登録」で編集できます）。")
LOCATION_UNUSED = "判定法が平均蛍光強度のときは、染まる場所は使いません。"
VISIBLE_NAMES = 20
NAME_COLUMN = 2
NAME_MIN_CHARS = 8      # マーカー名の欄に、少なくともこの文字数分の幅を取る
MIN_TABLE_WIDTH = 520


@dataclass
class _Editors:
    row: ChannelRow
    name: QComboBox
    location: QComboBox
    method: QComboBox
    judge: QCheckBox


def fill_marker_names(combo: QComboBox, used: list[str]) -> None:
    """マーカー名の ▼ の一覧。前に使った名前を先に、辞書の名前をあとに並べる。

    名前にポインターを合わせると、辞書のコメント（無ければ染まる場所と判定法）が出る。
    """
    dictionary = active_dictionary()
    used_keys = {marker_key(name) for name in used}
    known = sorted((entry.name for entry in dictionary.entries
                    if entry.key not in used_keys), key=str.casefold)
    combo.addItems(used)
    if used and known:
        combo.insertSeparator(combo.count())
    combo.addItems(known)
    for position in range(combo.count()):
        entry = dictionary.find(combo.itemText(position))
        if entry is not None:
            combo.setItemData(position, entry.describe(), Qt.ItemDataRole.ToolTipRole)
    combo.setMaxVisibleItems(VISIBLE_NAMES)


class ChannelTableWidget(QTableWidget):
    """渡された ChannelTable をその場で書き換え、変わるたびに changed を出す。"""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__(0, len(COLUMNS))
        self.setHorizontalHeaderLabels(COLUMNS)
        self.horizontalHeaderItem(1).setToolTip(DAPI_TOOLTIP)
        self.horizontalHeaderItem(4).setToolTip(METHOD_TOOLTIP)
        self.verticalHeader().hide()
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setMinimumSectionSize(40)
        self.setMinimumWidth(MIN_TABLE_WIDTH)
        self._table: ChannelTable | None = None
        self._names: list[str] = []
        self.dapi_buttons: dict[int, QRadioButton] = {}
        self.editors: dict[int, _Editors] = {}
        self._group = QButtonGroup(self)

    def set_table(self, table: ChannelTable, marker_names: list[str]) -> None:
        self._table, self._names = table, marker_names
        self.dapi_buttons, self.editors = {}, {}
        self._group = QButtonGroup(self)
        self.clearSpans()
        self.setRowCount(0)
        self.setRowCount(len(table.rows))
        for position, row in enumerate(table.rows):
            wave = f"{row.emission_nm:.0f} nm" if row.emission_nm else "波長不明"
            self.setItem(position, 0, QTableWidgetItem(f"{row.name}\n{row.dye or '色素不明'}・{wave}"))
            if not row.fluorescence:
                self.setSpan(position, 1, 1, len(COLUMNS) - 1)
                self.setItem(position, 1, QTableWidgetItem("蛍光ではないので判定には使いません"))
                continue
            button = QRadioButton()
            button.setChecked(row.role == "dapi")
            button.setToolTip(DAPI_TOOLTIP)
            button.toggled.connect(lambda checked, r=row: checked and self._choose_dapi(r))
            self._group.addButton(button)
            self.dapi_buttons[row.index] = button
            self.setCellWidget(position, 1, button)
            if row.role == "dapi":
                self.setSpan(position, 2, 1, len(COLUMNS) - 2)
                self.setItem(position, 2, QTableWidgetItem(DAPI_ROW_TEXT))
            else:
                self._add_editors(position, row)
        self.resizeRowsToContents()
        self._fit_width()

    def _fit_width(self) -> None:
        """マーカー名の列に必要な幅が残るよう、表の最小の幅を決める。

        ほかの列は中身に合わせて広がる（Windows の日本語フォントや表示の拡大では特に広い）。
        マーカー名の列はその残りなので、表の幅を固定すると縮みすぎて、名前の欄が隣の列に重なる。
        """
        header = self.horizontalHeader()
        others = sum(max(self.sizeHintForColumn(column), header.sectionSizeHint(column))
                     for column in range(self.columnCount()) if column != NAME_COLUMN)
        name = header.sectionSizeHint(NAME_COLUMN)
        for editors in self.editors.values():
            name = max(name, editors.name.minimumSizeHint().width())
        # 縦のスクロールバーが出ても足りるよう、その分も取っておく
        frame = 2 * self.frameWidth() + self.verticalScrollBar().sizeHint().width()
        self.setMinimumWidth(max(MIN_TABLE_WIDTH, others + name + frame))

    def _add_editors(self, position: int, row: ChannelRow) -> None:
        name = QComboBox()
        name.setEditable(True)
        name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        fill_marker_names(name, self._names)
        name.setCurrentText(row.marker)
        # 欄の幅を辞書のいちばん長い名前に合わせない（▼ の一覧は名前の長さに合わせて開く）。
        # 固定の最小幅も付けない。付けると、列がそれより狭いときに隣の列へはみ出す
        name.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        name.setMinimumContentsLength(NAME_MIN_CHARS)
        name.lineEdit().setPlaceholderText("例: MAP2")

        location = QComboBox()
        location.addItem(UNSELECTED, "")
        for key, spec in LOCATION_SPECS.items():
            location.addItem(spec.label, key)
        location.setCurrentIndex(max(location.findData(row.location), 0))

        method = QComboBox()
        for key, label in METHODS.items():
            method.addItem(label, key)
        method.setCurrentIndex(max(method.findData(row.method), 0))
        method.setToolTip(METHOD_TOOLTIP)

        judge = QCheckBox()
        judge.setChecked(row.judge)
        judge.setToolTip("ON にしたマーカーを、選んだ判定法で測ります"
                         "（陽性率なら組み合わせのタブを、平均蛍光強度なら「平均蛍光強度」のタブを作ります）。")

        editors = _Editors(row, name, location, method, judge)
        for column, editor in enumerate((name, location, method, judge), 2):
            self.setCellWidget(position, column, editor)
        self.editors[row.index] = editors
        self._show_state(editors)

        name.lineEdit().editingFinished.connect(lambda e=editors: self._name_edited(e))
        name.activated.connect(lambda _index, e=editors: self._name_edited(e))
        location.activated.connect(lambda _index, e=editors: self._apply(e))
        method.activated.connect(lambda _index, e=editors: self._apply(e))
        judge.clicked.connect(lambda _checked, e=editors: self._apply(e))

    def _choose_dapi(self, row: ChannelRow) -> None:
        """核を数えるチャンネルを変える。ほかの行に入れた名前や設定はそのまま残る。"""
        self._table.set_dapi(row.index)
        self.set_table(self._table, self._names)
        self.changed.emit()

    def _name_edited(self, editors: _Editors) -> None:
        """名前が変わったら、辞書から染まる場所と判定法を引き直す。辞書に無ければ未選択・陽性率。

        辞書で「核を数える」になっている名前なら、そのチャンネルを核を数えるチャンネルにする。
        """
        name = editors.name.currentText().strip()
        if name == editors.row.marker:
            return
        entry = lookup(name)
        location = entry.location if entry else ""
        method = METHOD_IMV if entry and entry.imv else METHOD_RATE
        editors.location.setCurrentIndex(max(editors.location.findData(location), 0))
        editors.method.setCurrentIndex(editors.method.findData(method))
        editors.judge.setChecked(bool(name))
        self._apply(editors)
        if entry and entry.counts_nuclei:
            self._choose_dapi(editors.row)

    def _apply(self, editors: _Editors) -> None:
        row = editors.row
        row.marker = editors.name.currentText().strip()
        row.location = editors.location.currentData()
        row.method = editors.method.currentData()
        row.judge = editors.judge.isChecked() and bool(row.marker)
        editors.judge.setChecked(row.judge)
        self._show_state(editors)
        self.changed.emit()

    @staticmethod
    def _show_state(editors: _Editors) -> None:
        """平均蛍光強度では染まる場所を使わないので、選べないようにする（値は残す）。"""
        rate = editors.row.method == METHOD_RATE
        editors.location.setEnabled(rate)
        editors.location.setToolTip("" if rate else LOCATION_UNUSED)
        entry = lookup(editors.row.marker) if editors.row.marker else None
        editors.name.setToolTip(entry.describe() if entry else NAME_TOOLTIP)
