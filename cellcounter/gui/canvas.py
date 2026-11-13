"""画像の表示部（napari）と、その上に並べる組み合わせのタブ。"""

from __future__ import annotations

import numpy as np
from napari.components import ViewerModel
from napari.qt import QtViewer
from napari.utils.action_manager import action_manager
from napari.utils.colormaps import Colormap, DirectLabelColormap
from qtpy.QtCore import Signal
from qtpy.QtWidgets import QLabel, QTabBar, QVBoxLayout, QWidget

from ..overlay import COLORS, rgb_of
from ..quality import full_scale
from ..session import Session, tab_name
from .shortcuts import REPLACED_NAPARI_ACTIONS

CLICK_TOLERANCE_PX = 4.0
MARK_HALF_LENGTH = 0.30   # 核の標準直径に対する、× の腕の長さ
MARK_SCREEN_WIDTH = 1.6   # × の線の太さ（画面上のピクセル）


class Canvas(QWidget):
    """クリックは clicked(y, x) で知らせる。ドラッグは napari 標準の「画像を動かす」のまま。"""

    clicked = Signal(float, float)
    tab_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.model = ViewerModel(title="cellcounter")
        self.view = QtViewer(self.model)
        # ドロップは親のウィンドウで受ける（napari に任せると .czi を読めずエラーになる）
        self.view.setAcceptDrops(False)
        for action in REPLACED_NAPARI_ACTIONS:
            action_manager.unbind_shortcut(action)

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
        self._hovered: int | None = None
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
        full = full_scale(session.bits)
        for row in session.table.rows:
            # ZEN で付けた色のまま重ねる（黒 → その色）
            colormap = Colormap([[0.0, 0.0, 0.0, 1.0], [*rgb_of(row.color), 1.0]], name=row.name)
            layer = self.model.add_image(
                session.image.planes[row.index], name=row.name, blending="additive",
                colormap=colormap, contrast_limits=session.contrast_limits(row.index),
                visible=False)
            layer.contrast_limits_range = (0.0, full)
            self._images[row.index] = layer
        shape = session.image.planes.shape[1:]
        self._outline = self.model.add_labels(
            np.zeros(shape, np.int32), name="選んでいる核", opacity=1.0,
            colormap=DirectLabelColormap(color_dict={None: "white", 0: "transparent"}))
        self._outline.contour = 2
        self._outline.show_selected_label = True
        self._outline.visible = False
        self._marks = self.model.add_vectors(np.empty((0, 2, 2)), name="×", vector_style="line",
                                             length=1, opacity=1.0)
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
        """背景・輪郭・× を、いまの組み合わせと作業状態に合わせる。"""
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

    def _draw_marks(self, marker: str | None) -> None:
        """× を 2 本の細い線で描く。核 1 個につき線が 2 本。"""
        session = self._session
        lines, colors = [], []
        if session.labels is not None and (marker is None or marker in session.judgements):
            half = max(3.0, session.diameter_px * MARK_HALF_LENGTH)
            for nucleus in session.nuclei.values():
                kind = session.marks.category(marker, nucleus.id)
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
        """拡大・縮小しても、× の線が画面上で同じ太さに見えるようにする。"""
        if self._marks is not None:
            self._marks.edge_width = MARK_SCREEN_WIDTH / max(self.model.scene.camera.zoom, 1e-6)

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
            y, x = event.position[-2:]
            self.clicked.emit(float(y), float(x))

    def _on_move(self, _model, event) -> None:
        """カーソルの下の核の輪郭を出して、どの核を選んでいるかを見分けやすくする。"""
        session = self._session
        if session is None or session.labels is None:
            return
        y, x = event.position[-2:]
        try:
            hovered = session.nucleus_at(y, x)
        except ValueError:
            hovered = None
        if hovered != self._hovered:
            self._hovered = hovered
            self._outline.selected_label = hovered or 0
            self._outline.visible = hovered is not None
