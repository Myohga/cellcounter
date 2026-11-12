"""ショートカットの表。キーの割り当て・ボタンの表示・ヘルプは、すべてここから作る。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from qtpy.QtGui import QKeySequence
from qtpy.QtWidgets import QAction, QWidget


@dataclass(frozen=True)
class Shortcut:
    name: str
    keys: tuple[str, ...]
    label: str
    help: str


SHORTCUTS = (
    Shortcut("open", ("Ctrl+O",), "開く…", ".czi を開く"),
    Shortcut("open_project", ("Ctrl+Shift+O",), "作業ファイルを開く…", "保存した作業の続きを開く"),
    Shortcut("save_project", ("Ctrl+S",), "作業を保存…", "途中の状態を作業ファイルに保存する"),
    Shortcut("judge", ("Ctrl+J",), "判定", "核を検出し、ON にしたマーカーを自動判定する"),
    Shortcut("export", ("Ctrl+Return",), "確定（出力）", "集計して Excel と確認用画像を書き出す"),
    Shortcut("undo", ("Ctrl+Z",), "元に戻す", "× の操作を 1 つ戻す"),
    Shortcut("redo", ("Ctrl+Shift+Z", "Ctrl+Y"), "やり直し", "戻した操作をやり直す"),
    Shortcut("next_tab", ("Ctrl+PgDown",), "次の組み合わせ", "右隣の組み合わせのタブへ"),
    Shortcut("previous_tab", ("Ctrl+PgUp",), "前の組み合わせ", "左隣の組み合わせのタブへ"),
    Shortcut("help", ("F1",), "ヘルプ", "この一覧を表示する"),
)

# 依頼の指定で Ctrl+Y を「やり直し」に使う。napari 標準ではこのキーが 2D/3D の切り替えなので、
# その割り当てを外す（この画面は 2D でしか使わない）。
REPLACED_NAPARI_ACTIONS = ("napari:toggle_ndisplay",)

MOUSE_HELP = (
    ("クリック（DAPI のみ）", "× のある核 → 数えない ／ × の無い核 → 数える ／ 何も無い場所 → 円い核を作る"),
    ("クリック（DAPI＋マーカー）", "× のある核 → 陰性 ／ × の無い核 → 陽性 ／ 何も無い場所 → 円い核を作って陽性"),
    ("ドラッグ", "画像を動かす"),
    ("ホイール", "拡大・縮小"),
)


def shortcut(name: str) -> Shortcut:
    for entry in SHORTCUTS:
        if entry.name == name:
            return entry
    raise KeyError(f"ショートカット {name} は表にありません。")


def button_text(name: str) -> str:
    entry = shortcut(name)
    return f"{entry.label}（{entry.keys[0]}）"


def make_action(parent: QWidget, name: str, run: Callable[[], None]) -> QAction:
    entry = shortcut(name)
    action = QAction(entry.label, parent)
    action.setShortcuts([QKeySequence(keys) for keys in entry.keys])
    action.setToolTip(entry.help)
    action.triggered.connect(lambda _checked=False: run())
    return action
