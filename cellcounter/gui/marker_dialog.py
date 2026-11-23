"""操作 → 辞書登録: 抗体マーカーの辞書の一覧と、登録・編集・削除。"""

from __future__ import annotations

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                            QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                            QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
                            QTableWidgetItem, QVBoxLayout, QWidget)

from ..markers import LOCATION_SPECS, MarkerDictionary, MarkerEntry, marker_key
from ..userdata import UserData
from .dialogs import confirm

COLUMNS = ("マーカー名", "染まる場所", "核を数える", "平均蛍光強度", "コメント")
UNSET = "（未設定）"
CHECKED = "✓"
COUNTS_TEXT = "選んだとき、そのチャンネルを「核を数える」にする（DAPI などの核の染色）"
IMV_TEXT = "選んだとき、判定法を「平均蛍光強度」にする（タウなど）"
COMMENT_HINT = "② 設定で、マーカー名の ▼ の一覧にポインターを合わせると出ます。"


class MarkerEntryDialog(QDialog):
    """1 件の登録・編集。名前が重なるなどで登録できないときは、閉じずに理由を出す。"""

    def __init__(self, parent: QWidget, dictionary: MarkerDictionary,
                 entry: MarkerEntry | None = None) -> None:
        super().__init__(parent)
        self._dictionary = dictionary
        self._original = entry
        self.setWindowTitle("マーカーを編集" if entry else "マーカーを登録")
        entry = entry or MarkerEntry("")

        self.name = QLineEdit(entry.name)
        self.name.setPlaceholderText("例: AT8")
        self.location = QComboBox()
        self.location.addItem(UNSET, "")
        for key, spec in LOCATION_SPECS.items():
            self.location.addItem(spec.label, key)
        self.location.setCurrentIndex(max(self.location.findData(entry.location), 0))
        self.counts = QCheckBox(COUNTS_TEXT)
        self.counts.setChecked(entry.counts_nuclei)
        self.imv = QCheckBox(IMV_TEXT)
        self.imv.setChecked(entry.imv)
        self.comment = QPlainTextEdit(entry.comment)
        self.comment.setPlaceholderText("例: リン酸化タウ（Ser202/Thr205）。1:500 で使用")
        self.comment.setMaximumHeight(90)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        self.error.hide()
        self.counts.toggled.connect(self._show_state)

        form = QFormLayout()
        form.addRow("マーカー名", self.name)
        form.addRow("染まる場所", self.location)
        form.addRow("既定", self.counts)
        form.addRow("", self.imv)
        form.addRow("コメント", self.comment)
        hint = QLabel(COMMENT_HINT)
        hint.setWordWrap(True)
        form.addRow("", hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("登録")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("やめる")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self.resize(560, self.sizeHint().height())
        self._show_state()

    def _show_state(self) -> None:
        """核を数えるチャンネルは陽性も平均蛍光強度も測らないので、その 2 つは選べなくする。"""
        counts = self.counts.isChecked()
        self.location.setEnabled(not counts)
        self.imv.setEnabled(not counts)

    def entry(self) -> MarkerEntry:
        counts = self.counts.isChecked()
        return MarkerEntry(self.name.text().strip(),
                           "" if counts else self.location.currentData(), counts,
                           not counts and self.imv.isChecked(),
                           self.comment.toPlainText().strip())

    def accept(self) -> None:
        try:
            self._dictionary.check(self.entry(),
                                   self._original.name if self._original else None)
        except ValueError as error:
            self.error.setText(str(error))
            self.error.show()
            return
        super().accept()


class MarkerDictionaryDialog(QDialog):
    """辞書の一覧。変えるたびに保存する。② のマーカー名の一覧には、閉じたときに反映する。"""

    def __init__(self, parent: QWidget | None, userdata: UserData) -> None:
        super().__init__(parent)
        self.setWindowTitle("辞書登録（抗体マーカーの辞書）")
        self._userdata = userdata
        self.edited = False

        guide = QLabel(
            "② 設定でマーカー名を入れたときに、ここに登録した内容（染まる場所・判定法・"
            "核を数えるか）が自動で入ります。コメントは、② のマーカー名の ▼ の一覧で名前に"
            "ポインターを合わせると出ます。名前は大文字・小文字や記号（- . 空白）を区別しません。")
        guide.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("絞り込み（名前・コメント）")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._fill())

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda _index: self.edit_selected())
        self.table.itemSelectionChanged.connect(self._show_state)

        self.add_button = QPushButton("新しく登録…")
        self.add_button.clicked.connect(self.add)
        self.edit_button = QPushButton("編集…")
        self.edit_button.clicked.connect(self.edit_selected)
        self.remove_button = QPushButton("削除")
        self.remove_button.clicked.connect(self.remove_selected)
        self.reset_button = QPushButton("初期値に戻す…")
        self.reset_button.clicked.connect(self.reset)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        for button in (self.add_button, self.edit_button, self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(guide)
        layout.addWidget(self.search)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        self.resize(820, 600)
        self._fill()

    @property
    def dictionary(self) -> MarkerDictionary:
        return self._userdata.markers

    def _fill(self, select: str | None = None) -> None:
        words = marker_key(self.search.text())
        typed = self.search.text().strip().casefold()
        entries = [entry for entry in self.dictionary.entries
                   if not typed or words in entry.key or typed in entry.comment.casefold()]
        self.table.setRowCount(len(entries))
        for position, entry in enumerate(entries):
            place = LOCATION_SPECS[entry.location].label if entry.location else UNSET
            cells = (entry.name, "—" if entry.counts_nuclei else place,
                     CHECKED if entry.counts_nuclei else "", CHECKED if entry.imv else "",
                     entry.comment.replace("\n", " "))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column in (2, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, entry.name)
                    item.setToolTip(entry.describe())
                self.table.setItem(position, column, item)
            if select is not None and entry.key == marker_key(select):
                self.table.selectRow(position)
        self._show_state()

    def _show_state(self) -> None:
        chosen = self.selected() is not None
        self.edit_button.setEnabled(chosen)
        self.remove_button.setEnabled(chosen)

    def selected(self) -> MarkerEntry | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.dictionary.exact(self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole))

    def _save(self, select: str | None = None) -> None:
        try:
            self._userdata.save_markers()
        except OSError as error:
            QMessageBox.warning(self, "辞書を保存できません", str(error))
        self.edited = True
        self._fill(select)

    def add(self) -> None:
        dialog = MarkerEntryDialog(self, self.dictionary)
        if dialog.exec():
            entry = dialog.entry()
            self.dictionary.add(entry)
            self._save(entry.name)

    def edit_selected(self) -> None:
        entry = self.selected()
        if entry is None:
            return
        dialog = MarkerEntryDialog(self, self.dictionary, entry)
        if dialog.exec():
            changed = dialog.entry()
            self.dictionary.replace(entry.name, changed)
            self._save(changed.name)

    def remove_selected(self) -> None:
        entry = self.selected()
        if entry is None or not confirm(self, "削除しますか？",
                                        f"「{entry.name}」を辞書から削除しますか？"):
            return
        self.dictionary.remove(entry.name)
        self._save()

    def reset(self) -> None:
        if not confirm(self, "初期値に戻しますか？",
                       "登録・編集した内容を消して、最初から入っている辞書に戻しますか？"):
            return
        self.dictionary.reset()
        self._save()
