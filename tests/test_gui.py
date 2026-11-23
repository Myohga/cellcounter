"""画面。合成画像の作業状態を直接渡して、表示と操作のつながりを確かめる（Cellpose は使わない）。"""

import os

import numpy as np
import pytest

pytest.importorskip("napari")

from napari.qt import get_qapp  # noqa: E402
from napari.settings import get_settings  # noqa: E402
from qtpy.QtCore import QMimeData, Qt, QUrl  # noqa: E402
from qtpy.QtTest import QTest  # noqa: E402
from qtpy.QtWidgets import QWidget  # noqa: E402

import synth  # noqa: E402
from cellcounter.channels import build_table  # noqa: E402
from cellcounter.gui import main_window  # noqa: E402
from cellcounter.gui.channel_table import ChannelTableWidget  # noqa: E402
from cellcounter.gui.dialogs import HelpDialog, help_html  # noqa: E402
from cellcounter.gui.main_window import PANEL_OUTPUT, PANEL_REVIEW, MainWindow  # noqa: E402
from cellcounter.gui.shortcuts import REPLACED_NAPARI_ACTIONS, SHORTCUTS, button_text  # noqa: E402
from cellcounter.userdata import RECENT_LIMIT, UserData  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return get_qapp()


@pytest.fixture
def window(app, tmp_path):
    from cellcounter.markers import MarkerDictionary, use_dictionary

    window = MainWindow(UserData(str(tmp_path / "user")))
    yield window
    if window.session:
        window.session.dirty = False
    window.close()
    # 画面は利用者の辞書をモジュール全体の辞書にするので、あとのテストのために初期の辞書へ戻す
    use_dictionary(MarkerDictionary())


@pytest.fixture
def judged(window):
    session = synth.two_marker_session(6, 6, {1, 2, 3}, {4, 5})
    window.show_session(session)
    return window


def _summary(window, row: int, column: int) -> str:
    return window.review_panel.summary.item(row, column).text()


def test_shortcuts_do_not_collide_with_napari():
    ours = [keys for entry in SHORTCUTS for keys in entry.keys]
    assert len(ours) == len(set(ours)), "同じキーを 2 つの操作に割り当てている"
    napari = {str(keys): action for action, bindings in get_settings().shortcuts.shortcuts.items()
              for keys in bindings if action not in REPLACED_NAPARI_ACTIONS}
    assert not set(ours) & set(napari)


def test_napari_keys_that_move_dimensions_are_switched_off(window):
    from cellcounter.gui.shortcuts import UNUSED_NAPARI_ACTIONS

    from napari.utils.action_manager import action_manager

    assert all(not action_manager._shortcuts.get(action) for action in UNUSED_NAPARI_ACTIONS)
    assert list(window.canvas.model.mouse_wheel_callbacks) == []
    before = window.canvas.model.dims.point
    QTest.keyClick(window.canvas.view.canvas.native, Qt.Key.Key_Right)
    assert window.canvas.model.dims.point == before


def test_buttons_and_help_come_from_the_shortcut_table(window):
    assert window.setup_panel.judge_button.text() == button_text("judge") == "判定（Ctrl+J）"
    assert {entry.name for entry in SHORTCUTS} == set(window.actions_by_name)
    redo = [sequence.toString() for sequence in window.actions_by_name["redo"].shortcuts()]
    assert redo == ["Ctrl+Shift+Z", "Ctrl+Y"]
    for entry in SHORTCUTS:
        assert entry.label in help_html() and all(keys in help_html() for keys in entry.keys)
    assert "動作環境" in help_html() and "GPU" in help_html()


