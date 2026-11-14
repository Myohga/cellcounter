""".czi の読み込み（シーン一覧・軸の並べ替え・Z 投影）。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import czifile
import numpy as np

from .metadata import ImageMeta, parse_metadata

_KEPT_AXES = "CZYX"
_AXIS_NAMES = {"S": "シーン", "M": "タイル", "T": "時間", "V": "ビュー", "B": "ブロック",
               "H": "位相", "I": "照明", "R": "回転"}
_PROJECTIONS = {
    "max": lambda stack: stack.max(axis=0),
    "mean": lambda stack: stack.mean(axis=0, dtype=np.float32),
    "best": lambda stack: stack[int(stack.mean(axis=(1, 2)).argmax())],
}


@dataclass
class SceneInfo:
    index: int
    name: str
    sizes: dict[str, int]


@dataclass
class LoadedImage:
    """1 シーン分の画像。planes は (チャンネル, Y, X)。"""

    path: str
    scene: int
    planes: np.ndarray
    meta: ImageMeta
    z_projection: str
    n_z: int
    warnings: list[str] = field(default_factory=list)


def to_czyx(array: np.ndarray, axes: str) -> tuple[np.ndarray, list[str]]:
    """軸の名前を見て (C, Z, Y, X) に並べ替える。捨てた軸があれば文章で返す。"""
    if len(axes) != array.ndim:
        raise ValueError(f"軸の数が合いません: 軸 '{axes}' に対して配列は {array.ndim} 次元です。")
    if "Y" not in axes or "X" not in axes:
        raise ValueError(f"Y・X の軸がありません: '{axes}'")

    notes, index, kept = [], [], []
    for axis, size in zip(axes, array.shape):
        if axis in _KEPT_AXES:
            index.append(slice(None))
            kept.append(axis)
            continue
        if size > 1:
            if axis == "0":
                raise ValueError("RGB 画像には対応していません。")
            notes.append(f"{_AXIS_NAMES.get(axis, axis)}の軸に {size} 個のデータがあります。"
                         "1 番目だけを使いました。")
        index.append(0)

    array = array[tuple(index)]
    for axis in "ZC":
        if axis not in kept:
            array = np.expand_dims(array, 0)
            kept.insert(0, axis)
    return np.transpose(array, [kept.index(axis) for axis in _KEPT_AXES]), notes


def project_z(stack: np.ndarray, mode: str) -> np.ndarray:
    """(Z, Y, X) を 1 枚にする。mode は max / mean / best か、'plane:3'（3 枚目だけ）。"""
    plane = re.fullmatch(r"plane:(\d+)", mode)
    if plane:
        number = int(plane.group(1))
        if not 1 <= number <= stack.shape[0]:
            raise ValueError(f"Z の {number} 枚目はありません（この画像は {stack.shape[0]} 枚）。")
        return stack[number - 1]
    if mode not in _PROJECTIONS:
        raise ValueError(f"Z 投影の指定が不正です: {mode}"
                         f"（{' / '.join(_PROJECTIONS)} / plane:番号 のいずれか）")
    return stack[0] if stack.shape[0] == 1 else _PROJECTIONS[mode](stack)


def _open(path: str) -> czifile.CziFile:
    if not os.path.isfile(path):
        raise FileNotFoundError(f".czi が見つかりません: {path}")
    return czifile.CziFile(path)


def list_scenes(path: str) -> list[SceneInfo]:
    with _open(path) as czi:
        return [SceneInfo(int(key), str(scene.name), dict(scene.sizes))
                for key, scene in czi.scenes.items()]


def read_scene(path: str, scene: int = 0, z_projection: str = "max") -> LoadedImage:
    with _open(path) as czi:
        if scene not in czi.scenes.keys():
            raise IndexError(f"シーン {scene} はありません（このファイルのシーン: "
                             f"{', '.join(str(key) for key in czi.scenes.keys())}）。")
        selected = czi.scenes[scene]
        array, warnings = to_czyx(np.asarray(selected.asarray()), str(selected.axes))
        meta = parse_metadata(czi.metadata())

    if array.shape[0] != len(meta.channels):
        raise ValueError(f"チャンネル数が合いません: 画像は {array.shape[0]}、"
                         f"メタデータは {len(meta.channels)} です。")
    if meta.bits is None:
        if not np.issubdtype(array.dtype, np.integer):
            raise ValueError("ビット深度がメタデータに無く、画像からも決められません。")
        meta.bits = array.dtype.itemsize * 8
        warnings.append(f"ビット深度がメタデータに無いため、{meta.bits} bit として扱います。")

    planes = np.stack([project_z(stack, z_projection) for stack in array])
    return LoadedImage(path=os.path.abspath(path), scene=scene, planes=planes, meta=meta,
                       z_projection=z_projection, n_z=array.shape[1], warnings=warnings)
