"""ウィンドウ本体。メニュー・パネル・段階の表示と、開く → 判定 → 修正 → 出力の流れ。"""

from __future__ import annotations

import os
from dataclasses import asdict

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox,
                            QProgressBar, QScrollArea, QSplitter, QTabWidget)

from .. import __version__
from ..channels import apply_preset, build_table, preset_of
from ..control import collect_control
from ..czi import list_scenes, read_scene
from ..export import RESULTS_NAME, default_folder, export_results
from ..pipeline import open_session, run_detection, run_judgement
from ..project import EXTENSION, load_project, save_project
from ..session import Session
from ..settings import Settings
from ..userdata import UserData
from .canvas import Canvas
from .dialogs import confirm, show_error, show_export_done, show_help
from .file_panel import FilePanel
from .output_panel import OutputPanel
from .review_panel import ReviewPanel
from .setup_panel import SetupPanel
from .shortcuts import SHORTCUTS, make_action
from .worker import TaskRunner

PROVISIONAL_BANNER = "暫定（陰性対照なし）: 固定の閾値で判定しています。陽性率は参考値です。"
PANEL_FILE, PANEL_SETUP, PANEL_REVIEW, PANEL_OUTPUT = range(4)
_MENUS = (("ファイル", ("open", "open_project", "save_project")), ("編集", ("undo", "redo")),
          ("表示", ("next_tab", "previous_tab")), ("実行", ("judge", "export")), ("ヘルプ", ("help",)))


