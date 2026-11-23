"""ウィンドウ本体。メニュー・パネル・段階の表示と、× の修正の操作。"""

from __future__ import annotations

import os

from qtpy.QtCore import Qt, QTimer
from qtpy.QtWidgets import (QFileDialog, QLabel, QMainWindow, QMessageBox, QProgressBar,
                            QScrollArea, QSplitter, QTabWidget)

from .. import __version__
from ..czi import list_scenes
from ..export import default_folder
from ..intensity import Region
from ..markers import use_dictionary
from ..project import EXTENSION
from ..session import IMV_TAB, Session
from ..userdata import UserData
from . import flows
from .canvas import Canvas
from .dialogs import confirm, show_error, show_help
from .file_panel import FilePanel
from .flows import PANEL_OUTPUT, PANEL_REVIEW, PANEL_SETUP
from .output_panel import OutputPanel
from .review_panel import ReviewPanel
from .setup_panel import SetupPanel
from .shortcuts import SHORTCUTS, make_action
from .worker import TaskRunner

PROVISIONAL_BANNER = "暫定（陰性対照なし）: 固定の閾値で判定しています。陽性率は参考値です。"
BLIND_BANNER = "目視判定モード: 自動判定を隠しています。マーカーのタブで、陽性だと思う核に × を付けてください。"
AUTOSAVE_INTERVAL_MS = 60_000
_MENUS = (("ファイル", ("open", "open_project", "save_project")), ("編集", ("undo", "redo")),
          ("表示", ("next_tab", "previous_tab")),
          ("実行", ("judge", "export", "batch", "batch_refresh")), ("操作", ("dictionary",)),
          ("ヘルプ", ("help",)))
IMV_CLICK_HINT = "平均蛍光強度のタブでは、③ の「測る範囲」で描き方を選んでから、画像の上で範囲を描きます。"