def test_help_fits_the_screen_and_can_scroll_and_zoom(app):
    # 親を MainWindow にして表示すると、napari の描画（OpenGL）があとのテストで壊れるので、ただの QWidget にする
    parent = QWidget()
    dialog = HelpDialog(parent)
    screen = parent.screen().availableGeometry()
    assert dialog.width() <= screen.width() and dialog.height() <= screen.height() * 0.8 + 1
    assert "動作環境" in dialog.text.toPlainText()
    dialog.show()
    dialog.activateWindow()
    assert QTest.qWaitForWindowActive(dialog)
    size = dialog.text.font().pointSizeF()
    dialog.zoom_out.click()
    assert dialog.text.font().pointSizeF() < size
    QTest.keyClick(dialog, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
    assert dialog.text.font().pointSizeF() == size
    for _ in range(20):
        dialog.zoom_in.click()
    app.processEvents()
    assert dialog.text.verticalScrollBar().maximum() > 0   # 画面に収まらない分はスクロールで見る
    dialog.close()


def test_start_state_disables_later_steps(window):
    assert window.stage_label.text() == "①読み込み → ②設定 → ③未判定 → ④未出力"
    assert [window.panels.isTabEnabled(index) for index in range(4)] == [True, False, False, False]
    assert not window.actions_by_name["judge"].isEnabled()
    assert not window.actions_by_name["export"].isEnabled()
    assert "cellcounter" in window.windowTitle()


def test_judged_session_shows_tabs_marks_and_counts(judged):
    window = judged
    tabs = [window.canvas.tabs.tabText(index) for index in range(window.canvas.tabs.count())]
    assert tabs == ["DAPI のみ", "DAPI＋NUC", "DAPI＋CYT"]
    assert window.stage_label.text() == "①読み込み ✓ → ②設定 ✓ → ③修正中 → ④未出力"
    assert window.panels.isTabEnabled(PANEL_REVIEW) and window.panels.isTabEnabled(PANEL_OUTPUT)
    assert "暫定" in window.canvas.banner.text()
    assert window.canvas.mark_count() == 36

    window.canvas.tabs.setCurrentIndex(1)
    assert window.canvas.current_marker() == "NUC"
    assert window.canvas.mark_count() == 3
    visible = {layer.name for layer in window.canvas.model.layers if layer.visible}
    assert {"H3342-T1", "AF488-T2"} <= visible and "AF555-T1" not in visible


def test_click_undo_and_redo_update_the_screen(judged):
    window = judged
    window.canvas.tabs.setCurrentIndex(1)
    nucleus = window.session.nuclei[10]
    window._on_click(nucleus.y, nucleus.x)
    assert window.canvas.mark_count() == 4 and _summary(window, 1, 2) == "4"
    assert _summary(window, 1, 4) == "1", "人が足した数"
    assert window.actions_by_name["undo"].isEnabled()

    window.undo()
    assert window.canvas.mark_count() == 3 and _summary(window, 1, 2) == "3"
    assert window.actions_by_name["redo"].isEnabled()
    window.redo()
    assert _summary(window, 1, 2) == "4"

    window.canvas.step_tab(-1)
    window._on_click(15.0, 100.0)
    assert _summary(window, 0, 1) == "37", "何も無い場所のクリックで核が 1 つ増える"


def test_background_channels_can_be_chosen_per_tab(judged):
    """③ のチェックで背景に出す画像を変えられ、組み合わせのタブごとに覚えている。"""
    window = judged
    layers = {layer.name: layer for layer in window.canvas.model.layers}
    window.canvas.tabs.setCurrentIndex(1)
    assert not layers["AF555-T1"].visible
    assert [check.isChecked() for check in window.review_panel.checks.values()] == [True, True, False]
    assert window.review_panel.checks[1].text() == "NUC"

    window.review_panel.checks[2].click()
    window.review_panel.checks[0].click()
    assert layers["AF555-T1"].visible and not layers["H3342-T1"].visible
    assert window.session.shown_channels("NUC") == [1, 2]

    window.canvas.tabs.setCurrentIndex(2)
    assert layers["H3342-T1"].visible and not layers["AF488-T2"].visible
    window.canvas.tabs.setCurrentIndex(1)
    assert layers["AF555-T1"].visible and not layers["H3342-T1"].visible
    assert window.review_panel.checks[2].isChecked()


def test_channels_use_their_original_colors(judged):
    window = judged
    colors = {row.name: row.color for row in window.session.table.rows}
    assert colors == {"H3342-T1": "#0076FF", "AF488-T2": "#00FF33", "AF555-T1": "#FF7E00"}
    top = window.canvas._images[2].colormap.colors[-1]
    assert [round(float(value), 2) for value in top[:3]] == [1.0, 0.49, 0.0]


def test_marks_are_thin_lines_and_can_be_hidden(judged):
    window = judged
    marks = window.canvas._marks
    assert type(marks).__name__ == "Vectors" and len(marks.data) == 2 * window.canvas.mark_count()
    window.review_panel.marks_check.click()
    assert not marks.visible
    window.review_panel.marks_check.click()
    assert marks.visible


def test_contrast_is_kept_across_tabs(judged):
    window = judged
    window._on_contrast(1, 10.0, 500.0)
    window.canvas.tabs.setCurrentIndex(2)
    window.canvas.tabs.setCurrentIndex(1)
    assert tuple(window.canvas._images[1].contrast_limits) == (10.0, 500.0)
    assert window.session.contrast[1] == (10.0, 500.0)


def test_changing_the_table_after_judging_is_flagged(judged):
    window = judged
    editors = window.setup_panel.table_widget.editors[1]
    editors.judge.setChecked(False)
    window.setup_panel.table_widget._apply(editors)
    assert "[判定] をやり直してください" in window.stage_label.text()


def test_closing_with_unexported_edits_asks_first(judged, monkeypatch):
    window = judged
    nucleus = window.session.nuclei[10]
    window._on_click(nucleus.y, nucleus.x)
    asked = []
    monkeypatch.setattr(main_window, "confirm", lambda *args: asked.append(args[1]) or False)
    assert not window.close()
    assert asked == ["まだ出力していない修正があります"]


def test_dropped_czi_is_opened(window, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(window, "open_path", opened.append)
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(tmp_path / "画像.czi"))])

    class Drop:
        accepted = False

        def mimeData(self):
            return data

        def acceptProposedAction(self):
            self.accepted = True

    event = Drop()
    window.dragEnterEvent(event)
    assert event.accepted
    window.dropEvent(event)
    assert opened and opened[0].endswith("画像.czi")