class MainWindow(QMainWindow):
    def __init__(self, userdata: UserData | None = None) -> None:
        super().__init__()
        self.userdata = userdata or UserData()
        self.session: Session | None = None
        self._detected_with: dict | None = None
        self._control_cache: tuple[str, object] | None = None
        self._exported = False
        self._stale = False

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
        self.runner.busy_changed.connect(self._refresh)
        self.runner.failed.connect(
            lambda title, error: show_error(self, f"{title}に失敗しました", error,
                                            self.userdata.log_path))

        slots = {"open": self.choose_czi, "open_project": self.choose_project,
                 "save_project": self.save_work, "judge": self.judge, "export": self.export,
                 "undo": self.undo, "redo": self.redo, "help": lambda: show_help(self),
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
        self.file_panel.load_requested.connect(self.load_scene)
        self.setup_panel.changed.connect(self._on_setup_changed)
        self.setup_panel.judge_requested.connect(self.judge)
        self.review_panel.undo_requested.connect(self.undo)
        self.review_panel.redo_requested.connect(self.redo)
        self.review_panel.contrast_changed.connect(self._on_contrast)
        self.output_panel.export_requested.connect(self.export)
        self.output_panel.save_requested.connect(self.save_work)
        self.canvas.clicked.connect(self._on_click)
        self.canvas.tab_changed.connect(self._refresh)
        self._show_recent()
        self._refresh()
        if self.userdata.notice:
            self.message_label.setText(self.userdata.notice)

    @property
    def judged(self) -> bool:
        return self.session is not None and self.session.labels is not None

    # ---- 開く -------------------------------------------------------------

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
        """.czi ならシーンを並べ、1 つしか無ければそのまま読み込む。作業ファイルなら再開する。"""
        if self.runner.busy or not self._may_discard():
            return
        if path.lower().endswith(EXTENSION):
            self._open_project(path)
            return
        try:
            scenes = list_scenes(path)
        except (OSError, ValueError) as error:
            show_error(self, "ファイルを開けません", error, self.userdata.log_path)
            return
        self.file_panel.set_scenes(path, scenes)
        self.panels.setCurrentIndex(PANEL_FILE)
        if len(scenes) == 1:
            self.load_scene(path, scenes[0].index, self.file_panel.z_projection())
        else:
            self.message_label.setText("シーンを選んで [このシーンを読み込む] を押してください。")

    def load_scene(self, path: str, scene: int, z_projection: str) -> None:
        if self.runner.busy:
            return

        def task():
            yield "読み込んでいます"
            return read_scene(path, scene, z_projection)

        def done(image) -> None:
            if not image.meta.um_per_px:
                value, accepted = QInputDialog.getDouble(
                    self, "µm/px が分かりません",
                    "メタデータに画素の大きさがありません。µm/px を入力してください。",
                    0.3, 0.001, 100.0, 4)
                if not accepted:
                    return
                image.meta.um_per_px = value
            table = build_table(image.meta)
            note = ""
            if self.userdata.last_table:
                try:
                    apply_preset(table, self.userdata.last_table)
                except ValueError:
                    table = build_table(image.meta)
                    note = "前回の設定はこの画像のチャンネルと合わないため、使っていません。"
            settings = Settings(z_projection=z_projection)
            self.setup_panel.apply_to(settings)
            self._show_session(open_session(image, table, settings))
            self.userdata.add_recent(path)
            self._show_recent()
            self.panels.setCurrentIndex(PANEL_SETUP)
            self.message_label.setText(note)

        self.runner.start("読み込み", task, done)

    def _open_project(self, path: str, czi_path: str | None = None) -> None:
        def task():
            yield "作業ファイルを開いています"
            try:
                return load_project(path, czi_path)
            except FileNotFoundError as error:
                return error

        def done(result) -> None:
            if isinstance(result, FileNotFoundError):
                moved, _ = QFileDialog.getOpenFileName(
                    self, "元の .czi が見つかりません。場所を教えてください", "", "CZI (*.czi)")
                if moved:
                    self._open_project(path, moved)
                return
            self._show_session(result)
            self._detected_with = asdict(result.settings.detection)
            self.userdata.add_recent(path)
            self._show_recent()
            self.panels.setCurrentIndex(PANEL_REVIEW if result.judgements else PANEL_SETUP)

        self.runner.start("作業ファイルの読み込み", task, done)

    def _show_session(self, session: Session) -> None:
        self.session = session
        self._detected_with, self._control_cache = None, None
        self._exported = self._stale = False
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
        self.canvas.show_session(session)
        self._refresh()

    # ---- 判定・修正・出力 ---------------------------------------------------

    def judge(self) -> None:
        session = self.session
        if session is None or self.runner.busy:
            return
        problems = session.table.problems()
        if problems:
            QMessageBox.warning(self, "チャンネル表を直してください", "\n".join(problems))
            self.panels.setCurrentIndex(PANEL_SETUP)
            return
        if session.history.can_undo and not confirm(
                self, "判定し直しますか？", "手で直した × は消えます。判定し直しますか？"):
            return
        self.setup_panel.apply_to(session.settings)
        sources = self.setup_panel.control_sources()
        detection = asdict(session.settings.detection)
        detect = session.labels is None or detection != self._detected_with
        measured = {**session.settings.to_dict(), "judge": {
            **asdict(session.settings.judge), "control_percentile": None}}
        # 対照の値は、対照のファイル・チャンネル表・設定が同じなら測り直さない
        key = repr((sources, session.table.to_list(), measured))
        cached = None
        if self._control_cache and self._control_cache[0] == key:
            cached = self._control_cache[1]

        def task():
            if detect:
                yield "核を検出しています（Cellpose）"
                run_detection(session)
            control = cached
            if sources and control is None:
                yield f"陰性対照を測っています（{len(sources)} シーン）"
                control = collect_control(session, sources)
            yield "判定しています"
            run_judgement(session, control)
            return control

        def done(control) -> None:
            self._detected_with = detection
            self._control_cache = (key, control) if control else None
            self._exported = self._stale = False
            self.userdata.remember_table(preset_of(session.table, "前回の設定"))
            self.panels.setCurrentIndex(PANEL_REVIEW)
            self._refresh()

        self.runner.start("判定", task, done)

    def export(self) -> None:
        session = self.session
        if not self.judged or self.runner.busy:
            return
        folder = self.output_panel.folder.text().strip() or default_folder(session.image.path)
        if os.path.isfile(os.path.join(folder, RESULTS_NAME)) and not confirm(
                self, "上書きしますか？", f"このフォルダには前の結果があります。上書きしますか？\n{folder}"):
            return

        def task():
            yield "結果を書き出しています"
            return export_results(session, folder)

        def done(written: str) -> None:
            self._exported = True
            self.output_panel.result.setText(f"出力しました: {written}")
            self._refresh()
            show_export_done(self, written)

        self.runner.start("出力", task, done)

    def save_work(self) -> None:
        session = self.session
        if not self.judged or self.runner.busy:
            return
        stem = os.path.splitext(session.image.path)[0]
        path, _ = QFileDialog.getSaveFileName(self, "作業を保存", stem + EXTENSION,
                                              f"作業ファイル (*{EXTENSION})")
        if not path:
            return
        try:
            save_project(session, path)
        except OSError as error:
            show_error(self, "作業を保存できません", error, self.userdata.log_path)
            return
        session.dirty = False
        self.message_label.setText(f"作業を保存しました: {os.path.basename(path)}")

    def undo(self) -> None:
        if self.judged and not self.runner.busy and self.session.undo():
            self._after_edit("元に戻しました")

    def redo(self) -> None:
        if self.judged and not self.runner.busy and self.session.redo():
            self._after_edit("やり直しました")

    def _on_click(self, y: float, x: float) -> None:
        session, marker = self.session, self.canvas.current_marker()
        if session is None or self.runner.busy:
            return
        if session.labels is None or (marker is not None and marker not in session.judgements):
            self.message_label.setText("先に [判定] を押してください。")
            return
        try:
            message = session.click(marker, y, x)
        except ValueError:
            return
        self._after_edit(message)

    def _after_edit(self, message: str) -> None:
        self._exported = False
        self.message_label.setText(message)
        self._refresh()

    def _on_contrast(self, channel_index: int, low: float, high: float) -> None:
        self.session.contrast[channel_index] = (low, high)
        self.canvas.set_contrast(channel_index, low, high)

    def _on_setup_changed(self) -> None:
        self._stale = bool(self.session and self.session.judgements)
        self._refresh()

    # ---- 表示の更新 ---------------------------------------------------------

    def _refresh(self, *_ignored) -> None:
        """いまの状態に合わせて、タブ・ボタンの有効無効・段階の表示・タイトルをそろえる。"""
        session, busy = self.session, self.runner.busy
        title = f"cellcounter {__version__}"
        if session is not None:
            title += f" — {os.path.basename(session.image.path)}"
            ready = [row.marker for row in session.table.judged() if row.marker]
            self.canvas.set_markers(list(session.judgements) if session.judgements else ready)
            self.canvas.set_banner(PROVISIONAL_BANNER if session.provisional else "")
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
                   "export": self.judged and not busy, "save_project": self.judged and not busy,
                   "undo": self.judged and not busy and session.history.can_undo,
                   "redo": self.judged and not busy and session.history.can_redo}
        for name, state in enabled.items():
            self.actions_by_name[name].setEnabled(state)

        if not self.judged:
            review = "③未判定"
        elif self._stale:
            review = "③設定を変えました（[判定] をやり直してください）"
        else:
            review = "③修正中"
        steps = ("①読み込み ✓" if session else "①読み込み",
                 "②設定 ✓" if configured else "②設定", review,
                 "④出力済み ✓" if self._exported else "④未出力")
        self.stage_label.setText(" → ".join(steps))

    def _show_recent(self) -> None:
        self.file_panel.set_recent(self.userdata.recent_files)
        self.recent_menu.clear()
        for path in self.userdata.recent_files:
            self.recent_menu.addAction(path, lambda _checked=False, p=path: self.open_path(p))

    def _may_discard(self) -> bool:
        if self.session is None or not self.session.dirty:
            return True
        return confirm(self, "まだ出力していない修正があります",
                       "出力も保存もしていない × の修正があります。破棄して続けますか？")

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
        elif self._may_discard():
            event.accept()
        else:
            event.ignore()