class MainWindow(QMainWindow):
    def __init__(self, userdata: UserData | None = None) -> None:
        super().__init__()
        self.userdata = userdata or UserData()
        # マーカー名を入れたときに引く辞書を、この利用者のもの（操作 → 辞書登録で編集したもの）にする
        use_dictionary(self.userdata.markers)
        self.session: Session | None = None
        self.detected_with: dict | None = None
        self.control_cache: tuple[str, object] | None = None
        self.exported = False
        self.stale = False

        self.canvas = Canvas()
        self.file_panel = FilePanel()
        self.setup_panel = SetupPanel(self.userdata)
        self.review_panel = ReviewPanel()
        self.output_panel = OutputPanel()
        self.panels = QTabWidget()
        titles = ("① ファイル", "② 設定", "③ 判定・修正", "④ 出力")
        for title, panel in zip(titles, (self.file_panel, self.setup_panel, self.review_panel,
                                         self.output_panel)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            self.panels.addTab(scroll, title)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.panels)
        self.setCentralWidget(splitter)
        self.setAcceptDrops(True)
        self.resize(1500, 900)
        splitter.setSizes([960, 540])

        self.stage_label, self.message_label, task_label = QLabel(), QLabel(), QLabel()
        bar = QProgressBar()
        bar.setMaximumWidth(160)
        self.statusBar().addWidget(self.stage_label, 1)
        self.statusBar().addPermanentWidget(self.message_label)
        self.statusBar().addPermanentWidget(task_label)
        self.statusBar().addPermanentWidget(bar)
        self.runner = TaskRunner(bar, task_label)
        self.runner.busy_changed.connect(self.refresh)
        self.runner.failed.connect(
            lambda title, error: show_error(self, f"{title}に失敗しました", error,
                                            self.userdata.log_path))

        slots = {"open": self.choose_czi, "open_project": self.choose_project,
                 "save_project": self.save_work, "judge": self.judge, "export": self.export,
                 "undo": self.undo, "redo": self.redo, "help": lambda: show_help(self),
                 "batch": lambda: flows.batch(self),
                 "batch_refresh": lambda: flows.batch_refresh(self),
                 "dictionary": lambda: flows.edit_dictionary(self),
                 "next_tab": lambda: self.canvas.step_tab(1),
                 "previous_tab": lambda: self.canvas.step_tab(-1)}
        self.actions_by_name = {entry.name: make_action(self, entry.name, slots[entry.name])
                                for entry in SHORTCUTS}
        for title, names in _MENUS:
            menu = self.menuBar().addMenu(title)
            for name in names:
                menu.addAction(self.actions_by_name[name])
            if title == "ファイル":
                self.recent_menu = menu.addMenu("最近使ったファイル")
                menu.addSeparator()
                menu.addAction("終了", self.close)

        self.file_panel.open_requested.connect(self.choose_czi)
        self.file_panel.open_project_requested.connect(self.choose_project)
        self.file_panel.recent_chosen.connect(self.open_path)
        self.file_panel.load_requested.connect(lambda *args: flows.load_scene(self, *args))
        self.setup_panel.changed.connect(self._on_setup_changed)
        self.setup_panel.judge_requested.connect(self.judge)
        self.review_panel.undo_requested.connect(self.undo)
        self.review_panel.redo_requested.connect(self.redo)
        self.review_panel.contrast_changed.connect(self._on_contrast)
        self.review_panel.channel_toggled.connect(self._on_channel_toggled)
        self.review_panel.marks_toggled.connect(self.canvas.set_marks_visible)
        self.review_panel.blind_toggled.connect(self._on_blind)
        self.review_panel.region_mode_requested.connect(self.canvas.set_region_mode)
        self.review_panel.delete_regions_requested.connect(self.canvas.delete_selected_regions)
        self.review_panel.clear_regions_requested.connect(lambda: self._on_regions_edited([]))
        self.canvas.region_mode_changed.connect(self.review_panel.show_region_mode)
        self.canvas.regions_edited.connect(self._on_regions_edited)
        self.output_panel.export_requested.connect(self.export)
        self.output_panel.save_requested.connect(self.save_work)
        self.canvas.clicked.connect(self._on_click)
        self.canvas.tab_changed.connect(self.refresh)
        self.show_recent()
        self.refresh()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(lambda: flows.autosave(self))
        self._autosave_timer.start(AUTOSAVE_INTERVAL_MS)
        if self.userdata.notice:
            self.message_label.setText(self.userdata.notice)

    @property
    def judged(self) -> bool:
        return self.session is not None and self.session.labels is not None

    # ---- メニューとボタンから呼ばれる操作 -------------------------------------

    def choose_czi(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, ".czi を開く", "", "CZI (*.czi)")
        if path:
            self.open_path(path)

    def choose_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "作業ファイルを開く", "",
                                              f"作業ファイル (*{EXTENSION})")
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        flows.open_path(self, path)

    def judge(self) -> None:
        flows.judge(self)

    def export(self) -> None:
        flows.export(self)

    def save_work(self) -> None:
        flows.save_work(self)

    def undo(self) -> None:
        if self.judged and not self.runner.busy and self.session.undo():
            self._after_edit("元に戻しました")

    def redo(self) -> None:
        if self.judged and not self.runner.busy and self.session.redo():
            self._after_edit("やり直しました")

    def show_session(self, session: Session) -> None:
        """読み込んだ画像（または開き直した作業）を、すべてのパネルに反映する。"""
        self.session = session
        self.detected_with, self.control_cache = None, None
        self.exported = self.stale = False
        image = session.image
        self.file_panel.set_scenes(image.path, list_scenes(image.path)
                                   if os.path.isfile(image.path) else [])
        self.file_panel.show_loaded(
            image.path, image.scene, image.z_projection,
            f"{image.planes.shape[2]}×{image.planes.shape[1]} px ／ {session.um_per_px:.4f} µm/px ／ "
            f"{session.bits} bit ／ {image.meta.objective or '対物は取得できず'}")
        self.setup_panel.set_table(session.table)
        self.setup_panel.show_settings(session.settings)
        self.review_panel.show_session(session)
        self.output_panel.folder.setText(default_folder(image.path))
        self.output_panel.name.clear()
        self.canvas.show_session(session)
        self.refresh()

    # ---- 画面からの知らせ ---------------------------------------------------

    def _on_click(self, y: float, x: float) -> None:
        session, marker = self.session, self.canvas.current_marker()
        if session is None or self.runner.busy:
            return
        if session.labels is None or (marker not in (None, IMV_TAB)
                                      and marker not in session.judgements):
            self.message_label.setText("先に [判定] を押してください。")
            return
        if marker == IMV_TAB:
            # クリックは範囲を描く操作（多角形の頂点など）なので、核は直さない
            if self.canvas.region_mode() == "pan":
                self.message_label.setText(IMV_CLICK_HINT)
            return
        try:
            message = session.click(marker, y, x)
        except ValueError:
            return
        self._after_edit(message)

    def _after_edit(self, message: str) -> None:
        self.exported = False
        self.message_label.setText(message)
        self.refresh()

    def _on_contrast(self, channel_index: int, low: float, high: float) -> None:
        self.session.contrast[channel_index] = (low, high)
        self.canvas.set_contrast(channel_index, low, high)

    def _on_channel_toggled(self, channel_index: int, visible: bool) -> None:
        """背景に出す画像を、いま開いている組み合わせのタブについて変える。"""
        self.session.set_shown(self.canvas.current_marker(), channel_index, visible)
        self.canvas.refresh()

    def _on_blind(self, active: bool) -> None:
        self.session.set_blind(active)
        self.refresh()

    def _on_regions_edited(self, regions: list[Region]) -> None:
        """平均蛍光強度を測る範囲を描いた・動かした・消した。元に戻せるよう作業の履歴に積む。"""
        session = self.session
        if session is None or self.runner.busy:
            return
        if session.set_regions(regions):
            count = len(session.regions)
            self._after_edit(f"測る範囲を変えました（{count} 個）" if count
                             else "測る範囲を消しました（画像全体を測ります）")

    def _on_setup_changed(self) -> None:
        self.stale = bool(self.session and (self.session.judgements or self.session.imv_channels))
        self.refresh()

    # ---- 表示の更新 ---------------------------------------------------------

    def refresh(self, *_ignored) -> None:
        """いまの状態に合わせて、タブ・ボタンの有効無効・段階の表示・タイトルをそろえる。"""
        session, busy = self.session, self.runner.busy
        title = f"cellcounter {__version__}"
        if session is not None:
            title += f" — {os.path.basename(session.image.path)}"
            if session.judgements or session.imv_channels:
                markers = list(session.judgements)
            else:
                markers = [row.marker for row in session.table.judged() if row.marker]
            # 平均蛍光強度で測るマーカーは、まとめて 1 つのタブにする
            self.canvas.set_markers(markers + ([IMV_TAB] if session.imv_markers() else []))
            banner = PROVISIONAL_BANNER if session.provisional else ""
            self.canvas.set_banner(BLIND_BANNER if session.blind_active else banner)
            self.review_panel.refresh(session, self.canvas.current_marker())
            self.setup_panel.show_warnings(session.warnings)
        self.setWindowTitle(title)

        configured = session is not None and not session.table.problems()
        self.canvas.setEnabled(not busy)
        self.panels.setEnabled(not busy)
        self.panels.setTabEnabled(PANEL_SETUP, session is not None)
        self.panels.setTabEnabled(PANEL_REVIEW, self.judged)
        self.panels.setTabEnabled(PANEL_OUTPUT, self.judged)
        self.output_panel.set_ready(self.judged and not busy)
        enabled = {"open": not busy, "open_project": not busy, "judge": configured and not busy,
                   "batch": configured and not busy, "batch_refresh": not busy,
                   "export": self.judged and not busy, "save_project": self.judged and not busy,
                   "undo": self.judged and not busy and session.history.can_undo,
                   "redo": self.judged and not busy and session.history.can_redo}
        for name, state in enabled.items():
            self.actions_by_name[name].setEnabled(state)

        if not self.judged:
            review = "③未判定"
        elif self.stale:
            review = "③設定を変えました（[判定] をやり直してください）"
        else:
            review = "③修正中"
        steps = ("①読み込み ✓" if session else "①読み込み",
                 "②設定 ✓" if configured else "②設定", review,
                 "④出力済み ✓" if self.exported else "④未出力")
        self.stage_label.setText(" → ".join(steps))

    def show_recent(self) -> None:
        self.file_panel.set_recent(self.userdata.recent_files)
        self.recent_menu.clear()
        for path in self.userdata.recent_files:
            self.recent_menu.addAction(path, lambda _checked=False, p=path: self.open_path(p))

    def may_discard(self) -> bool:
        """保存していない修正を捨ててよいか。捨てると決めたら、自動保存の控えも消す。"""
        if self.session is not None and self.session.dirty and not confirm(
                self, "まだ出力していない修正があります",
                "出力も保存もしていない × の修正があります。破棄して続けますか？"):
            return False
        self.userdata.clear_autosave()
        return True

    # ---- ウィンドウのイベント -------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if len(paths) == 1 and paths[0].lower().endswith((".czi", EXTENSION)):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.open_path(event.mimeData().urls()[0].toLocalFile())

    def closeEvent(self, event) -> None:
        if self.runner.busy:
            QMessageBox.information(self, "処理中です", "処理が終わってから閉じてください。")
            event.ignore()
        elif self.may_discard():
            event.accept()
        else:
            event.ignore()