def test_channel_table_guesses_location_and_reports_unknown_names(app):
    table = build_table(synth.fake_image([synth.dapi_plane(synth.grid_labels(2, 2), 1)] * 3).meta)
    widget = ChannelTableWidget()
    widget.set_table(table, ["MAP2"])
    name = widget.editors[1].name
    name.setCurrentText("Islet-1")
    name.lineEdit().editingFinished.emit()
    assert (table.rows[1].marker, table.rows[1].location, table.rows[1].judge) == (
        "Islet-1", "nuclear", True)
    assert table.problems() == []

    name.setCurrentText("MyNewProtein")
    name.lineEdit().editingFinished.emit()
    assert table.rows[1].location == ""
    assert any("染まる場所を選んでください" in problem for problem in table.problems())


def test_choosing_another_dapi_keeps_the_marker_names(app):
    """核を数えるチャンネルを選び直しても、入れてあった名前や設定は消えない。"""
    table = build_table(synth.fake_image([synth.dapi_plane(synth.grid_labels(2, 2), 1)] * 3).meta)
    table.set_marker(1, "MAP2")
    table.set_marker(2, "Islet-1")
    widget = ChannelTableWidget()
    widget.set_table(table, [])
    assert "核を検出して数えます" in widget.item(0, 2).text()

    widget.dapi_buttons[2].setChecked(True)
    assert table.dapi.index == 2 and table.rows[0].role == "marker"
    assert [row.marker for row in table.judged()] == ["MAP2"]
    assert 2 not in widget.editors, "核を数える行には、マーカーの入力欄を出さない"

    widget.dapi_buttons[0].setChecked(True)
    assert [(row.marker, row.location, row.judge) for row in table.judged()] == [
        ("MAP2", "fibrillar", True), ("Islet-1", "nuclear", True)]
    assert widget.editors[2].name.currentText() == "Islet-1"


def test_userdata_remembers_files_names_and_presets(tmp_path):
    folder = str(tmp_path / "user")
    data = UserData(folder)
    for number in range(RECENT_LIMIT + 3):
        data.add_recent(str(tmp_path / f"{number}.czi"))
    data.add_recent(str(tmp_path / "5.czi"))
    assert len(data.recent_files) == RECENT_LIMIT and data.recent_files[0].endswith("5.czi")

    table = build_table(synth.fake_image([synth.dapi_plane(synth.grid_labels(2, 2), 1)] * 3).meta)
    table.set_marker(1, "MAP2")
    from cellcounter.channels import preset_of
    data.remember_table(preset_of(table, "前回の設定"))
    data.save_preset(preset_of(table, "運動ニューロン"))
    with pytest.raises(ValueError, match="使えない文字"):
        data.save_preset(preset_of(table, "a/b"))

    again = UserData(folder)
    assert again.recent_files == data.recent_files and again.marker_names == ["MAP2"]
    assert again.preset_names() == ["運動ニューロン"]
    assert again.load_preset("運動ニューロン")["channels"][1]["marker"] == "MAP2"
    assert again.last_table["channels"][1]["marker"] == "MAP2"


