"""組み合わせごとの確認用画像（背景に × を焼き付けた PNG）。"""

from __future__ import annotations

import os
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .marks import ADDED, AUTO, REMOVED
from .session import IMV_TAB, Session, tab_name

COLORS = {AUTO: (255, 221, 0), ADDED: (0, 229, 255), REMOVED: (255, 64, 64)}
REGION_COLOR = (255, 255, 255)
CAPTIONS = {AUTO: "自動で付いた ×", ADDED: "人が足した ×", REMOVED: "人が消した ×"}
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


def rgb_of(color: str) -> tuple[float, float, float]:
    """'#RRGGBB' を 0〜1 の (R, G, B) にする。"""
    return tuple(int(color[position:position + 2], 16) / 255 for position in (1, 3, 5))


def _background(session: Session, marker: str | None) -> np.ndarray:
    """画面と同じチャンネルを、同じ色とコントラストで重ねる。"""
    rgb = np.zeros((*session.image.planes.shape[1:], 3), np.float32)
    for index in session.shown_channels(marker):
        tint = np.array(rgb_of(session.table.row(index).color), dtype=np.float32)
        rgb += _scaled(session, index)[..., None] * tint
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
    thickness = 1
    counts = dict.fromkeys(COLORS, 0)
    for nucleus in session.nuclei.values():
        kind = session.marks.category(marker, nucleus.id)
        if kind:
            counts[kind] += 1
            _cross(canvas, nucleus.y, nucleus.x, half, COLORS[kind], thickness)

    lines = [(f"{os.path.basename(session.image.path)}　{tab_name(marker)}", (255, 255, 255))]
    if marker is not None and session.judgements[marker].provisional:
        lines.append(("暫定（陰性対照なし）", COLORS[REMOVED]))
    lines += [(f"× {CAPTIONS[kind]}: {counts[kind]}", COLORS[kind]) for kind in COLORS]
    image, _draw, _font_used = _with_legend(canvas, lines)
    return image


def _with_legend(canvas: np.ndarray, lines: list[tuple[str, tuple[int, int, int]]]):
    """画像の下に黒い帯を足し、凡例の行を書く。あとから書き足せるよう draw と font も返す。"""
    height, width = canvas.shape[:2]
    size = max(14, width // 45)
    line_height = round(size * 1.5)
    image = Image.new("RGB", (width, height + line_height * len(lines) + size), (0, 0, 0))
    image.paste(Image.fromarray(canvas), (0, 0))
    draw = ImageDraw.Draw(image)
    font = _font(size)
    for number, (text, color) in enumerate(lines):
        top = height + size // 2 + number * line_height
        draw.text((size // 2, top), text, fill=color, font=font)
    return image, draw, font


def render_intensity(session: Session) -> Image.Image:
    """平均蛍光強度のタブ。測った範囲の縁と番号を描き、下の帯に範囲ごとの値を入れる。"""
    canvas = np.ascontiguousarray(_background(session, IMV_TAB))
    for region in session.regions:
        points = np.round(region.outline()[:, ::-1]).astype(np.int32)  # (x, y) の順にする
        cv2.polylines(canvas, [points], True, REGION_COLOR, 1, cv2.LINE_AA)

    markers = session.imv_channels
    lines = [(f"{os.path.basename(session.image.path)}　{IMV_TAB}", (255, 255, 255))]
    for row in session.intensity():
        values = " ／ ".join(f"{marker} {row.stats[index].mean:.1f}"
                            for marker, index in markers.items())
        lines.append((f"{row.name}（{row.area_um2:g} µm²）: {values}", REGION_COLOR))
    image, draw, font = _with_legend(canvas, lines)
    for number, region in enumerate(session.regions, 1):
        top, left = region.outline().min(axis=0)
        draw.text((max(0, left) + 3, max(0, top) + 1), str(number), fill=REGION_COLOR, font=font)
    return image


def save_all(session: Session, folder: str) -> list[str]:
    paths = []
    tabs = [None, *session.judgements, *([IMV_TAB] if session.imv_channels else [])]
    for marker in tabs:
        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", tab_name(marker))
        path = os.path.join(folder, f"確認_{safe}.png")
        (render_intensity(session) if marker == IMV_TAB else render(session, marker)).save(path)
        paths.append(path)
    return paths
