"""画像の表示部（napari）と、その上に並べる組み合わせのタブ。"""

from __future__ import annotations

import numpy as np
from napari.components import ViewerModel
from napari.qt import QtViewer
from napari.utils.action_manager import action_manager
from napari.utils.colormaps import Colormap, DirectLabelColormap
from qtpy.QtCore import QTimer, Signal
from qtpy.QtWidgets import QLabel, QTabBar, QVBoxLayout, QWidget

from ..intensity import SHAPE_LABELS, Region, same_regions
from ..overlay import COLORS, rgb_of
from ..quality import full_scale
from ..session import IMV_TAB, Session, tab_name
from .shortcuts import REPLACED_NAPARI_ACTIONS, UNUSED_NAPARI_ACTIONS

CLICK_TOLERANCE_PX = 4.0
MARK_HALF_LENGTH = 0.30   # 核の標準直径に対する、× の腕の長さ
MARK_SCREEN_WIDTH = 1.6   # × の線の太さ（画面上のピクセル）
REGION_SCREEN_WIDTH = 2.0  # 平均蛍光強度を測る範囲の縁の太さ（画面上のピクセル）
REGION_COLOR = "white"
# napari の既定（nearest）だと、縮小表示で画素が間引かれてざらつき、拡大で四角く見える
INTERPOLATION = "cubic"
# 範囲の描き方（③ のボタン）と、napari の図形レイヤーのモード
REGION_MODES = {"pan": "pan_zoom", "select": "select", "rectangle": "add_rectangle",
                "ellipse": "add_ellipse", "polygon": "add_polygon", "lasso": "add_polygon_lasso"}
_FINISHED = {"added", "changed", "removed"}
MIN_REGION_PX = 1.0  # これより小さい範囲（クリックしただけの四角形など）は捨てる


