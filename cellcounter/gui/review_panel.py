"""③ 判定・修正: 背景に出す画像の選択・件数・凡例・元に戻す／やり直し・警告。"""

from __future__ import annotations

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (QButtonGroup, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout,
                            QHeaderView, QLabel, QPlainTextEdit, QPushButton, QTableWidget,
                            QTableWidgetItem, QVBoxLayout, QWidget)
from superqt import QRangeSlider

from ..marks import ADDED, AUTO, REMOVED
from ..overlay import CAPTIONS, COLORS
from ..quality import full_scale
from ..session import IMV_TAB, Session
from ..tally import agreement, summarize
from .shortcuts import button_text

HEADER = ("組み合わせ", "総核数", "陽性数", "陽性率", "足した", "消した", "判定不能")
HINT_DAPI = ("「DAPI のみ」: × は数える核です。× をクリック → 数えない。"
             "× の無い核をクリック → 数える。何も無い場所をクリック → 円い核を作る。")
HINT_MARKER = ("「DAPI＋{marker}」: × は {marker} 陽性の核です。× をクリック → 陰性。"
               "× の無い核をクリック → 陽性。何も無い場所をクリック → 円い核を作って陽性。")
HINT_BEFORE = "② 設定 でチャンネル表を決め、[判定] を押してください。"
HINT_BLIND = ("目視判定モード「DAPI＋{marker}」: 自動判定は隠しています。{marker} 陽性だと思う核を"
              "クリックして × を付けてください（もう一度クリックで外す）。"
              "終わったらチェックを外すと、自動判定との一致率が出ます。")
HINT_IMV = ("「平均蛍光強度」: 範囲を描くと、その中の画素の明るさの平均（ZEN の Intensity Mean Value と"
            "同じ求め方）を測ります。範囲が無いときは画像全体を測ります。"
            "下の「測る範囲」で描き方を選んでください。")
# ③ のボタン（キーは canvas.REGION_MODES と同じ）
REGION_TOOLS = (("pan", "画像を動かす"), ("select", "選ぶ・動かす・大きさを変える"),
                ("rectangle", "四角形"), ("ellipse", "円・楕円"), ("polygon", "多角形"),
                ("lasso", "フリーハンド"))
REGION_HELP = ("四角形・円・楕円: ドラッグで描く（Shift を押しながらで正方形・正円）。"
               "多角形: クリックで頂点を置き、ダブルクリックか Enter で閉じる。"
               "フリーハンド: ドラッグでなぞり、離すと閉じる。"
               "描いた範囲は「選ぶ・動かす・大きさを変える」で動かしたり、角を引いて大きさを変えたりできます。"
               "範囲が 2 つ以上あるときは、範囲ごとの値と、すべてを合わせた値が出ます。元に戻す（Ctrl+Z）も効きます。")
IMV_CAPTION = "平均蛍光強度（範囲の中の画素の明るさの平均。背景は引いていません）"


