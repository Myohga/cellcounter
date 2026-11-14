"""追加機能（Z の 1 枚選択・面積・閾値曲線・目視判定との比較・一括処理・動作環境）。"""

import os

import numpy as np
import pytest
from openpyxl import load_workbook

import synth
from cellcounter.batch import (BatchItem, condition_of, condition_stats, refresh_batch, run_batch)
from cellcounter.czi import project_z
from cellcounter.environment import environment_report
from cellcounter.excel import TABLE_TOP
from cellcounter.export import export_results
from cellcounter.project import load_project, save_project
from cellcounter.settings import Settings
from cellcounter.tally import agreement, summarize, threshold_curves


def _at(session, nucleus_id: int) -> tuple[float, float]:
    nucleus = session.nuclei[nucleus_id]
    return nucleus.y, nucleus.x


def test_single_z_plane_can_be_chosen():
    stack = np.array([[[1, 9]], [[5, 2]], [[3, 3]]])
    assert project_z(stack, "plane:2").tolist() == [[5, 2]]
    with pytest.raises(ValueError, match="4 枚目はありません"):
        project_z(stack, "plane:4")
    assert Settings(z_projection="plane:3").z_projection == "plane:3"
    with pytest.raises(ValueError, match="Z 投影"):
        Settings(z_projection="plane:0")


def test_fibrillar_marker_reports_positive_area_per_nucleus():
    labels = synth.grid_labels(8, 8)
    planes = [synth.dapi_plane(labels, 1), synth.marker_plane(labels, set(), "nucleus", 2),
              synth.marker_plane(labels, set(range(1, 33)), "cytoplasm", 3)]
    session = synth.build_session(labels, planes, [(1, "NUC", "nuclear"), (2, "FIB", "fibrillar")])
    _, nuclear, fibrillar = summarize(session)
    assert nuclear.area_per_nucleus_um2 is None

    # 陽性の 32 個の周り（幅 10 px のリング）だけが閾値を超えるので、その面積とほぼ同じになる
    ring_px = np.pi * ((synth.RADIUS + synth.CYTOPLASM_PX) ** 2 - synth.RADIUS ** 2)
    expected = 32 * ring_px * synth.UM_PER_PX ** 2 / 64
    assert fibrillar.area_per_nucleus_um2 == pytest.approx(expected, rel=0.15)


def test_threshold_curve_matches_the_judgement():
    control = synth.negative_control(20, 20, seed=300)
    session = synth.two_marker_session(20, 20, set(range(1, 201)), set(), control)
    nuclear = threshold_curves(session)[0]
    assert nuclear.marker == "NUC" and len(nuclear.thresholds) == 60
    assert nuclear.sample == sorted(nuclear.sample, reverse=True), "閾値を上げれば陽性率は下がる"
    assert nuclear.sample[0] > 99 and nuclear.sample[-1] == 0.0

    values = np.array(list(session.judgements["NUC"].values.values()))
    at_chosen = float((values > nuclear.chosen).mean() * 100)
    assert at_chosen == pytest.approx(summarize(session)[1].auto_rate, abs=0.01)
    control_values = np.array(session.control.values["NUC"])
    assert (control_values > nuclear.chosen).mean() * 100 == pytest.approx(1.0, abs=0.3)

    without_control = synth.two_marker_session(5, 5, {1}, set())
    assert threshold_curves(without_control)[0].control is None


@pytest.fixture
def blind():
    """核 100 個。NUC は 1〜40 が陽性。目視判定モードに入った状態。"""
    session = synth.two_marker_session(10, 10, set(range(1, 41)), set())
    session.set_blind(True)
    return session


def test_blind_mode_hides_the_automatic_judgement(blind):
    assert all(blind.category("NUC", i) is None for i in blind.nuclei)
    assert blind.category(None, 1) == "auto", "「DAPI のみ」はいつもどおり"

    assert "目視で NUC 陽性" in blind.click("NUC", *_at(blind, 50))
    assert blind.category("NUC", 50) == "added" and blind.category("NUC", 1) is None
    assert blind.marks.positive["NUC"][50] is False, "確定判定には触らない"
    assert "数える核だけ" in blind.click("NUC", 15.0, 100.0), "何も無い場所では核を作らない"

    assert blind.undo() and blind.category("NUC", 50) is None
    assert blind.redo() and blind.category("NUC", 50) == "added"

    blind.set_blind(False)
    assert blind.category("NUC", 1) == "auto" and blind.category("NUC", 50) is None


def test_agreement_with_the_human_judgement(blind):
    assert agreement(blind) == [], "まだ何も付けていない"
    # 目視では 1〜30 と 41〜45 を陽性にした（自動は 1〜40）
    for nucleus_id in [*range(1, 31), *range(41, 46)]:
        blind.click("NUC", *_at(blind, nucleus_id))
    result = agreement(blind)[0]
    assert (result.both, result.auto_only, result.human_only, result.neither) == (30, 10, 5, 55)
    assert result.sensitivity == pytest.approx(30 / 35, abs=0.001)
    assert result.specificity == pytest.approx(55 / 65, abs=0.001)
    observed, expected = 0.85, (35 * 40 + 65 * 60) / 100 ** 2
    assert result.kappa == pytest.approx((observed - expected) / (1 - expected), abs=0.001)


