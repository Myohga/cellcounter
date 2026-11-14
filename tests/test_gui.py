"""画面。合成画像の作業状態を直接渡して、表示と操作のつながりを確かめる（Cellpose は使わない）。"""

import pytest

pytest.importorskip("napari")

from napari.qt import get_qapp  # noqa: E402
from napari.settings import get_settings  # noqa: E402
from qtpy.QtCore import QMimeData, QUrl  # noqa: E402

import synth  # noqa: E402
from cellcounter.channels import build_table  # noqa: E402
from cellcounter.gui import main_window  # noqa: E402
from cellcounter.gui.channel_table import ChannelTableWidget  # noqa: E402
from cellcounter.gui.dialogs import help_html  # noqa: E402
from cellcounter.gui.main_window import PANEL_OUTPUT, PANEL_REVIEW, MainWindow  # noqa: E402
from cellcounter.gui.shortcuts import REPLACED_NAPARI_ACTIONS, SHORTCUTS, button_text  # noqa: E402
from cellcounter.userdata import RECENT_LIMIT, UserData  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return get_qapp()


@pytest.fixture
def window(app, tmp_path):
    window = MainWindow(UserData(str(tmp_path / "user")))
    yield window
    if window.session:
        window.session.dirty = False
    window.close()


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


def test_buttons_and_help_come_from_the_shortcut_table(window):
    assert window.setup_panel.judge_button.text() == button_text("judge") == "判定（Ctrl+J）"
    assert {entry.name for entry in SHORTCUTS} == set(window.actions_by_name)
    redo = [sequence.toString() for sequence in window.actions_by_name["redo"].shortcuts()]
    assert redo == ["Ctrl+Shift+Z", "Ctrl+Y"]
    for entry in SHORTCUTS:
        assert entry.label in help_html() and all(keys in help_html() for keys in entry.keys)
    assert "動作環境" in help_html() and "GPU" in help_html()


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
