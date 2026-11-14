"""③ 判定・修正: 背景に出す画像の選択・件数・凡例・元に戻す／やり直し・警告。"""

from __future__ import annotations

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                            QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                            QVBoxLayout, QWidget)
from superqt import QRangeSlider

from ..marks import ADDED, AUTO, REMOVED
from ..overlay import CAPTIONS, COLORS
from ..quality import full_scale
from ..session import Session
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


class ReviewPanel(QWidget):
    undo_requested = Signal()
    redo_requested = Signal()
    contrast_changed = Signal(int, float, float)
    channel_toggled = Signal(int, bool)
    marks_toggled = Signal(bool)
    blind_toggled = Signal(bool)

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
        legend = QHBoxLayout()
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
        layout.addLayout(legend)
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
        if not judged:
            self.hint.setText(HINT_BEFORE)
            self.summary.setRowCount(0)
            return
        if marker is None:
            self.hint.setText(HINT_DAPI)
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
