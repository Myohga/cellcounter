"""組み合わせごとの確認用画像（背景に × を焼き付けた PNG）。"""

from __future__ import annotations

import os
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .marks import ADDED, AUTO, REMOVED
from .session import Session, tab_name

COLORS = {AUTO: (255, 221, 0), ADDED: (0, 229, 255), REMOVED: (255, 64, 64)}
CAPTIONS = {AUTO: "自動で付いた ×", ADDED: "人が足した ×", REMOVED: "人が消した ×"}
_DAPI_TINT = (0.25, 0.45, 1.0)
_MARKER_TINT = (0.3, 1.0, 0.2)
_FONTS = (
    r"C:\Windows\Fonts\meiryo.ttc", r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONTS:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    raise RuntimeError("日本語のフォントが見つからないため、確認用画像に凡例を書けません。")


def _scaled(session: Session, channel_index: int) -> np.ndarray:
    low, high = session.contrast_limits(channel_index)
    plane = session.image.planes[channel_index].astype(np.float32)
    return np.clip((plane - low) / (high - low), 0.0, 1.0)


def _background(session: Session, marker: str | None) -> np.ndarray:
    layers = [(_scaled(session, session.table.dapi.index), _DAPI_TINT)]
    if marker is not None:
        layers.append((_scaled(session, session.judgements[marker].channel_index), _MARKER_TINT))
    rgb = sum(layer[..., None] * np.array(tint, dtype=np.float32) for layer, tint in layers)
    return (np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8)


def _cross(canvas: np.ndarray, y: float, x: float, half: int, color: tuple[int, int, int],
           thickness: int) -> None:
    row, column = int(round(y)), int(round(x))
    for direction in (1, -1):
        cv2.line(canvas, (column - half, row - direction * half),
                 (column + half, row + direction * half), color, thickness, cv2.LINE_AA)


def render(session: Session, marker: str | None) -> Image.Image:
    """marker が None なら「DAPI のみ」。下の帯に凡例と件数を入れる。"""
    canvas = np.ascontiguousarray(_background(session, marker))
    half = max(3, round(session.diameter_px * 0.3))
    thickness = 1 if session.diameter_px < 20 else 2
    counts = dict.fromkeys(COLORS, 0)
    for nucleus in session.nuclei.values():
        kind = session.marks.category(marker, nucleus.id)
        if kind:
            counts[kind] += 1
            _cross(canvas, nucleus.y, nucleus.x, half, COLORS[kind], thickness)

    height, width = canvas.shape[:2]
    size = max(14, width // 45)
    lines = [(f"{os.path.basename(session.image.path)}　{tab_name(marker)}", (255, 255, 255))]
    if marker is not None and session.judgements[marker].provisional:
        lines.append(("暫定（陰性対照なし）", COLORS[REMOVED]))
    lines += [(f"× {CAPTIONS[kind]}: {counts[kind]}", COLORS[kind]) for kind in COLORS]

    line_height = round(size * 1.5)
    image = Image.new("RGB", (width, height + line_height * len(lines) + size), (0, 0, 0))
    image.paste(Image.fromarray(canvas), (0, 0))
    draw = ImageDraw.Draw(image)
    font = _font(size)
    for number, (text, color) in enumerate(lines):
        top = height + size // 2 + number * line_height
        draw.text((size // 2, top), text, fill=color, font=font)
    return image


def save_all(session: Session, folder: str) -> list[str]:
    paths = []
    for marker in (None, *session.judgements):
        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", tab_name(marker))
        path = os.path.join(folder, f"確認_{safe}.png")
        render(session, marker).save(path)
        paths.append(path)
    return paths
