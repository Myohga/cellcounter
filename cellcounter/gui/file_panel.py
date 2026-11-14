"""① ファイル: 開く・最近使ったファイル・シーンの選択。"""

from __future__ import annotations

import os

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget,
                            QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..czi import SceneInfo
from ..settings import Z_PROJECTIONS
from .shortcuts import button_text

_Z_LABELS = {"max": "最大値投影", "mean": "平均投影", "best": "いちばん明るい 1 枚"}
PLANE = "plane"


class FilePanel(QWidget):
    open_requested = Signal()
    open_project_requested = Signal()
    recent_chosen = Signal(str)
    load_requested = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self._path = ""
        open_button = QPushButton(button_text("open"))
        open_button.clicked.connect(self.open_requested)
        project_button = QPushButton(button_text("open_project"))
        project_button.clicked.connect(self.open_project_requested)

        self.recent = QListWidget()
        self.recent.itemActivated.connect(lambda item: self.recent_chosen.emit(
            item.data(Qt.ItemDataRole.UserRole)))

        self.file_label = QLabel("（まだ開いていません）")
        self.file_label.setWordWrap(True)
        self.scene = QComboBox()
        self.z = QComboBox()
        for key in Z_PROJECTIONS:
            self.z.addItem(_Z_LABELS[key], key)
        self.z.addItem("枚数を指定して 1 枚だけ使う →", PLANE)
        self.z_plane = QSpinBox()
        self.z_plane.setMinimum(1)
        self.z_plane.setSuffix(" 枚目")
        self.z.currentIndexChanged.connect(self._sync_z)
        self.scene.currentIndexChanged.connect(self._sync_z)
        z_row = QHBoxLayout()
        z_row.addWidget(self.z, 1)
        z_row.addWidget(self.z_plane)
        self.load_button = QPushButton("このシーンを読み込む")
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self._load)
        self.info = QLabel()
        self.info.setWordWrap(True)

        form = QFormLayout()
        form.addRow("ファイル", self.file_label)
        form.addRow("シーン", self.scene)
        form.addRow("Z の重ね方", z_row)

        layout = QVBoxLayout(self)
        layout.addWidget(open_button)
        layout.addWidget(project_button)
        layout.addWidget(QLabel(".czi はウィンドウにドラッグ＆ドロップしても開けます。"))
        layout.addWidget(QLabel("最近使ったファイル（ダブルクリックで開く）"))
        layout.addWidget(self.recent, 1)
        layout.addLayout(form)
        layout.addWidget(self.load_button)
        layout.addWidget(self.info)
        self._sync_z()

    def z_projection(self) -> str:
        """max / mean / best か、'plane:3'（3 枚目だけ）。"""
        if self.z.currentData() == PLANE:
            return f"{PLANE}:{self.z_plane.value()}"
        return self.z.currentData()

    def _sync_z(self, *_ignored) -> None:
        """枚数の欄は「1 枚だけ使う」のときだけ有効にし、上限を選んだシーンの Z の枚数にする。"""
        sizes = self.scene.currentData(Qt.ItemDataRole.UserRole + 1) or {}
        self.z_plane.setMaximum(max(1, sizes.get("Z", 1)))
        self.z_plane.setEnabled(self.z.currentData() == PLANE)

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        for path in paths:
            item = QListWidgetItem(os.path.basename(path))
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.recent.addItem(item)

    def set_scenes(self, path: str, scenes: list[SceneInfo]) -> None:
        """ファイルの中にある実際のシーンを並べる。"""
        self._path = path
        self.file_label.setText(os.path.basename(path))
        self.scene.clear()
        for scene in scenes:
            sizes = " ".join(f"{axis}={size}" for axis, size in scene.sizes.items())
            self.scene.addItem(f"{scene.index}: {scene.name}（{sizes}）", scene.index)
            self.scene.setItemData(self.scene.count() - 1, scene.sizes, Qt.ItemDataRole.UserRole + 1)
        self.load_button.setEnabled(bool(scenes))

    def show_loaded(self, path: str, scene: int, z_projection: str, info: str) -> None:
        """作業ファイルから開いたときなど、読み込み済みの内容を表示に反映する。"""
        self._path = path
        self.file_label.setText(os.path.basename(path))
        self.scene.setCurrentIndex(max(self.scene.findData(scene), 0))
        mode, _, plane = z_projection.partition(":")
        self.z.setCurrentIndex(max(self.z.findData(mode), 0))
        if plane:
            self.z_plane.setValue(int(plane))
        self.info.setText(info)

    def _load(self) -> None:
        self.load_requested.emit(self._path, self.scene.currentData(), self.z_projection())
