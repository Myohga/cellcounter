"""一括処理で判定する画像と、条件の名前・出力先を決めるダイアログ。"""

from __future__ import annotations

import os

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView,
                            QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                            QTableWidgetItem, QVBoxLayout, QWidget)

from ..batch import BatchItem, list_items

HEADER = ("条件（書き換えられます）", "ファイル", "シーン")


class BatchDialog(QDialog):
    def __init__(self, parent: QWidget, default_folder: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("一括処理")
        self.resize(760, 480)
        self._items: list[BatchItem] = []

        guide = QLabel(
            "いま開いている画像と同じチャンネル表・設定・陰性対照で、下の画像をすべて判定します。\n"
            "条件が同じ画像は、まとめの Excel で平均 ± SD になります。"
            "× の修正は、あとで画像ごとの作業ファイルを開いて行います。")
        guide.setWordWrap(True)
        self.table = QTableWidget(0, len(HEADER))
        self.table.setHorizontalHeaderLabels(HEADER)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        buttons = QHBoxLayout()
        for text, run in (("ファイルを追加…", self._add_files), ("フォルダを追加…", self._add_folder),
                          ("選んだ行を外す", self._remove)):
            button = QPushButton(text)
            button.clicked.connect(run)
            buttons.addWidget(button)
        buttons.addStretch(1)

        self.folder = QLineEdit(default_folder)
        browse = QPushButton("変更…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("出力先"))
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)

        self.box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                    | QDialogButtonBox.StandardButton.Cancel)
        self.box.button(QDialogButtonBox.StandardButton.Ok).setText("一括処理を始める")
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(guide)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addLayout(folder_row)
        layout.addWidget(self.box)
        self._refresh()

    def items(self) -> list[BatchItem]:
        """表に入力された条件の名前を反映した、判定する画像の一覧。"""
        return [BatchItem(item.path, item.scene, self.table.item(row, 0).text().strip())
                for row, item in enumerate(self._items)]

    def add(self, paths: list[str]) -> None:
        try:
            found = list_items(paths)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "画像を読めません", str(error))
            return
        known = {(item.path, item.scene) for item in self._items}
        self._items += [item for item in found if (item.path, item.scene) not in known]
        self._refresh()

    def _refresh(self) -> None:
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            self.table.setItem(row, 0, QTableWidgetItem(item.condition))
            for column, text in ((1, os.path.basename(item.path)), (2, str(item.scene))):
                cell = QTableWidgetItem(text)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, cell)
        self.box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self._items))

    def _keep_names(self) -> None:
        """表を作り直す前に、書き換えられた条件の名前を控える。"""
        self._items = self.items()

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "判定する .czi を選ぶ", "", "CZI (*.czi)")
        self._keep_names()
        self.add(paths)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, ".czi の入ったフォルダを選ぶ")
        if folder:
            self._keep_names()
            self.add([folder])

    def _remove(self) -> None:
        self._keep_names()
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            del self._items[row]
        self._refresh()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "出力先のフォルダ", self.folder.text())
        if folder:
            self.folder.setText(folder)