class ReviewPanel(QWidget):
    undo_requested = Signal()
    redo_requested = Signal()
    contrast_changed = Signal(int, float, float)
    channel_toggled = Signal(int, bool)
    marks_toggled = Signal(bool)
    blind_toggled = Signal(bool)
    region_mode_requested = Signal(str)
    delete_regions_requested = Signal()
    clear_regions_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.channel_box = QGroupBox("背景に表示する画像（チェックで重ねる。組み合わせのタブごとに覚えます）")
        self.channel_grid = QGridLayout(self.channel_box)
        self.checks: dict[int, QCheckBox] = {}

        self.marks_check = QCheckBox("× を表示する（外すと、× の下の細胞が見えます）")
        self.marks_check.setChecked(True)
        self.marks_check.clicked.connect(self.marks_toggled)

        self.blind_check = QCheckBox("目視判定モード（自動判定を隠して、自分で × を付けて比べる）")
        self.blind_check.clicked.connect(self.blind_toggled)
        self.agreement_label = QLabel()
        self.agreement_label.setWordWrap(True)

        self.hint = QLabel(HINT_BEFORE)
        self.hint.setWordWrap(True)
        self.legend = QWidget()
        legend = QHBoxLayout(self.legend)
        legend.setContentsMargins(0, 0, 0, 0)
        for kind in (AUTO, ADDED, REMOVED):
            red, green, blue = COLORS[kind]
            label = QLabel(CAPTIONS[kind])
            label.setStyleSheet(f"color: rgb({red},{green},{blue}); background: #202020;"
                                "font-weight: bold; padding: 3px;")
            legend.addWidget(label)

        self.summary = QTableWidget(0, len(HEADER))
        self.summary.setHorizontalHeaderLabels(HEADER)
        self.summary.verticalHeader().hide()
        self.summary.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.summary.setMinimumHeight(170)

        self.region_box = QGroupBox("測る範囲（平均蛍光強度）")
        region_layout = QGridLayout(self.region_box)
        self.region_buttons: dict[str, QPushButton] = {}
        self._region_group = QButtonGroup(self)
        self._region_group.setExclusive(True)
        for position, (key, text) in enumerate(REGION_TOOLS):
            button = QPushButton(text)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, k=key: self.region_mode_requested.emit(k))
            self._region_group.addButton(button)
            self.region_buttons[key] = button
            region_layout.addWidget(button, position // 3, position % 3)
        self.region_buttons["pan"].setChecked(True)
        self.delete_region_button = QPushButton("選んだ範囲を消す（Delete）")
        self.delete_region_button.clicked.connect(self.delete_regions_requested)
        self.clear_regions_button = QPushButton("すべて消す（画像全体を測る）")
        self.clear_regions_button.clicked.connect(self.clear_regions_requested)
        region_layout.addWidget(self.delete_region_button, 2, 0, 1, 2)
        region_layout.addWidget(self.clear_regions_button, 2, 2)
        region_help = QLabel(REGION_HELP)
        region_help.setWordWrap(True)
        region_layout.addWidget(region_help, 3, 0, 1, 3)

        self.intensity_label = QLabel(IMV_CAPTION)
        self.intensity_label.setWordWrap(True)
        self.intensity = QTableWidget(0, 0)
        self.intensity.verticalHeader().hide()
        self.intensity.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.intensity.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.intensity.setMinimumHeight(110)

        self.undo_button = QPushButton(button_text("undo"))
        self.undo_button.clicked.connect(self.undo_requested)
        self.redo_button = QPushButton(button_text("redo"))
        self.redo_button.clicked.connect(self.redo_requested)
        history = QHBoxLayout()
        history.addWidget(self.undo_button)
        history.addWidget(self.redo_button)

        self.warnings = QPlainTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setMaximumHeight(120)

        layout = QVBoxLayout(self)
        layout.addWidget(self.channel_box)
        layout.addWidget(self.marks_check)
        layout.addWidget(self.blind_check)
        layout.addWidget(self.hint)
        # 平均蛍光強度のタブでは × を描かないので、× の凡例・件数の代わりに範囲の道具と値を出す
        layout.addWidget(self.region_box)
        layout.addWidget(self.intensity_label)
        layout.addWidget(self.intensity, 1)
        layout.addWidget(self.legend)
        layout.addWidget(self.summary, 1)
        layout.addWidget(self.agreement_label)
        layout.addLayout(history)
        layout.addWidget(QLabel("警告"))
        layout.addWidget(self.warnings)
        self.refresh(None, None)

    def show_session(self, session: Session) -> None:
        """画像が変わったとき、チャンネルごとの「表示」と明るさのスライダーを作り直す。"""
        while self.channel_grid.count():
            self.channel_grid.takeAt(0).widget().deleteLater()
        self.checks = {}
        full = int(full_scale(session.bits))
        self.channel_grid.addWidget(QLabel("表示"), 0, 0, 1, 2)
        self.channel_grid.addWidget(QLabel("明るさ（表示だけ。判定には影響しません）"), 0, 2)
        for position, row in enumerate(session.table.rows, 1):
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(f"background: {row.color}; border: 1px solid #606060;")
            check = QCheckBox(row.title)
            check.clicked.connect(
                lambda checked, index=row.index: self.channel_toggled.emit(index, checked))
            slider = QRangeSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, full)
            slider.setValue(tuple(round(value) for value in session.contrast_limits(row.index)))
            slider.valueChanged.connect(
                lambda value, index=row.index: self.contrast_changed.emit(
                    index, float(value[0]), float(max(value[1], value[0] + 1))))
            self.checks[row.index] = check
            self.channel_grid.addWidget(swatch, position, 0)
            self.channel_grid.addWidget(check, position, 1)
            self.channel_grid.addWidget(slider, position, 2)
        self.channel_grid.setColumnStretch(2, 1)

    def refresh(self, session: Session | None, marker: str | None) -> None:
        judged = session is not None and session.labels is not None
        self.undo_button.setEnabled(judged and session.history.can_undo)
        self.redo_button.setEnabled(judged and session.history.can_redo)
        self.warnings.setPlainText("\n\n".join(session.warnings) if session else "")
        if session is not None:
            shown = session.shown_channels(marker)
            for index, check in self.checks.items():
                check.setText(session.table.row(index).title)
                check.setChecked(index in shown)
        blind = judged and session.blind_active
        self.blind_check.setEnabled(judged and bool(session.judgements))
        self.blind_check.setChecked(blind)
        self.agreement_label.setText("" if blind or not judged else _agreement_text(session))
        on_imv = judged and marker == IMV_TAB
        for widget in (self.region_box, self.intensity_label, self.intensity):
            widget.setVisible(on_imv)
        for widget in (self.marks_check, self.blind_check, self.legend, self.summary,
                       self.agreement_label):
            widget.setVisible(not on_imv)
        if not judged:
            self.hint.setText(HINT_BEFORE)
            self.summary.setRowCount(0)
            return
        if on_imv:
            self._show_intensity(session)
        if marker is None:
            self.hint.setText(HINT_DAPI)
        elif marker == IMV_TAB:
            self.hint.setText(HINT_IMV)
        else:
            self.hint.setText((HINT_BLIND if blind else HINT_MARKER).format(marker=marker))
        rows = summarize(session)
        self.summary.setRowCount(len(rows))
        for position, row in enumerate(rows):
            rate = f"{row.rate:.1f}%" if row.rate is not None else "—"
            cells = (row.name, row.total, row.positive, rate, row.added, row.removed, row.undetermined)
            if blind and position:
                # 目視判定の途中で自動判定の数が見えると、判定がそちらに引っ張られる
                cells = (row.name, row.total, *["（隠しています）"] * 5)
            for column, value in enumerate(cells):
                self.summary.setItem(position, column, QTableWidgetItem(str(value)))


    def _show_intensity(self, session: Session) -> None:
        """範囲ごとの平均蛍光強度（平均蛍光強度で測るマーカーだけ）。"""
        markers = session.imv_channels
        header = ["範囲", "面積 (µm²)", "数える核", *markers]
        rows = session.intensity()
        self.intensity.setColumnCount(len(header))
        self.intensity.setHorizontalHeaderLabels(header)
        self.intensity.setRowCount(len(rows))
        for position, row in enumerate(rows):
            cells = [row.name, f"{row.area_um2:,.1f}", "—" if row.nuclei is None else row.nuclei,
                     *[f"{row.stats[index].mean:,.1f}" for index in markers.values()]]
            for column, value in enumerate(cells):
                item = QTableWidgetItem(str(value))
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.intensity.setItem(position, column, item)

    def show_region_mode(self, key: str) -> None:
        """napari のキー（R・E・P など）で描き方が変わったときも、ボタンの表示を合わせる。"""
        if key in self.region_buttons:
            self.region_buttons[key].setChecked(True)


def _agreement_text(session: Session) -> str:
    lines = []
    for row in agreement(session):
        def show(value: float | None) -> str:
            return "—" if value is None else f"{value:.2f}"

        lines.append(f"目視との一致 {row.marker}: 感度 {show(row.sensitivity)}、"
                     f"特異度 {show(row.specificity)}、κ {show(row.kappa)}"
                     f"（目視も自動も陽性 {row.both}、自動だけ {row.auto_only}、"
                     f"目視だけ {row.human_only}、どちらも陰性 {row.neither}）")
    return "\n".join(lines)
