"""[確定] で書き出す一式（Excel・確認用画像・作業ファイル）。"""

from __future__ import annotations

import os

from .excel import write_results
from .overlay import save_all
from .project import EXTENSION, save_project
from .session import Session

RESULTS_NAME = "results.xlsx"


def default_folder(czi_path: str) -> str:
    stem = os.path.splitext(os.path.basename(czi_path))[0]
    return os.path.join(os.path.dirname(czi_path), f"{stem}_cellcounter")


def export_results(session: Session, folder: str | None = None) -> str:
    """結果フォルダはここで初めて作る。書き出したフォルダを返す。"""
    if session.labels is None:
        raise RuntimeError("核を検出してから出力してください。")
    folder = folder or default_folder(session.image.path)
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(session.image.path))[0]
    write_results(session, os.path.join(folder, RESULTS_NAME))
    save_all(session, folder)
    save_project(session, os.path.join(folder, stem + EXTENSION))
    session.dirty = False
    return folder
