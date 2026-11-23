"""② 設定: チャンネル表・プリセット・陰性対照・検出の設定と、[判定] ボタン。"""

from __future__ import annotations

import os

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                            QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
                            QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..channels import ChannelTable, apply_preset, preset_of
from ..czi import list_scenes
from ..settings import Settings
from ..userdata import UserData
from .channel_table import ChannelTableWidget
from .shortcuts import button_text

PERCENTILES = (99.0, 95.0)


def _spin(low: float, high: float, step: float, decimals: int, value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setSingleStep(step)
    box.setDecimals(decimals)
    box.setValue(value)
    return box


class SetupPanel(QWidget):
    changed = Signal()
    judge_requested = Signal()

    def __init__(self, userdata: UserData) -> None:
        super().__init__()
        self._userdata = userdata
        self._table: ChannelTable | None = None
        defaults = Settings()

        self.table_widget = ChannelTableWidget()
        self.table_widget.changed.connect(self._on_changed)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setStyleSheet("color: #c00000;")
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setStyleSheet("color: #a05a00;")

        self.presets = QComboBox()
        apply_button = QPushButton("適用")
        apply_button.clicked.connect(self._apply_preset)
        save_button = QPushButton("名前を付けて保存…")
        save_button.clicked.connect(self._save_preset)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("プリセット"))
        preset_row.addWidget(self.presets, 1)
        preset_row.addWidget(apply_button)
        preset_row.addWidget(save_button)

        self.controls = QListWidget()
        self.controls.setMaximumHeight(90)
        add_button = QPushButton("追加…")
        add_button.clicked.connect(self._add_controls)
        remove_button = QPushButton("選んだ行を外す")
        remove_button.clicked.connect(self._remove_controls)
        self.percentile = QComboBox()
        for value in PERCENTILES:
            self.percentile.addItem(f"{value:g} パーセンタイル", value)
        self.percentile.activated.connect(lambda _index: self.changed.emit())
        self.control_hint = QLabel()
        self.control_hint.setWordWrap(True)
        control_buttons = QHBoxLayout()
        control_buttons.addWidget(add_button)
        control_buttons.addWidget(remove_button)
        control_buttons.addWidget(QLabel("閾値"))
        control_buttons.addWidget(self.percentile)
        control_box = QGroupBox("陰性対照（二次抗体のみ、または陰性の細胞を染めた .czi）")
        control_layout = QVBoxLayout(control_box)
        control_layout.addWidget(self.controls)
        control_layout.addLayout(control_buttons)
        control_layout.addWidget(self.control_hint)

        detection = defaults.detection
        self.diameter = _spin(0.0, 50.0, 0.5, 1, 0.0)
        self.diameter.setSpecialValueText("自動")
        self.clip_white = _spin(0.05, 1.0, 0.05, 2, detection.clip_white)
        self.cellprob = _spin(-6.0, 6.0, 0.5, 1, detection.cellprob_threshold)
        self.flow = _spin(0.0, 3.0, 0.1, 1, detection.flow_threshold)
        detection_box = QGroupBox("核の検出")
        form = QFormLayout(detection_box)
        form.addRow("核の直径 (µm)", self.diameter)
        form.addRow("DAPI の白点（全階調比）", self.clip_white)
        form.addRow("cellprob の閾値", self.cellprob)
        form.addRow("flow の閾値", self.flow)
        for box in (self.diameter, self.clip_white, self.cellprob, self.flow):
            box.valueChanged.connect(lambda _value: self.changed.emit())

        self.judge_button = QPushButton(button_text("judge"))
        self.judge_button.setMinimumHeight(36)
        self.judge_button.clicked.connect(self.judge_requested)

        guide = QLabel(
            "● を付けたチャンネルで核を検出して数えます（陽性率の分母。ふつうは DAPI / Hoechst）。"
            "ほかのチャンネルには、マーカー名を入れて「判定」に ✓ を付けます。\n"
            "判定法は「陽性率」（核ごとに陽性・陰性を数える）か「平均蛍光強度」（範囲の明るさの平均。"
            "ZEN の Intensity Mean Value）を選べます。AT8 などのタウのマーカーは、自動で平均蛍光強度になります。\n"
            "画面に重ねる画像は、ここではなく「③ 判定・修正」で選べます。")
        guide.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(guide)
        layout.addWidget(self.table_widget, 1)
        layout.addWidget(self.problems)
        layout.addWidget(self.warnings)
        layout.addLayout(preset_row)
        layout.addWidget(control_box)
        layout.addWidget(detection_box)
        layout.addWidget(self.judge_button)
        self._refresh_presets()
        self._on_changed(notify=False)

    def set_table(self, table: ChannelTable) -> None:
        self._table = table
        self.table_widget.set_table(table, self._userdata.marker_names)
        self._on_changed(notify=False)

    def reload_names(self) -> None:
        """マーカー辞書を編集したあと、▼ の一覧とコメントを作り直す（入れてある値は変えない）。"""
        if self._table is not None:
            self.table_widget.set_table(self._table, self._userdata.marker_names)

    def show_warnings(self, warnings: list[str]) -> None:
        """読み込み時の警告（階調の不足など）を、判定の前から見えるようにする。"""
        self.warnings.setText("\n".join(f"警告: {text}" for text in warnings))
        self.warnings.setVisible(bool(warnings))

    def show_settings(self, settings: Settings) -> None:
        """作業ファイルから開いたとき、保存されていた設定を表示に戻す。"""
        detection = settings.detection
        pairs = ((self.diameter, detection.nucleus_diameter_um or 0.0),
                 (self.clip_white, detection.clip_white),
                 (self.cellprob, detection.cellprob_threshold), (self.flow, detection.flow_threshold))
        for box, value in pairs:
            box.blockSignals(True)
            box.setValue(value)
            box.blockSignals(False)
        index = self.percentile.findData(settings.judge.control_percentile)
        if index < 0:
            self.percentile.addItem(f"{settings.judge.control_percentile:g} パーセンタイル",
                                    settings.judge.control_percentile)
            index = self.percentile.count() - 1
        self.percentile.setCurrentIndex(index)

    def apply_to(self, settings: Settings) -> None:
        """画面の値を設定に書き込む。"""
        detection = settings.detection
        detection.nucleus_diameter_um = self.diameter.value() or None
        detection.clip_white = self.clip_white.value()
        detection.cellprob_threshold = self.cellprob.value()
        detection.flow_threshold = self.flow.value()
        settings.judge.control_percentile = self.percentile.currentData()

    def control_sources(self) -> list[tuple[str, int]]:
        return [tuple(self.controls.item(row).data(Qt.ItemDataRole.UserRole))
                for row in range(self.controls.count())]

    def set_control_sources(self, sources: list[tuple[str, int]]) -> None:
        """作業ファイルから開いたとき、判定に使った陰性対照の一覧を戻す。"""
        self.controls.clear()
        for path, scene in sources:
            self._add_control(path, scene)
        self._on_changed(notify=False)

    def _add_control(self, path: str, scene: int) -> None:
        item = QListWidgetItem(f"{os.path.basename(path)}（シーン {scene}）")
        item.setToolTip(path)
        item.setData(Qt.ItemDataRole.UserRole, (path, scene))
        self.controls.addItem(item)

    def _on_changed(self, notify: bool = True) -> None:
        problems = self._table.problems() if self._table else []
        self.problems.setText("\n".join(problems))
        self.problems.setVisible(bool(problems))
        self.judge_button.setEnabled(self._table is not None and not problems)
        if self.controls.count():
            self.control_hint.setText("陰性対照の細胞の値から閾値を決めます。")
        else:
            self.control_hint.setText("陰性対照が無いので、固定の閾値で判定します。"
                                      "結果は「暫定」と表示されます。")
        if notify:
            self.changed.emit()

    def _refresh_presets(self) -> None:
        self.presets.clear()
        self.presets.addItems(self._userdata.preset_names())

    def _apply_preset(self) -> None:
        name = self.presets.currentText()
        if not name or self._table is None:
            return
        try:
            apply_preset(self._table, self._userdata.load_preset(name))
        except ValueError as error:
            QMessageBox.warning(self, "プリセットを適用できません", str(error))
        self.table_widget.set_table(self._table, self._userdata.marker_names)
        self._on_changed()

    def _save_preset(self) -> None:
        if self._table is None:
            return
        name, accepted = QInputDialog.getText(self, "プリセットを保存", "プリセットの名前")
        if not accepted or not name.strip():
            return
        try:
            self._userdata.save_preset(preset_of(self._table, name.strip()))
        except ValueError as error:
            QMessageBox.warning(self, "プリセットを保存できません", str(error))
            return
        self._refresh_presets()
        self.presets.setCurrentText(name.strip())

    def _add_controls(self) -> None:
        """選んだファイルの全シーンを 1 行ずつ足す。使わないシーンは行ごと外せる。"""
        paths, _ = QFileDialog.getOpenFileNames(self, "陰性対照の .czi を選ぶ", "", "CZI (*.czi)")
        existing = set(self.control_sources())
        for path in paths:
            try:
                scenes = list_scenes(path)
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, "陰性対照を読めません", f"{path}\n{error}")
                continue
            for scene in scenes:
                if (os.path.abspath(path), scene.index) not in existing:
                    self._add_control(os.path.abspath(path), scene.index)
        self._on_changed()

    def _remove_controls(self) -> None:
        for item in self.controls.selectedItems():
            self.controls.takeItem(self.controls.row(item))
        self._on_changed()