def _polygon_area(points: np.ndarray) -> float:
    y, x = points[:, 0], points[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


class Canvas(QWidget):
    """クリックは clicked(y, x) で知らせる。ドラッグは napari 標準の「画像を動かす」のまま。"""

    clicked = Signal(float, float)
    tab_changed = Signal()
    regions_edited = Signal(list)      # 描き終えた・動かした・消した範囲（list[Region]）
    region_mode_changed = Signal(str)  # REGION_MODES のキー

    def __init__(self) -> None:
        super().__init__()
        self.model = ViewerModel(title="cellcounter")
        self.view = QtViewer(self.model)
        # ドロップは親のウィンドウで受ける（napari に任せると .czi を読めずエラーになる）
        self.view.setAcceptDrops(False)
        for action in (*REPLACED_NAPARI_ACTIONS, *UNUSED_NAPARI_ACTIONS):
            action_manager.unbind_shortcut(action)
        # Ctrl+ホイール（次元を動かす）と Alt+ホイール（レイヤーを選ぶ）も、この画面では使わない
        self.model.mouse_wheel_callbacks.clear()

        self.banner = QLabel()
        self.banner.setStyleSheet("color: #c00000; font-weight: bold; padding: 2px;")
        self.banner.hide()
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.currentChanged.connect(self._on_tab)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.banner)
        layout.addWidget(self.tabs)
        layout.addWidget(self.view, 1)

        self.model.mouse_drag_callbacks.append(self._on_drag)
        self.model.mouse_move_callbacks.append(self._on_move)
        self.model.scene.camera.events.zoom.connect(lambda _event: self._fit_mark_width())
        self._session: Session | None = None
        self._markers: list[str | None] = [None]
        self._images: dict[int, object] = {}
        self._outline = None
        self._marks = None
        self._regions = None
        self._updating_regions = False
        self._hovered: int | None = None
        self._um = 1.0
        self.marks_visible = True

    def current_marker(self) -> str | None:
        """いま開いている組み合わせのマーカー。「DAPI のみ」なら None。"""
        return self._markers[max(self.tabs.currentIndex(), 0)]

    def mark_count(self) -> int:
        """いま画面に出ている × の数。"""
        return len(self._marks.data) // 2

    def set_banner(self, text: str) -> None:
        self.banner.setText(text)
        self.banner.setVisible(bool(text))

    def show_session(self, session: Session) -> None:
        """画像を読み込んだとき、開き直したときに、レイヤーを作り直す。"""
        self.model.layers.clear()
        self._session, self._images, self._hovered = session, {}, None
        # レイヤーを µm 単位で置くと、napari のスケールバーが実寸で出る
        self._um = session.um_per_px
        placed = {"scale": (self._um, self._um), "units": ("µm", "µm")}
        full = full_scale(session.bits)
        for row in session.table.rows:
            # ZEN で付けた色のまま重ねる（黒 → その色）
            colormap = Colormap([[0.0, 0.0, 0.0, 1.0], [*rgb_of(row.color), 1.0]], name=row.name)
            layer = self.model.add_image(
                session.image.planes[row.index], name=row.name, blending="additive",
                colormap=colormap, contrast_limits=session.contrast_limits(row.index),
                interpolation2d=INTERPOLATION, visible=False, **placed)
            layer.contrast_limits_range = (0.0, full)
            self._images[row.index] = layer
        shape = session.image.planes.shape[1:]
        self._outline = self.model.add_labels(
            np.zeros(shape, np.int32), name="選んでいる核", opacity=1.0,
            colormap=DirectLabelColormap(color_dict={None: "white", 0: "transparent"}), **placed)
        self._outline.contour = 2
        self._outline.show_selected_label = True
        self._outline.visible = False
        self._marks = self.model.add_vectors(np.empty((0, 2, 2)), name="×", vector_style="line",
                                             length=1, opacity=1.0, **placed)
        self._regions = self.model.add_shapes(
            None, ndim=2, name="測る範囲", edge_color=REGION_COLOR, face_color="transparent",
            opacity=1.0, features={"label": np.array([], dtype=str)},
            text={"string": "{label}", "color": REGION_COLOR, "anchor": "upper_left", "size": 11},
            **placed)
        self._regions.current_edge_color = REGION_COLOR
        self._regions.current_face_color = "transparent"
        self._regions.feature_defaults = {"label": ""}
        self._regions.visible = False
        self._regions.events.data.connect(self._on_region_data)
        self._regions.events.mode.connect(lambda _event: self.region_mode_changed.emit(
            self.region_mode()))
        self.model.canvas.overlays.scale_bar.visible = True
        # レイヤーを選んだ状態にしない（選ぶと、napari のレイヤー用のキーが効いてしまう）
        self.model.layers.selection.clear()
        self.model.reset_view()
        self.refresh()

    def set_markers(self, markers: list[str]) -> None:
        """組み合わせのタブを作り直す。開いていた組み合わせが残っていれば、そこに戻る。"""
        if [None, *markers] == self._markers and self.tabs.count():
            self.refresh()
            return
        current = self.current_marker()
        self._markers = [None, *markers]
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for marker in self._markers:
            self.tabs.addTab(tab_name(marker))
        self.tabs.setCurrentIndex(self._markers.index(current) if current in self._markers else 0)
        self.tabs.blockSignals(False)
        self.refresh()

    def step_tab(self, step: int) -> None:
        if self.tabs.count():
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def set_contrast(self, channel_index: int, low: float, high: float) -> None:
        self._images[channel_index].contrast_limits = (low, high)

    def set_marks_visible(self, visible: bool) -> None:
        self.marks_visible = visible
        if self._marks is not None:
            self._marks.visible = visible

    def refresh(self) -> None:
        """背景・輪郭・×・範囲を、いまの組み合わせと作業状態に合わせる。"""
        session = self._session
        if session is None:
            return
        marker = self.current_marker()
        shown = session.shown_channels(marker)
        for index, layer in self._images.items():
            layer.visible = index in shown
        if session.labels is not None:
            self._outline.data = session.labels
        self._draw_marks(marker)
        self._show_regions(marker == IMV_TAB)

    # ---- 平均蛍光強度を測る範囲 ---------------------------------------------------

    def region_mode(self) -> str:
        mode = str(self._regions.mode) if self._regions is not None else "pan_zoom"
        return next((key for key, value in REGION_MODES.items() if value == mode), "pan")

    def set_region_mode(self, key: str) -> None:
        """③ のボタンで選んだ描き方にする。キー操作（Esc・Delete）がすぐ効くよう、画像に焦点を移す。"""
        if self._regions is None or self.current_marker() != IMV_TAB:
            return
        self._regions.mode = REGION_MODES[key]
        self.view.canvas.native.setFocus()

    def delete_selected_regions(self) -> None:
        if self._regions is not None and self._regions.selected_data:
            self._regions.remove_selected()

    def _show_regions(self, active: bool) -> None:
        """平均蛍光強度のタブでだけ範囲を出し、描けるようにする。ほかのタブでは隠して触れなくする。"""
        layer, session = self._regions, self._session
        if layer is None:
            return
        self._load_regions(session.regions)
        layer.visible = active
        if active and session.labels is not None:
            if self.model.layers.selection.active is not layer:
                self.model.layers.selection.active = layer
        else:
            if str(layer.mode) != "pan_zoom":
                layer.mode = "pan_zoom"
            # レイヤーを選んだ状態にしない（選ぶと、napari のレイヤー用のキーが効いてしまう）
            self.model.layers.selection.clear()

    def _creating(self) -> bool:
        return bool(getattr(self._regions, "_is_creating", False))

    def _layer_regions(self) -> list[Region | None]:
        """レイヤーの図形を範囲にする。範囲にならないもの（線・小さすぎるもの）は None。"""
        found = []
        for data, kind in zip(self._regions.data, self._regions.shape_type):
            region = None
            if kind in SHAPE_LABELS:
                try:
                    region = Region.of(kind, data)
                except ValueError:
                    region = None
            if region is not None and _polygon_area(region.outline()) < MIN_REGION_PX:
                region = None
            found.append(region)
        return found

    def _load_regions(self, regions: list[Region]) -> None:
        """作業状態の範囲をレイヤーに写す（元に戻す・作業ファイルを開いたときなど）。描いている途中は触らない。"""
        if self._creating() or same_regions(self._layer_regions(), list(regions)):
            return
        layer = self._regions
        self._updating_regions = True
        try:
            layer.selected_data = set()
            layer.data = []
            if regions:
                layer.add([np.array(region.points) for region in regions],
                          shape_type=[region.shape for region in regions],
                          edge_color=REGION_COLOR, face_color="transparent")
            self._number_regions()
        finally:
            self._updating_regions = False
        self._fit_mark_width()

    def _number_regions(self) -> None:
        """範囲の左上に、③ や Excel の「範囲 1」「範囲 2」と同じ番号を出す。"""
        self._regions.features = {"label": [str(number)
                                            for number in range(1, self._regions.nshapes + 1)]}

    def _on_region_data(self, event) -> None:
        if self._updating_regions or str(getattr(event, "action", "")) not in _FINISHED:
            return
        # napari は描き終える前にも「足した」と知らせるので、処理が一段落してから読む
        QTimer.singleShot(0, self._emit_regions)

    def _emit_regions(self) -> None:
        if self._regions is None or self._creating():
            return
        regions = [region for region in self._layer_regions() if region is not None]
        if not same_regions(regions, self._session.regions):
            self.regions_edited.emit(regions)
        # 捨てた図形（小さすぎる・線）を消し、番号を付け直す
        self._load_regions(self._session.regions)
        self._updating_regions = True
        try:
            if len(self._regions.features) == self._regions.nshapes:
                self._number_regions()
        finally:
            self._updating_regions = False
        self._fit_mark_width()

    def _draw_marks(self, marker: str | None) -> None:
        """× を 2 本の細い線で描く。核 1 個につき線が 2 本。平均蛍光強度のタブでは描かない。"""
        session = self._session
        lines, colors = [], []
        if session.labels is not None and (marker is None or marker in session.judgements):
            half = max(3.0, session.diameter_px * MARK_HALF_LENGTH)
            for nucleus in session.nuclei.values():
                kind = session.category(marker, nucleus.id)
                if kind is None:
                    continue
                y, x = nucleus.y, nucleus.x
                lines += [[[y - half, x - half], [2 * half, 2 * half]],
                          [[y - half, x + half], [2 * half, -2 * half]]]
                colors += [(*(value / 255 for value in COLORS[kind]), 1.0)] * 2
        self._marks.data = np.array(lines, dtype=float).reshape(-1, 2, 2)
        if lines:
            self._marks.edge_color = np.array(colors)
        self._marks.visible = self.marks_visible
        self._fit_mark_width()

    def _fit_mark_width(self) -> None:
        """拡大・縮小しても、× と範囲の線が画面上で同じ太さに見えるようにする。"""
        on_screen = max(self.model.scene.camera.zoom * self._um, 1e-6)
        if self._marks is not None:
            self._marks.edge_width = MARK_SCREEN_WIDTH / on_screen
        if self._regions is not None:
            width = REGION_SCREEN_WIDTH / on_screen
            self._regions.current_edge_width = width
            if self._regions.nshapes:
                self._regions.edge_width = width

    def _on_tab(self, _index: int) -> None:
        self.refresh()
        self.tab_changed.emit()

    def _on_drag(self, _model, event):
        if event.button != 1:
            return
        start = np.array(event.pos, dtype=float)
        yield
        while event.type == "mouse_move":
            yield
        if np.hypot(*(np.array(event.pos, dtype=float) - start)) <= CLICK_TOLERANCE_PX:
            y, x = self._pixel(event)
            self.clicked.emit(y, x)

    def _pixel(self, event) -> tuple[float, float]:
        """マウスの位置（µm）を、画像の画素の位置にする。"""
        y, x = event.position[-2:]
        return float(y) / self._um, float(x) / self._um

    def _on_move(self, _model, event) -> None:
        """カーソルの下の核の輪郭を出して、どの核を選んでいるかを見分けやすくする。"""
        session = self._session
        if session is None or session.labels is None:
            return
        try:
            # 平均蛍光強度のタブでは核を直さないので、輪郭も出さない
            hovered = None if self.current_marker() == IMV_TAB else session.nucleus_at(
                *self._pixel(event))
        except ValueError:
            hovered = None
        if hovered != self._hovered:
            self._hovered = hovered
            self._show_outline(hovered)

    def _show_outline(self, nucleus_id: int | None) -> None:
        """核を 1 つ選んで輪郭を出す。None なら消す。

        napari は、非表示のレイヤーの中身を 1×1・8 bit の仮のものに差し替えることがある
        （× が画像の端からはみ出して、表示範囲が変わったときなど）。そのまま 256 以上の
        核を選ぶと OverflowError になるので、必ず表示してから選ぶ。
        """
        outline = self._outline
        if nucleus_id is None:
            outline.visible = False
            return
        if not outline.visible:
            outline.visible = True
        outline.selected_label = nucleus_id