def test_broken_userdata_is_reported_not_hidden(tmp_path):
    folder = tmp_path / "user"
    folder.mkdir()
    (folder / "user.json").write_text("{broken", encoding="utf-8")
    data = UserData(str(folder))
    assert "壊れていた" in data.notice and (folder / "user.json.broken").exists()


def test_blind_mode_in_the_window_hides_counts_and_shows_agreement(judged):
    window = judged
    window.canvas.tabs.setCurrentIndex(1)
    window.review_panel.blind_check.click()
    assert window.session.blind_active and "目視判定モード" in window.canvas.banner.text()
    assert window.canvas.mark_count() == 0, "自動判定の × は隠す"
    assert _summary(window, 1, 2) == "（隠しています）"

    for nucleus_id in (1, 2, 20):
        nucleus = window.session.nuclei[nucleus_id]
        window._on_click(nucleus.y, nucleus.x)
    assert window.canvas.mark_count() == 3

    window.review_panel.blind_check.click()
    assert not window.session.blind_active and window.canvas.mark_count() == 3
    text = window.review_panel.agreement_label.text()
    assert "目視との一致 NUC" in text and "目視も自動も陽性 2、自動だけ 1、目視だけ 1" in text


def test_autosave_keeps_unsaved_edits_and_is_cleared_when_discarded(judged, monkeypatch):
    window = judged
    path = window.userdata.autosave_path
    main_window.flows.autosave(window)
    assert not os.path.exists(path), "修正が無ければ書かない"

    nucleus = window.session.nuclei[10]
    window._on_click(nucleus.y, nucleus.x)
    main_window.flows.autosave(window)
    assert os.path.isfile(path)

    monkeypatch.setattr(main_window, "confirm", lambda *args: True)
    assert window.may_discard() and not os.path.exists(path)


def test_canvas_is_placed_in_micrometers_with_a_scale_bar(judged):
    window = judged
    canvas = window.canvas
    assert canvas.model.canvas.overlays.scale_bar.visible
    assert tuple(canvas._images[0].scale) == (synth.UM_PER_PX, synth.UM_PER_PX)

    class Move:
        position = (30.0 * synth.UM_PER_PX, 60.0 * synth.UM_PER_PX)

    assert canvas._pixel(Move()) == pytest.approx((30.0, 60.0))
    assert str(canvas._images[0].interpolation2d) == "cubic"


def test_hovering_works_with_many_nuclei_and_one_cut_by_the_edge(window):
    """核が 256 個以上あり、端で切れた核の × が画像からはみ出しても、輪郭を出せる。

    × がはみ出すと napari が非表示の輪郭レイヤーを 8 bit の仮の中身に差し替えるため、
    そのまま 256 以上の核を選ぶと OverflowError になっていた（実画像で核 2083 個のとき）。
    """
    import numpy as np

    from cellcounter.gui.canvas import MARK_HALF_LENGTH

    labels = synth.grid_labels(17, 17)
    edge_id = int(labels.max()) + 1
    ys, xs = np.mgrid[0:synth.RADIUS + 1, 300 - synth.RADIUS:300 + synth.RADIUS + 1]
    inside = ys ** 2 + (xs - 300) ** 2 <= synth.RADIUS ** 2
    labels[ys[inside], xs[inside]] = edge_id
    planes = [synth.dapi_plane(labels, 1), synth.marker_plane(labels, {1, 2}, "nucleus", 2)]
    session = synth.build_session(labels, planes, [(1, "NUC", "nuclear")])
    assert len(session.nuclei) > 256
    window.show_session(session)
    canvas = window.canvas
    arm = max(3.0, session.diameter_px * MARK_HALF_LENGTH)
    assert session.nuclei[edge_id].y - arm < -0.5, "× が画像の上にはみ出している"

    class Move:
        def __init__(self, nucleus_id):
            nucleus = session.nuclei[nucleus_id]
            self.position = (nucleus.y * canvas._um, nucleus.x * canvas._um)

    for nucleus_id in (280, edge_id, 5):
        canvas._on_move(None, Move(nucleus_id))
        assert canvas._outline.visible and canvas._outline.selected_label == nucleus_id

    class Outside:
        position = (15.0 * canvas._um, 15.0 * canvas._um)

    canvas._on_move(None, Outside())
    assert not canvas._outline.visible
    canvas._on_move(None, Move(289))
    assert canvas._outline.visible and canvas._outline.selected_label == 289


