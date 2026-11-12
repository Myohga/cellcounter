"""チャンネル表の編集（DAPI の選択・マーカー名・染まる場所・判定の ON/OFF）。"""

from __future__ import annotations

from dataclasses import dataclass

from qtpy.QtCore import Signal
from qtpy.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QHeaderView,
                            QRadioButton, QTableWidget, QTableWidgetItem)

from ..channels import ChannelRow, ChannelTable
from ..markers import LOCATION_SPECS, guess_location

COLUMNS = ("チャンネル", "DAPI", "マーカー名", "染まる場所", "判定")
UNSELECTED = "（未選択）"


@dataclass
class _RowWidgets:
    row: ChannelRow
    dapi: QRadioButton
    name: QComboBox
    location: QComboBox
    judge: QCheckBox


class ChannelTableWidget(QTableWidget):
    """渡された ChannelTable をその場で書き換え、変わるたびに changed を出す。"""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__(0, len(COLUMNS))
        self.setHorizontalHeaderLabels(COLUMNS)
        self.verticalHeader().hide()
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setMinimumSectionSize(40)
        self.setMinimumWidth(460)
        self._table: ChannelTable | None = None
        self._names: list[str] = []
        self._widgets: list[_RowWidgets] = []
        self._group = QButtonGroup(self)

    def set_table(self, table: ChannelTable, marker_names: list[str]) -> None:
        self._table, self._names, self._widgets = table, marker_names, []
        self._group = QButtonGroup(self)
        self.setRowCount(len(table.rows))
        for position, row in enumerate(table.rows):
            wave = f"{row.emission_nm:.0f} nm" if row.emission_nm else "波長不明"
            item = QTableWidgetItem(f"{row.name}\n{row.dye or '色素不明'}・{wave}")
            self.setItem(position, 0, item)
            if row.fluorescence:
                self._add_editors(position, row)
            else:
                self.setSpan(position, 1, 1, len(COLUMNS) - 1)
                self.setItem(position, 1, QTableWidgetItem("蛍光ではないので使いません"))
        self.resizeRowsToContents()

    def _add_editors(self, position: int, row: ChannelRow) -> None:
        is_dapi = row.role == "dapi"
        dapi = QRadioButton()
        dapi.setChecked(is_dapi)
        self._group.addButton(dapi)

        name = QComboBox()
        name.setEditable(True)
        name.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        name.addItems(self._names)
        name.setCurrentText(row.marker)
        name.setMinimumWidth(120)

        location = QComboBox()
        location.addItem(UNSELECTED, "")
        for key, spec in LOCATION_SPECS.items():
            location.addItem(spec.label, key)
        location.setCurrentIndex(max(location.findData(row.location), 0))

        judge = QCheckBox()
        judge.setChecked(row.judge)

        widgets = _RowWidgets(row, dapi, name, location, judge)
        for editor in (name, location, judge):
            editor.setEnabled(not is_dapi)
        for column, editor in enumerate((dapi, name, location, judge), 1):
            self.setCellWidget(position, column, editor)
        self._widgets.append(widgets)

        dapi.toggled.connect(lambda checked, r=row: checked and self._choose_dapi(r))
        name.lineEdit().editingFinished.connect(lambda w=widgets: self._name_edited(w))
        name.activated.connect(lambda _index, w=widgets: self._name_edited(w))
        location.activated.connect(lambda _index, w=widgets: self._apply(w))
        judge.clicked.connect(lambda _checked, w=widgets: self._apply(w))

    def _choose_dapi(self, row: ChannelRow) -> None:
        self._table.set_dapi(row.index)
        self.set_table(self._table, self._names)
        self.changed.emit()

    def _name_edited(self, widgets: _RowWidgets) -> None:
        """名前が変わったら、辞書から染まる場所を引き直す。辞書に無ければ未選択に戻す。"""
        name = widgets.name.currentText().strip()
        if name == widgets.row.marker:
            return
        widgets.location.setCurrentIndex(max(widgets.location.findData(guess_location(name) or ""), 0))
        widgets.judge.setChecked(bool(name))
        self._apply(widgets)

    def _apply(self, widgets: _RowWidgets) -> None:
        row = widgets.row
        row.marker = widgets.name.currentText().strip()
        row.location = widgets.location.currentData()
        row.judge = widgets.judge.isChecked() and bool(row.marker)
        widgets.judge.setChecked(row.judge)
        self.changed.emit()
