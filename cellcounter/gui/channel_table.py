"""チャンネル表の編集（核を数えるチャンネル・マーカー名・染まる場所・判定の ON/OFF）。"""

from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Signal
from qtpy.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QHeaderView,
                            QRadioButton, QTableWidget, QTableWidgetItem)

from ..channels import ChannelRow, ChannelTable
from ..markers import LOCATION_SPECS, guess_location

COLUMNS = ("チャンネル", "核を数える", "マーカー名", "染まる場所", "判定")
UNSELECTED = "（未選択）"
DAPI_ROW_TEXT = "このチャンネルで核を検出して数えます（陽性率の分母）"
DAPI_TOOLTIP = ("核を検出して数えるチャンネルを 1 つ選びます（ふつうは DAPI / Hoechst）。\n"
                "画面に出す画像を選ぶボタンではありません。")


@dataclass
class _Editors:
    row: ChannelRow
    name: QComboBox
    location: QComboBox
    judge: QCheckBox


class ChannelTableWidget(QTableWidget):
    """渡された ChannelTable をその場で書き換え、変わるたびに changed を出す。"""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__(0, len(COLUMNS))
        self.setHorizontalHeaderLabels(COLUMNS)
        self.horizontalHeaderItem(1).setToolTip(DAPI_TOOLTIP)
        self.verticalHeader().hide()
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setMinimumSectionSize(40)
        self.setMinimumWidth(460)
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

    def _add_editors(self, position: int, row: ChannelRow) -> None:
        name = QComboBox()
        name.setEditable(True)
        name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        name.addItems(self._names)
        name.setCurrentText(row.marker)
        name.setMinimumWidth(120)
        name.lineEdit().setPlaceholderText("例: MAP2")

        location = QComboBox()
        location.addItem(UNSELECTED, "")
        for key, spec in LOCATION_SPECS.items():
            location.addItem(spec.label, key)
        location.setCurrentIndex(max(location.findData(row.location), 0))

        judge = QCheckBox()
        judge.setChecked(row.judge)
        judge.setToolTip("ON にしたマーカーを自動判定し、組み合わせのタブを作ります。")

        editors = _Editors(row, name, location, judge)
        for column, editor in enumerate((name, location, judge), 2):
            self.setCellWidget(position, column, editor)
        self.editors[row.index] = editors

        name.lineEdit().editingFinished.connect(lambda e=editors: self._name_edited(e))
        name.activated.connect(lambda _index, e=editors: self._name_edited(e))
        location.activated.connect(lambda _index, e=editors: self._apply(e))
        judge.clicked.connect(lambda _checked, e=editors: self._apply(e))

    def _choose_dapi(self, row: ChannelRow) -> None:
        """核を数えるチャンネルを変える。ほかの行に入れた名前や設定はそのまま残る。"""
        self._table.set_dapi(row.index)
        self.set_table(self._table, self._names)
        self.changed.emit()

    def _name_edited(self, editors: _Editors) -> None:
        """名前が変わったら、辞書から染まる場所を引き直す。辞書に無ければ未選択に戻す。"""
        name = editors.name.currentText().strip()
        if name == editors.row.marker:
            return
        guessed = guess_location(name) or ""
        editors.location.setCurrentIndex(max(editors.location.findData(guessed), 0))
        editors.judge.setChecked(bool(name))
        self._apply(editors)

    def _apply(self, editors: _Editors) -> None:
        row = editors.row
        row.marker = editors.name.currentText().strip()
        row.location = editors.location.currentData()
        row.judge = editors.judge.isChecked() and bool(row.marker)
        editors.judge.setChecked(row.judge)
        self.changed.emit()
