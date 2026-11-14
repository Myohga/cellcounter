"""動作環境の確認（版と GPU）。ヘルプに表示する。"""

from __future__ import annotations

import platform
from importlib import metadata

from . import __version__

_PACKAGES = ("napari", "cellpose", "torch", "czifile", "numpy", "openpyxl")


def _gpu() -> str:
    try:
        import torch
    except ImportError as error:
        return f"PyTorch を読み込めません（{error}）"
    if torch.cuda.is_available():
        return f"使えます（{torch.cuda.get_device_name(0)}）"
    return "使えません（核の検出は CPU で動き、1 枚に 10 分以上かかります）"


def environment_report() -> list[tuple[str, str]]:
    report = [("cellcounter", __version__), ("Python", platform.python_version()),
              ("OS", platform.platform())]
    for name in _PACKAGES:
        try:
            report.append((name, metadata.version(name)))
        except metadata.PackageNotFoundError:
            report.append((name, "入っていません"))
    report.append(("GPU", _gpu()))
    return report
