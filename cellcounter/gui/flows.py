"""時間のかかる流れ（開く・判定・出力・保存）。ウィンドウから呼ばれ、裏で処理を走らせる。"""

from __future__ import annotations

import os
from dataclasses import asdict

from qtpy.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from ..batch import BATCH_NAME, refresh_batch, run_batch
from ..channels import apply_preset, build_table, preset_of
from ..control import collect_control
from ..czi import list_scenes, read_scene
from ..export import RESULTS_NAME, default_folder, export_results
from ..pipeline import open_session, run_detection, run_judgement
from ..project import EXTENSION, load_project, save_project
from ..settings import Settings
from .batch_dialog import BatchDialog
from .dialogs import confirm, show_error, show_export_done

PANEL_FILE, PANEL_SETUP, PANEL_REVIEW, PANEL_OUTPUT = range(4)


def open_path(window, path: str) -> None:
    """.czi ならシーンを並べ、1 つしか無ければそのまま読み込む。作業ファイルなら再開する。"""
    if window.runner.busy or not window.may_discard():
        return
    if path.lower().endswith(EXTENSION):
        open_project(window, path)
        return
    try:
        scenes = list_scenes(path)
    except (OSError, ValueError) as error:
        show_error(window, "ファイルを開けません", error, window.userdata.log_path)
        return
    window.file_panel.set_scenes(path, scenes)
    window.panels.setCurrentIndex(PANEL_FILE)
    if len(scenes) == 1:
        load_scene(window, path, scenes[0].index, window.file_panel.z_projection())
    else:
        window.message_label.setText("シーンを選んで [このシーンを読み込む] を押してください。")


def load_scene(window, path: str, scene: int, z_projection: str) -> None:
    if window.runner.busy:
        return

    def task():
        yield "読み込んでいます"
        return read_scene(path, scene, z_projection)

    def done(image) -> None:
        if not image.meta.um_per_px:
            value, accepted = QInputDialog.getDouble(
                window, "µm/px が分かりません",
                "メタデータに画素の大きさがありません。µm/px を入力してください。",
                0.3, 0.001, 100.0, 4)
            if not accepted:
                return
            image.meta.um_per_px = value
        table = build_table(image.meta)
        note = ""
        if window.userdata.last_table:
            try:
                apply_preset(table, window.userdata.last_table)
            except ValueError:
                table = build_table(image.meta)
                note = "前回の設定はこの画像のチャンネルと合わないため、使っていません。"
        settings = Settings(z_projection=z_projection)
        window.setup_panel.apply_to(settings)
        window.show_session(open_session(image, table, settings))
        window.userdata.add_recent(path)
        window.show_recent()
        window.panels.setCurrentIndex(PANEL_SETUP)
        window.message_label.setText(note)

    window.runner.start("読み込み", task, done)


def open_project(window, path: str, czi_path: str | None = None) -> None:
    def task():
        yield "作業ファイルを開いています"
        try:
            return load_project(path, czi_path)
        except FileNotFoundError as error:
            return error

    def done(result) -> None:
        if isinstance(result, FileNotFoundError):
            moved, _ = QFileDialog.getOpenFileName(
                window, "元の .czi が見つかりません。場所を教えてください", "", "CZI (*.czi)")
            if moved:
                open_project(window, path, moved)
            return
        window.show_session(result)
        window.detected_with = asdict(result.settings.detection)
        if result.control:
            window.setup_panel.set_control_sources(result.control.sources)
        if os.path.abspath(path) == os.path.abspath(window.userdata.autosave_path):
            # 自動保存から戻した作業は、まだどこにも保存されていない
            result.dirty = True
        else:
            window.userdata.add_recent(path)
            window.show_recent()
        window.panels.setCurrentIndex(PANEL_REVIEW if result.judgements else PANEL_SETUP)

    window.runner.start("作業ファイルの読み込み", task, done)


