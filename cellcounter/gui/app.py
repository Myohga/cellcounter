"""画面の起動。"""

from __future__ import annotations

import logging
import os
import sys

from napari.qt import get_qapp

from ..userdata import UserData
from .dialogs import show_error
from .main_window import MainWindow


def run(path: str | None = None) -> int:
    """ウィンドウを開く。path を渡すと、起動してすぐそのファイルを開く。"""
    app = get_qapp()
    userdata = UserData()
    os.makedirs(userdata.folder, exist_ok=True)
    logging.basicConfig(filename=userdata.log_path, encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    window = MainWindow(userdata)
    # 画面の操作中に起きた想定外のエラーも、黙って消さずにダイアログとログに出す
    sys.excepthook = lambda kind, error, trace: show_error(
        window, "予期しないエラーが起きました", error, userdata.log_path)
    window.show()
    if path:
        window.open_path(path)
    return app.exec()
