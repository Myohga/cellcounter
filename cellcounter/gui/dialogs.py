"""エラー・完了・ヘルプのダイアログ。"""

from __future__ import annotations

import logging
import os

from qtpy.QtWidgets import QMessageBox, QWidget

from .. import __version__
from .shortcuts import MOUSE_HELP, SHORTCUTS

log = logging.getLogger("cellcounter")


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

    keys = [(" / ".join(entry.keys), f"{entry.label}: {entry.help}") for entry in SHORTCUTS]
    return (f"<h3>cellcounter {__version__}</h3><h4>キー</h4>{table(keys)}"
            f"<h4>マウス</h4>{table(MOUSE_HELP)}")


def show_help(parent: QWidget) -> None:
    QMessageBox(QMessageBox.Icon.NoIcon, "ヘルプ", help_html(), parent=parent).exec()