def judge(window) -> None:
    session = window.session
    if session is None or window.runner.busy:
        return
    problems = session.table.problems()
    if problems:
        QMessageBox.warning(window, "チャンネル表を直してください", "\n".join(problems))
        window.panels.setCurrentIndex(PANEL_SETUP)
        return
    if session.history.can_undo and not confirm(
            window, "判定し直しますか？", "手で直した × は消えます。判定し直しますか？"):
        return
    window.setup_panel.apply_to(session.settings)
    sources = window.setup_panel.control_sources()
    detection = asdict(session.settings.detection)
    detect = session.labels is None or detection != window.detected_with
    # 対照の値は、対照のファイル・チャンネル表・設定が同じなら測り直さない
    measured = {**session.settings.to_dict(), "judge": {
        **asdict(session.settings.judge), "control_percentile": None}}
    key = repr((sources, session.table.to_list(), measured))
    cached = None
    if window.control_cache and window.control_cache[0] == key:
        cached = window.control_cache[1]

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
        window.detected_with = detection
        window.control_cache = (key, control) if control else None
        window.exported = window.stale = False
        window.userdata.remember_table(preset_of(session.table, "前回の設定"))
        window.panels.setCurrentIndex(PANEL_REVIEW)
        window.refresh()

    window.runner.start("判定", task, done)


def export(window) -> None:
    session = window.session
    if not window.judged or window.runner.busy:
        return
    folder = window.output_panel.folder.text().strip() or default_folder(session.image.path)
    if os.path.isfile(os.path.join(folder, RESULTS_NAME)) and not confirm(
            window, "上書きしますか？", f"このフォルダには前の結果があります。上書きしますか？\n{folder}"):
        return

    def task():
        yield "結果を書き出しています"
        return export_results(session, folder)

    def done(written: str) -> None:
        window.exported = True
        window.userdata.clear_autosave()
        window.output_panel.result.setText(f"出力しました: {written}")
        window.refresh()
        show_export_done(window, written)

    window.runner.start("出力", task, done)


def save_work(window) -> None:
    session = window.session
    if not window.judged or window.runner.busy:
        return
    stem = os.path.splitext(session.image.path)[0]
    path, _ = QFileDialog.getSaveFileName(window, "作業を保存", stem + EXTENSION,
                                          f"作業ファイル (*{EXTENSION})")
    if not path:
        return
    try:
        save_project(session, path)
    except OSError as error:
        show_error(window, "作業を保存できません", error, window.userdata.log_path)
        return
    session.dirty = False
    window.userdata.clear_autosave()
    window.message_label.setText(f"作業を保存しました: {os.path.basename(path)}")


def autosave(window) -> None:
    """保存していない × の修正があれば、落ちたときに戻せるよう控えを書いておく。"""
    session = window.session
    if window.judged and session.dirty and not window.runner.busy:
        os.makedirs(window.userdata.folder, exist_ok=True)
        save_project(session, window.userdata.autosave_path)


def batch(window) -> None:
    """いま開いている画像の設定で、選んだ画像をまとめて判定する。"""
    session = window.session
    if session is None or window.runner.busy:
        return
    problems = session.table.problems()
    if problems:
        QMessageBox.warning(window, "チャンネル表を直してください", "\n".join(problems))
        window.panels.setCurrentIndex(PANEL_SETUP)
        return
    dialog = BatchDialog(window, os.path.join(os.path.dirname(session.image.path), "一括処理"))
    if not dialog.exec():
        return
    items, folder = dialog.items(), dialog.folder.text().strip()
    window.setup_panel.apply_to(session.settings)
    sources = window.setup_panel.control_sources()

    def task():
        yield f"一括処理を始めます（{len(items)} 枚）"
        return run_batch(items, session, sources, folder, progress=window.runner.stage.emit)

    def done(rows) -> None:
        window.message_label.setText(f"一括処理が終わりました（{len(rows)} 枚）: {BATCH_NAME}")
        show_export_done(window, folder)

    window.runner.start("一括処理", task, done)


def batch_refresh(window) -> None:
    if window.runner.busy:
        return
    folder = QFileDialog.getExistingDirectory(window, "一括処理の出力フォルダを選ぶ")
    if not folder:
        return

    def task():
        yield "一括処理の集計をやり直しています"
        return refresh_batch(folder)

    def done(rows) -> None:
        window.message_label.setText(f"集計をやり直しました（{len(rows)} 枚）: {BATCH_NAME}")
        show_export_done(window, folder)

    window.runner.start("集計のやり直し", task, done)
