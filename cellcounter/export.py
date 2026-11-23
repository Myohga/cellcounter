"""[確定] で書き出す一式（Excel・確認用画像・作業ファイル）。"""

from __future__ import annotations

import os
import re
from datetime import date

from .excel import write_results
from .overlay import save_all
from .project import EXTENSION, save_project
from .session import Session

RESULTS_STEM = "result"
# ファイル名には / を使えないので、日付は 2026-11-23 の形にする
DATE_FORMAT = "%Y-%m-%d"
_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')


def results_name(prefix: str = "", day: date | None = None) -> str:
    """結果の Excel の名前。<名前>_result_<日付>.xlsx。名前が空なら result_<日付>.xlsx。"""
    prefix = prefix.strip()
    found = sorted(set(_FORBIDDEN.findall(prefix)))
    if found:
        raise ValueError(f"結果ファイルの名前に使えない文字が入っています: {' '.join(found)}"
                         r'（\ / : * ? " < > | は使えません）')
    stem = f"{prefix}_{RESULTS_STEM}" if prefix else RESULTS_STEM
    return f"{stem}_{(day or date.today()).strftime(DATE_FORMAT)}.xlsx"


def default_folder(czi_path: str) -> str:
    stem = os.path.splitext(os.path.basename(czi_path))[0]
    return os.path.join(os.path.dirname(czi_path), f"{stem}_cellcounter")


def export_results(session: Session, folder: str | None = None, name: str = "") -> str:
    """結果フォルダはここで初めて作る。書き出したフォルダを返す。

    name は結果の Excel の名前の前半（results_name を参照）。
    """
    if session.labels is None:
        raise RuntimeError("核を検出してから出力してください。")
    workbook = results_name(name)
    folder = folder or default_folder(session.image.path)
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(session.image.path))[0]
    write_results(session, os.path.join(folder, workbook))
    save_all(session, folder)
    save_project(session, os.path.join(folder, stem + EXTENSION))
    session.dirty = False
    return folder
