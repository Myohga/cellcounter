"""エラー・完了・ヘルプのダイアログ。"""

from __future__ import annotations

import logging
import os

from qtpy.QtGui import QKeySequence
from qtpy.QtWidgets import (QDialog, QDialogButtonBox, QMessageBox, QShortcut, QTextBrowser,
                            QVBoxLayout, QWidget)

from .. import __version__
from ..environment import environment_report
from .shortcuts import MOUSE_HELP, SHORTCUTS

log = logging.getLogger("cellcounter")

HELP_WIDTH = 760             # ヘルプの窓の幅（画面が狭いときは画面の 9 割まで）
HELP_SCREEN_FRACTION = 0.8   # ヘルプの窓の高さの上限（画面の高さに対する割合）


def show_error(parent: QWidget, title: str, error: BaseException, log_path: str) -> None:
    """利用者には要点だけを見せ、詳細（どこで起きたか）はログファイルに残す。"""
    log.error("%s", title, exc_info=error)
    QMessageBox.critical(parent, title, f"{error}\n\n詳細はログファイルに残しました:\n{log_path}")


def show_export_done(parent: QWidget, folder: str) -> None:
    box = QMessageBox(QMessageBox.Icon.Information, "出力が終わりました",
                      f"結果を書き出しました。\n{folder}", parent=parent)
    open_button = box.addButton("フォルダを開く", QMessageBox.ButtonRole.ActionRole)
    box.addButton("閉じる", QMessageBox.ButtonRole.AcceptRole)
    box.exec()
    if box.clickedButton() is open_button:
        os.startfile(folder)


def confirm(parent: QWidget, title: str, text: str) -> bool:
    answer = QMessageBox.question(parent, title, text)
    return answer == QMessageBox.StandardButton.Yes


def help_html() -> str:
    def table(rows) -> str:
        cells = "".join(f"<tr><td><b>{left}</b>&nbsp;&nbsp;</td><td>{right}</td></tr>"
                        for left, right in rows)
        return f"<table cellpadding='3'>{cells}</table>"

    keys = [(" / ".join(entry.keys) or "（メニュー）", f"{entry.label}: {entry.help}")
            for entry in SHORTCUTS]
    return (f"<h3>cellcounter {__version__}</h3><h4>キー</h4>{table(keys)}"
            f"<h4>マウス</h4>{table(MOUSE_HELP)}<h4>動作環境</h4>{table(environment_report())}")


class HelpDialog(QDialog):
    """ヘルプ。画面に収まる大きさで開き、中はスクロールでき、文字の大きさを変えられる。"""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("ヘルプ")
        self.text = QTextBrowser()
        self.text.setHtml(help_html())
        # 読み取り専用の QTextBrowser は、Ctrl+ホイールでも文字の大きさが変わる
        self.text.setToolTip("Ctrl+ホイールでも文字の大きさを変えられます")

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Close).setText("閉じる")
        box.rejected.connect(self.reject)
        self.zoom_in = box.addButton("文字を大きく（Ctrl++）", QDialogButtonBox.ButtonRole.ActionRole)
        self.zoom_out = box.addButton("文字を小さく（Ctrl+-）", QDialogButtonBox.ButtonRole.ActionRole)
        self.zoom_in.clicked.connect(lambda: self.text.zoomIn(1))
        self.zoom_out.clicked.connect(lambda: self.text.zoomOut(1))
        # 日本語キーボードでは + が Shift+; なので、; と = でも効くようにする
        for keys, button in ((("Ctrl++", "Ctrl+=", "Ctrl+;"), self.zoom_in),
                             (("Ctrl+-",), self.zoom_out)):
            for key in keys:
                QShortcut(QKeySequence(key), self).activated.connect(button.click)

        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addWidget(box)
        self._fit_to_screen(parent)

    def _fit_to_screen(self, parent: QWidget) -> None:
        """中身が全部見える大きさにする。ただし画面からはみ出さない（はみ出す分はスクロール）。"""
        screen = parent.screen().availableGeometry()
        width = min(HELP_WIDTH, int(screen.width() * 0.9))
        document = self.text.document()
        document.setTextWidth(width - 40)
        wanted = int(document.size().height()) + 100   # 100: ボタンと余白の分
        self.resize(width, min(wanted, int(screen.height() * HELP_SCREEN_FRACTION)))


def show_help(parent: QWidget) -> None:
    HelpDialog(parent).exec()