def test_hovering_works_after_napari_moved_its_slider_position(window):
    """← → キーや Ctrl+ホイールで napari の「スライダーの位置」が動いたあとでも、輪郭を出せる。"""
    session = synth.two_marker_session(17, 17, {1, 2, 3}, {4, 5})
    window.show_session(session)
    canvas = window.canvas
    canvas.model.dims._increment_dims_right()  # napari が → キーで呼ぶ処理

    class Move:
        nucleus = session.nuclei[280]
        position = (nucleus.y * canvas._um, nucleus.x * canvas._um)

    canvas._on_move(None, Move())
    assert canvas._outline.visible and canvas._outline.selected_label == 280


def test_file_panel_offers_a_single_z_plane(app):
    from cellcounter.czi import SceneInfo
    from cellcounter.gui.file_panel import FilePanel

    panel = FilePanel()
    panel.set_scenes("stack.czi", [SceneInfo(0, "Scene 0", {"C": 4, "Z": 12, "Y": 10, "X": 10})])
    assert panel.z_projection() == "max" and not panel.z_plane.isEnabled()
    panel.z.setCurrentIndex(panel.z.findData("plane"))
    panel.z_plane.setValue(20)
    assert panel.z_plane.isEnabled() and panel.z_projection() == "plane:12", "上限は Z の枚数"
    panel.show_loaded("stack.czi", 0, "plane:5", "")
    assert panel.z_projection() == "plane:5"


def test_batch_dialog_lets_the_user_rename_conditions(app, monkeypatch, tmp_path):
    from cellcounter.batch import BatchItem
    from cellcounter.gui import batch_dialog

    found = [BatchItem(str(tmp_path / "ctrl_1.czi"), 0, "ctrl"),
             BatchItem(str(tmp_path / "ctrl_2.czi"), 0, "ctrl")]
    monkeypatch.setattr(batch_dialog, "list_items", lambda paths: found)
    dialog = batch_dialog.BatchDialog(None, str(tmp_path / "out"))
    dialog.add([str(tmp_path)])
    dialog.table.item(1, 0).setText("薬剤")
    assert [(item.condition, os.path.basename(item.path)) for item in dialog.items()] == [
        ("ctrl", "ctrl_1.czi"), ("薬剤", "ctrl_2.czi")]
    dialog.add([str(tmp_path)])
    assert dialog.table.rowCount() == 2, "同じ画像を二重に足さない"


# ---- 平均蛍光強度・辞書登録・結果ファイルの名前 ------------------------------------------


@pytest.fixture
def tau(window):
    """NUC は陽性率、AT8（辞書でタウ → 平均蛍光強度）を測る画像を開いた画面。"""
    from cellcounter.pipeline import run_judgement

    labels = synth.grid_labels(6, 6)
    planes = [synth.dapi_plane(labels, 1), synth.marker_plane(labels, {1, 2}, "nucleus", 2),
              synth.marker_plane(labels, set(range(1, 19)), "cytoplasm", 3)]
    session = synth.build_session(labels, planes, [(1, "NUC", "nuclear")])
    session.table.set_marker(2, "AT8")
    run_judgement(session, None)
    window.show_session(session)
    return window


def _tab(window, name: str) -> None:
    tabs = [window.canvas.tabs.tabText(index) for index in range(window.canvas.tabs.count())]
    window.canvas.tabs.setCurrentIndex(tabs.index(name))


def test_dictionary_is_under_the_operations_menu(window):
    menus = {action.text(): action.menu() for action in window.menuBar().actions()}
    assert list(menus)[-2:] == ["操作", "ヘルプ"]
    assert [action.text() for action in menus["操作"].actions()] == ["辞書登録…"]