def test_blind_judgement_is_saved_and_exported(blind, tmp_path):
    for nucleus_id in range(1, 31):
        blind.click("NUC", *_at(blind, nucleus_id))
    path = str(tmp_path / "blind.cellcounter")
    save_project(blind, path)
    resumed = load_project(path, loader=lambda czi, scene, z: synth.fake_image(
        list(blind.image.planes)))
    assert resumed.blind_active and agreement(resumed) == agreement(blind)

    folder = export_results(blind, str(tmp_path / "out"))
    book = load_workbook(os.path.join(folder, "results.xlsx"))
    assert book.sheetnames[-2:] == ["Thresholds", "Agreement"]
    row = [cell.value for cell in book["Agreement"][TABLE_TOP + 1]]
    assert row[:6] == ["NUC", 100, 30, 10, 0, 60]
    assert len(book["Thresholds"]._charts) == 2, "マーカーごとに 1 つ"


def test_condition_name_drops_the_trailing_number():
    assert condition_of(r"D:\data\ctrl_1.czi") == "ctrl"
    assert condition_of("drug 10uM-02.czi") == "drug 10uM"
    assert condition_of("123.czi") == "123"


def _batch_inputs():
    """条件 A が 2 枚（NUC 陽性 25%・50%）、条件 B が 1 枚（75%）。"""
    images, items = {}, []
    for number, (condition, positives) in enumerate((("A", 9), ("A", 18), ("B", 27))):
        labels = synth.grid_labels(6, 6, seed=number)
        path = os.path.abspath(f"{condition}_{number}.czi")
        images[path] = synth.fake_image(
            [synth.dapi_plane(labels, 10 + number),
             synth.marker_plane(labels, set(range(1, positives + 1)), "nucleus", 20 + number),
             synth.marker_plane(labels, set(), "cytoplasm", 30 + number)], path=path)
        items.append(BatchItem(path, 0, condition))
    return images, items


def test_batch_writes_one_summary_and_can_be_refreshed(tmp_path):
    images, items = _batch_inputs()
    control_path = os.path.abspath("control.czi")
    images[control_path] = synth.negative_control(20, 20, seed=300)
    template = synth.two_marker_session(6, 6, set(), set())
    loader = lambda path, scene, z: images[path]  # noqa: E731
    out = str(tmp_path / "一括")
    messages = []
    rows = run_batch(items, template, [(control_path, 0)], out, synth.by_threshold, loader,
                     messages.append)

    assert [row.rates["NUC"] for row in rows] == [25.0, 50.0, 75.0]
    assert not any(row.provisional for row in rows)
    assert messages[0].startswith("1 / 3") and len(messages) == 3
    for row in rows:
        assert {"results.xlsx"} <= set(os.listdir(row.folder))

    header, table = condition_stats(rows)
    assert header[:4] == ["条件", "画像の枚数", "NUC 平均 (%)", "NUC SD (%)"]
    assert table[0][:4] == ["A", 2, 37.5, pytest.approx(17.68, abs=0.01)]
    assert table[1][:4] == ["B", 1, 75.0, None], "1 枚だけの条件に SD は無い"

    book = load_workbook(os.path.join(out, "batch.xlsx"))
    assert book.sheetnames == ["Images", "Conditions"]
    assert [row[0].value for row in book["Images"].iter_rows(min_row=2)] == ["A", "A", "B"]
    chart = book["Conditions"]._charts[0]
    assert len(chart.series) == 2 and chart.series[0].errBars is not None

    # 1 枚を開いて × を 1 つ足し、同じ場所に保存してから集計し直す
    project = next(os.path.join(rows[0].folder, name) for name in os.listdir(rows[0].folder)
                   if name.endswith(".cellcounter"))
    session = load_project(project, loader=loader)
    session.click("NUC", *_at(session, 36))
    save_project(session, project)
    refreshed = refresh_batch(out, loader)
    assert refreshed[0].rates["NUC"] == pytest.approx(10 / 36 * 100, abs=0.01)
    assert refreshed[1].rates["NUC"] == 50.0

    with pytest.raises(FileNotFoundError, match="一括処理のフォルダではありません"):
        refresh_batch(str(tmp_path))
    with pytest.raises(ValueError, match="画像がありません"):
        run_batch([], template, [], out, synth.by_threshold, loader)


def test_environment_report_lists_versions_and_gpu():
    report = dict(environment_report())
    assert {"cellcounter", "Python", "napari", "cellpose", "torch", "GPU"} <= set(report)
    assert report["GPU"].startswith(("使えます", "使えません", "PyTorch を読み込めません"))
