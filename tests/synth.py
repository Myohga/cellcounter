"""テスト用の合成画像。核の位置と陽性の核が分かっているので、数え間違いを見つけられる。"""

from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

from cellcounter.channels import build_table
from cellcounter.control import collect_control
from cellcounter.czi import LoadedImage
from cellcounter.metadata import ChannelInfo, ImageMeta
from cellcounter.pipeline import open_session, run_detection, run_judgement
from cellcounter.segment import Segmentation
from cellcounter.session import Session
from cellcounter.settings import Settings

UM_PER_PX = 0.3
RADIUS = 7
CYTOPLASM_PX = 10
BACKGROUND = 200.0
NOISE = 20.0
CELL_SD = 10.0
CHANNELS = (("H3342-T1", "Hoechst 33342", 455.0, "#0076FF"),
            ("AF488-T2", "Alexa Fluor 488", 517.0, "#00FF33"),
            ("AF555-T1", "Alexa Fluor 555", 568.0, "#FF7E00"))


def _stamp(labels: np.ndarray, cy: int, cx: int, nucleus_id: int, radius: int = RADIUS) -> None:
    ys, xs = np.mgrid[cy - radius:cy + radius + 1, cx - radius:cx + radius + 1]
    inside = (ys - cy) ** 2 + (xs - cx) ** 2 <= radius ** 2
    labels[ys[inside], xs[inside]] = nucleus_id


def grid_labels(rows: int, columns: int, pitch: int = 30, seed: int = 0) -> np.ndarray:
    """互いに離れた円い核を格子状に並べる（位置は少しずらす）。ID は 1 から。"""
    rng = np.random.default_rng(seed)
    labels = np.zeros(((rows + 1) * pitch, (columns + 1) * pitch), np.int32)
    for number in range(rows * columns):
        row, column = divmod(number, columns)
        jitter_y, jitter_x = rng.integers(-3, 4, 2)
        _stamp(labels, (row + 1) * pitch + jitter_y, (column + 1) * pitch + jitter_x, number + 1)
    return labels


def pair_labels(pairs: int, pitch: int = 60, columns: int = 10) -> np.ndarray:
    """ぴったり接した 2 つの核の組を並べる。奇数 ID が左、偶数 ID が右。"""
    rows = -(-pairs // columns)
    labels = np.zeros(((rows + 1) * pitch, (columns + 1) * pitch), np.int32)
    for number in range(pairs):
        row, column = divmod(number, columns)
        cy, cx = (row + 1) * pitch, (column + 1) * pitch
        _stamp(labels, cy, cx - RADIUS - 1, 2 * number + 1)
        _stamp(labels, cy, cx + RADIUS, 2 * number + 2)
    return labels


def _noisy(signal: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    plane = BACKGROUND + signal + rng.normal(0.0, NOISE, signal.shape)
    return np.clip(plane, 0, 4095).astype(np.uint16)


def dapi_plane(labels: np.ndarray, seed: int) -> np.ndarray:
    return _noisy(2000.0 * (labels > 0), np.random.default_rng(seed))


def marker_plane(labels: np.ndarray, positive: set[int], where: str, seed: int,
                 gain: float = 800.0, blur: float = 0.0) -> np.ndarray:
    """where が 'nucleus' なら核の中、'cytoplasm' なら核の周りが染まる。

    陰性の細胞にも細胞ごとにばらつく弱い染まりを入れる（非特異的な染まりの代わり）。
    """
    rng = np.random.default_rng(seed)
    level = rng.normal(0.0, CELL_SD, int(labels.max()) + 1)
    level[sorted(positive)] += gain
    level[0] = 0.0
    region = labels
    if where == "cytoplasm":
        distance, index = ndi.distance_transform_edt(labels == 0, return_indices=True)
        region = np.where((distance > 0) & (distance <= CYTOPLASM_PX),
                          labels[index[0], index[1]], 0)
    signal = level[region]
    if blur:
        signal = ndi.gaussian_filter(signal, blur)
    return _noisy(signal, rng)


def fake_image(planes: list[np.ndarray], bits: int = 12, path: str = "synthetic.czi") -> LoadedImage:
    channels = [ChannelInfo(index, name, fluor, None, emission, "Fluorescence", color)
                for index, (name, fluor, emission, color) in enumerate(CHANNELS[:len(planes)])]
    meta = ImageMeta(channels, UM_PER_PX, bits, "Plan-Apochromat 20x/0.8 M27")
    return LoadedImage(path, 0, np.stack(planes), meta, "max", 1)


def known_labels(labels: np.ndarray):
    """正解のラベルをそのまま返す検出器（Cellpose の代わり）。"""
    return lambda dapi, settings, um_per_px, full: Segmentation(labels.copy(), None)


def by_threshold(dapi, settings, um_per_px, full) -> Segmentation:
    """DAPI を閾値で切るだけの検出器。核どうしが離れている画像で使う。"""
    labels, _ = ndi.label(dapi > BACKGROUND + 1000.0)
    return Segmentation(labels.astype(np.int32), None)


def negative_control(rows: int, columns: int, seed: int,
                     stains: tuple[str, ...] = ("nucleus", "cytoplasm")) -> LoadedImage:
    """陽性の細胞が 1 つも無い画像。stains はマーカーのチャンネルごとの染まり方。"""
    labels = grid_labels(rows, columns, seed=seed)
    planes = [marker_plane(labels, set(), where, seed + 2 + number)
              for number, where in enumerate(stains)]
    return fake_image([dapi_plane(labels, seed + 1), *planes])


def build_session(labels: np.ndarray, planes: list[np.ndarray],
                  markers: list[tuple[int, str, str]], control: LoadedImage | None = None,
                  bits: int = 12, control_segmenter=by_threshold) -> Session:
    """合成画像を読み込み → 検出 → 判定まで進めた状態を作る。"""
    image = fake_image(planes, bits)
    table = build_table(image.meta)
    for index, name, location in markers:
        table.set_marker(index, name, location)
    session = open_session(image, table, Settings())
    run_detection(session, known_labels(labels))
    control_data = None
    if control is not None:
        control_data = collect_control(session, [("control.czi", 0)], control_segmenter,
                                       lambda path, scene, z: control)
    run_judgement(session, control_data)
    return session


def two_marker_session(rows: int, columns: int, nuclear: set[int], cytoplasmic: set[int],
                       control: LoadedImage | None = None, seed: int = 10) -> Session:
    """核マーカー「NUC」と細胞質マーカー「CYT」を持つ画像。陽性の核 ID を指定する。"""
    labels = grid_labels(rows, columns, seed=seed)
    planes = [dapi_plane(labels, seed + 1), marker_plane(labels, nuclear, "nucleus", seed + 2),
              marker_plane(labels, cytoplasmic, "cytoplasm", seed + 3)]
    return build_session(labels, planes, [(1, "NUC", "nuclear"), (2, "CYT", "cytoplasmic")], control)