def test_channel_table_takes_method_and_comment_from_the_dictionary(app):
    from cellcounter.gui.channel_table import fill_marker_names
    from qtpy.QtWidgets import QComboBox

    table = build_table(synth.fake_image([synth.dapi_plane(synth.grid_labels(2, 2), 1)] * 3).meta)
    widget = ChannelTableWidget()
    widget.set_table(table, ["MAP2"])
    editors = widget.editors[1]
    editors.name.setCurrentText("AT8")
    editors.name.lineEdit().editingFinished.emit()
    assert (table.rows[1].method, table.rows[1].judge) == ("imv", True)
    assert editors.method.currentText() == "平均蛍光強度" and not editors.location.isEnabled()
    assert "Ser202/Thr205" in editors.name.toolTip()

    editors.method.setCurrentIndex(editors.method.findData("rate"))
    widget._apply(editors)
    assert table.rows[1].method == "rate" and editors.location.isEnabled()

    combo = QComboBox()
    fill_marker_names(combo, ["MAP2"])
    assert combo.itemText(0) == "MAP2" and combo.findText("AT8") > 1, "使った名前を先に、辞書をあとに"
    tooltip = combo.itemData(combo.findText("EP2456Y"), Qt.ItemDataRole.ToolTipRole)
    assert "総タウ" in tooltip and "平均蛍光強度" in tooltip

    widget.editors[2].name.setCurrentText("DRAQ5")
    widget.editors[2].name.lineEdit().editingFinished.emit()
    assert table.dapi.index == 2 and 2 not in widget.editors, "核の染色は「核を数える」になる"


def test_intensity_tab_measures_regions_and_undo_works(tau):
    window = tau
    session = window.session
    tabs = [window.canvas.tabs.tabText(index) for index in range(window.canvas.tabs.count())]
    assert tabs == ["DAPI のみ", "DAPI＋NUC", "平均蛍光強度"], "AT8 は組み合わせのタブを作らない"
    _tab(window, "平均蛍光強度")
    panel = window.review_panel
    assert panel.region_box.isVisibleTo(panel) and not panel.summary.isVisibleTo(panel)
    assert window.canvas.mark_count() == 0
    assert panel.intensity.item(0, 0).text() == "画像全体"
    assert [panel.intensity.horizontalHeaderItem(c).text() for c in range(4)] == [
        "範囲", "面積 (µm²)", "数える核", "AT8"]

    panel.region_buttons["rectangle"].click()
    layer = window.canvas._regions
    assert str(layer.mode) == "add_rectangle" and layer.visible
    layer.add(np.array([[10, 10], [10, 80], [70, 80], [70, 10]]), shape_type="rectangle")
    QTest.qWait(20)
    assert len(session.regions) == 1 and panel.intensity.item(0, 0).text() == "範囲 1"
    layer.add(np.array([[3, 3], [3, 3.2], [3.2, 3.2], [3.2, 3]]), shape_type="rectangle")
    QTest.qWait(20)
    assert len(session.regions) == 1 and layer.nshapes == 1, "小さすぎる範囲は捨てる"

    window.undo()
    assert session.regions == [] and layer.nshapes == 0
    window.redo()
    assert layer.nshapes == 1
    panel.clear_regions_button.click()
    assert session.regions == [] and panel.intensity.item(0, 0).text() == "画像全体"

    layer.mode = "add_ellipse"
    assert panel.region_buttons["ellipse"].isChecked(), "napari のキーで変えてもボタンが合う"
    nuclei = len(session.nuclei)
    window._on_click(5.0, 5.0)
    assert len(session.nuclei) == nuclei, "このタブのクリックで核を作らない"

    _tab(window, "DAPI のみ")
    assert not layer.visible and str(layer.mode) == "pan_zoom"
    assert window.canvas.model.layers.selection.active is None
    assert panel.summary.isVisibleTo(panel) and not panel.region_box.isVisibleTo(panel)


def test_changing_the_method_after_judging_is_flagged(tau):
    window = tau
    editors = window.setup_panel.table_widget.editors[2]
    editors.method.setCurrentIndex(editors.method.findData("rate"))
    window.setup_panel.table_widget._apply(editors)
    assert "[判定] をやり直してください" in window.stage_label.text()


