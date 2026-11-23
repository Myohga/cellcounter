"""利用者ごとの記憶（最近使ったファイル・使ったマーカー名・プリセット・前回のチャンネル表・マーカー辞書）。"""

from __future__ import annotations

import json
import os
import re

from .channels import load_preset, save_preset
from .markers import MarkerDictionary

RECENT_LIMIT = 10
_FILE = "user.json"
MARKERS_FILE = "markers.json"


def data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "cellcounter")


def load_marker_dictionary(folder: str) -> tuple[MarkerDictionary, str]:
    """利用者のマーカー辞書。まだ編集していなければ初期の辞書。読めなければ初期の辞書と知らせ。"""
    path = os.path.join(folder, MARKERS_FILE)
    if not os.path.isfile(path):
        return MarkerDictionary(), ""
    try:
        with open(path, encoding="utf-8") as handle:
            return MarkerDictionary.from_dict(json.load(handle)), ""
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as error:
        os.replace(path, path + ".broken")
        return MarkerDictionary(), (f"マーカー辞書のファイルを読めなかったため、初期の辞書を使っています"
                                    f"（読めなかったファイルは {path}.broken に残してあります）: {error}")


class UserData:
    def __init__(self, folder: str | None = None) -> None:
        self.folder = folder or data_dir()
        self.recent_files: list[str] = []
        self.marker_names: list[str] = []
        self.last_table: dict | None = None
        self.markers, self.notice = load_marker_dictionary(self.folder)
        path = os.path.join(self.folder, _FILE)
        if not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:
            os.replace(path, path + ".broken")
            self.notice = " ".join(filter(None, (
                self.notice, "設定ファイルが壊れていたため、最近使ったファイルなどの記憶を"
                f"作り直しました（壊れたファイルは {path}.broken に残してあります）。")))
            return
        self.recent_files = data["recent_files"]
        self.marker_names = data["marker_names"]
        self.last_table = data["last_table"]

    @property
    def log_path(self) -> str:
        return os.path.join(self.folder, "cellcounter.log")

    @property
    def autosave_path(self) -> str:
        return os.path.join(self.folder, "autosave.cellcounter")

    @property
    def _preset_dir(self) -> str:
        return os.path.join(self.folder, "presets")

    def clear_autosave(self) -> None:
        if os.path.isfile(self.autosave_path):
            os.remove(self.autosave_path)

    def save(self) -> None:
        os.makedirs(self.folder, exist_ok=True)
        data = {"recent_files": self.recent_files, "marker_names": self.marker_names,
                "last_table": self.last_table}
        with open(os.path.join(self.folder, _FILE), "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)

    def save_markers(self) -> None:
        """マーカー辞書を書き出す。登録・編集・削除のたびに呼ぶ。"""
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, MARKERS_FILE), "w", encoding="utf-8") as handle:
            json.dump(self.markers.to_dict(), handle, ensure_ascii=False, indent=1)

    def add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        self.recent_files = [path, *(p for p in self.recent_files if p != path)][:RECENT_LIMIT]
        self.save()

    def remember_table(self, preset: dict) -> None:
        """判定に使ったチャンネル表とマーカー名を、次回のために覚える。"""
        self.last_table = preset
        used = [entry["marker"] for entry in preset["channels"] if entry["marker"]]
        self.marker_names = list(dict.fromkeys([*used, *self.marker_names]))
        self.save()

    def preset_names(self) -> list[str]:
        if not os.path.isdir(self._preset_dir):
            return []
        return sorted(name[:-5] for name in os.listdir(self._preset_dir) if name.endswith(".json"))

    def _preset_path(self, name: str) -> str:
        if not name or re.search(r'[\\/:*?"<>|]', name):
            raise ValueError(f"プリセット名に使えない文字が入っています: {name}")
        return os.path.join(self._preset_dir, name + ".json")

    def save_preset(self, preset: dict) -> None:
        path = self._preset_path(preset["name"])
        os.makedirs(self._preset_dir, exist_ok=True)
        save_preset(path, preset)

    def load_preset(self, name: str) -> dict:
        return load_preset(self._preset_path(name))
