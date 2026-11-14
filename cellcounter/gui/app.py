"""画面の起動。"""

from __future__ import annotations

import logging
import os
import sys

from napari.qt import get_qapp

from ..userdata import UserData
from .dialogs import confirm, show_error
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
    if os.path.isfile(userdata.autosave_path):
        if confirm(window, "前回の作業が残っています",
                   "前回、保存する前に終わった作業が残っています。続きから開きますか？\n"
                   "（「いいえ」を選ぶと、残っている作業は消えます）"):
            path = userdata.autosave_path
        else:
            userdata.clear_autosave()
    if path:
        window.open_path(path)
    return app.exec()
