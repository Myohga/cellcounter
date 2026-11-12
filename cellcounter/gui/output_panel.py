"""④ 出力: 出力先と [確定]、作業の保存。"""

from __future__ import annotations

from qtpy.QtCore import Signal
from qtpy.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                            QWidget)

from .shortcuts import button_text


class OutputPanel(QWidget):
    export_requested = Signal()
    save_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.folder = QLineEdit()
        browse = QPushButton("変更…")
        browse.clicked.connect(self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)

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
        layout.addWidget(QLabel("書き出すもの: results.xlsx（集計とグラフ）、"
                                "組み合わせごとの確認用画像、作業ファイル"))
        layout.addWidget(self.export_button)
        layout.addSpacing(16)
        layout.addWidget(QLabel("途中でやめるときは、作業を保存しておくと続きから開けます。"))
        layout.addWidget(self.save_button)
        layout.addWidget(self.result)
        layout.addStretch(1)
        self.set_ready(False)

    def set_ready(self, ready: bool) -> None:
        self.export_button.setEnabled(ready)
        self.save_button.setEnabled(ready)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "出力先のフォルダ", self.folder.text())
        if folder:
            self.folder.setText(folder)
