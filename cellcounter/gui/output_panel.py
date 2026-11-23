"""④ 出力: 出力先・結果ファイルの名前と [確定]、作業の保存。"""

from __future__ import annotations

from qtpy.QtCore import Signal
from qtpy.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                            QWidget)

from ..export import RESULTS_STEM, results_name
from .shortcuts import button_text


class OutputPanel(QWidget):
    export_requested = Signal()
    save_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._ready = False
        self.folder = QLineEdit()
        browse = QPushButton("変更…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)

        self.name = QLineEdit()
        self.name.setPlaceholderText(f"空欄なら {results_name()}")
        self.name.setToolTip("入れた名前の後ろに、_result_<出力した日付>.xlsx が付きます。")
        self.name.textChanged.connect(lambda _text: self._show_name())
        self.name_preview = QLabel()
        self.name_preview.setWordWrap(True)

        self.export_button = QPushButton(button_text("export"))
        self.export_button.setMinimumHeight(36)
        self.export_button.clicked.connect(self.export_requested)
        self.save_button = QPushButton(button_text("save_project"))
        self.save_button.clicked.connect(self.save_requested)
        self.result = QLabel()
        self.result.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("出力先のフォルダ（[確定] を押したときに作ります）"))
        layout.addLayout(folder_row)
        layout.addWidget(QLabel(f"結果ファイルの名前（後ろに _{RESULTS_STEM}_<日付>.xlsx が付きます）"))
        layout.addWidget(self.name)
        layout.addWidget(self.name_preview)
        layout.addWidget(QLabel("書き出すもの: 結果の Excel（集計とグラフ）、"
                                "組み合わせごとの確認用画像、作業ファイル"))
        layout.addWidget(self.export_button)
        layout.addSpacing(16)
        layout.addWidget(QLabel("途中でやめるときは、作業を保存しておくと続きから開けます。"))
        layout.addWidget(self.save_button)
        layout.addWidget(self.result)
        layout.addStretch(1)
        self.set_ready(False)

    def file_name(self) -> str:
        """書き出す Excel の名前。名前に使えない文字があれば ValueError。"""
        return results_name(self.name.text())

    def _show_name(self) -> bool:
        try:
            name = self.file_name()
        except ValueError as error:
            self.name_preview.setText(str(error))
            self.name_preview.setStyleSheet("color: #c00000;")
            valid = False
        else:
            self.name_preview.setText(f"書き出すファイル: {name}")
            self.name_preview.setStyleSheet("")
            valid = True
        self.export_button.setEnabled(self._ready and valid)
        return valid

    def set_ready(self, ready: bool) -> None:
        self._ready = ready
        self._show_name()
        self.save_button.setEnabled(ready)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "出力先のフォルダ", self.folder.text())
        if folder:
            self.folder.setText(folder)