def test_result_file_name_is_previewed_and_used(tau, monkeypatch, tmp_path):
    from cellcounter.export import results_name

    window = tau
    panel = window.output_panel
    assert panel.export_button.isEnabled() and results_name() in panel.name_preview.text()
    panel.name.setText("a:b")
    assert not panel.export_button.isEnabled() and "使えない文字" in panel.name_preview.text()

    warned = []
    monkeypatch.setattr(main_window.flows.QMessageBox, "warning",
                        lambda *args: warned.append(args[1]))
    window.export()
    assert warned == ["結果ファイルの名前を直してください"]

    panel.name.setText("tau_day40")
    panel.folder.setText(str(tmp_path / "out"))

    def run_now(title, task, done):
        steps = task()
        try:
            while True:
                next(steps)
        except StopIteration as finished:
            done(finished.value)

    monkeypatch.setattr(window.runner, "start", run_now)
    monkeypatch.setattr(main_window.flows, "show_export_done", lambda *args: None)
    window.export()
    assert results_name("tau_day40") in os.listdir(tmp_path / "out")
    assert panel.result.text().endswith(results_name("tau_day40"))


def test_dictionary_dialog_registers_edits_and_deletes(window, monkeypatch):
    from cellcounter.gui import marker_dialog
    from cellcounter.markers import lookup

    table = build_table(synth.fake_image([synth.dapi_plane(synth.grid_labels(2, 2), 1)] * 3).meta)
    window.setup_panel.set_table(table)
    dialog = marker_dialog.MarkerDictionaryDialog(window, window.userdata)

    def fill(name, imv, comment):
        def run(self):
            self.name.setText(name)
            self.imv.setChecked(imv)
            self.comment.setPlainText(comment)
            self.accept()
            return self.result()
        return run

    monkeypatch.setattr(marker_dialog.MarkerEntryDialog, "exec", fill("MyTau", True, "自作の抗体"))
    dialog.add()
    assert lookup("my-tau").imv and dialog.edited
    assert os.path.isfile(os.path.join(window.userdata.folder, "markers.json"))
    assert dialog.selected().name == "MyTau"

    monkeypatch.setattr(marker_dialog.MarkerEntryDialog, "exec", fill("MyTau", False, "直した"))
    dialog.edit_selected()
    assert not lookup("MyTau").imv and lookup("MyTau").comment == "直した"

    monkeypatch.setattr(marker_dialog.MarkerEntryDialog, "exec", fill("at-8", False, ""))
    entry = marker_dialog.MarkerEntryDialog(dialog, window.userdata.markers)
    assert not entry.exec() and "同じ名前" in entry.error.text(), "AT8 と重なる名前は登録しない"

    dialog.search.setText("mytau")
    assert dialog.table.rowCount() == 1
    dialog.table.selectRow(0)
    monkeypatch.setattr(marker_dialog, "confirm", lambda *args: True)
    dialog.remove_selected()
    assert lookup("MyTau") is None and dialog.table.rowCount() == 0

    window.setup_panel.reload_names()
    combo = window.setup_panel.table_widget.editors[1].name
    assert combo.findText("MyTau") < 0 and combo.findText("AT8") >= 0

    dialog.reset()
    assert len(window.userdata.markers.entries) > 100
    again = UserData(window.userdata.folder)
    assert again.markers.exact("AT8").imv


@pytest.mark.parametrize("scale", [1.0, 1.5])
def test_marker_name_box_stays_inside_its_column(window, scale):
    """文字が大きい PC（Windows の日本語フォントや表示の拡大）でも、名前の欄が「染まる場所」に重ならない。

    以前は名前の欄に固定の最小幅があり、列がそれより狭くなると隣の列にはみ出していた。
    """
    from cellcounter.gui.channel_table import NAME_COLUMN

    font = window.font()
    font.setPointSizeF(font.pointSizeF() * scale)
    window.setup_panel.setFont(font)
    table = build_table(synth.fake_image([synth.dapi_plane(synth.grid_labels(2, 2), 1)] * 3).meta)
    table.set_marker(1, "AT8")
    table.set_marker(2, "MAP2")
    session = synth.build_session(synth.grid_labels(2, 2),
                                  [synth.dapi_plane(synth.grid_labels(2, 2), 1)] * 3, [])
    session.table = table
    window.show()
    window.show_session(session)
    window.panels.setCurrentIndex(1)
    QTest.qWait(100)

    widget = window.setup_panel.table_widget
    header = widget.horizontalHeader()
    assert [editors.row.method for editors in widget.editors.values()] == ["imv", "rate"]
    for editors in widget.editors.values():
        assert editors.name.geometry().right() < header.sectionViewportPosition(NAME_COLUMN + 1)
        assert editors.name.width() >= editors.name.minimumSizeHint().width()
    assert not window.panels.widget(1).horizontalScrollBar().isVisible(), "右のパネルを広げて収める"
