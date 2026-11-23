"""平均蛍光強度（ZEN の Intensity Mean Value）。範囲の形・値・元に戻す・保存・出力・ファイル名。"""

import os
from datetime import date

import numpy as np
import pytest
from openpyxl import load_workbook

import synth
from cellcounter.excel import IMV_SHEET, IMV_TITLE, TABLE_TOP
from cellcounter.export import export_results, results_name
from cellcounter.intensity import ALL_REGIONS, WHOLE_IMAGE, Region
from cellcounter.project import load_project, save_project
from cellcounter.session import IMV_TAB
from cellcounter.tally import cell_table, coexpression, settings_record, summarize

RECT = Region.of("rectangle", [[10, 20], [10, 59], [39, 59], [39, 20]])
CIRCLE = Region.of("ellipse", [[100, 100], [100, 160], [160, 160], [160, 100]])


@pytest.fixture
def session():
    """核 36 個。NUC は陽性率、TAU（チャンネル 2）は平均蛍光強度で測る。"""
    labels = synth.grid_labels(6, 6)
    planes = [synth.dapi_plane(labels, 1), synth.marker_plane(labels, {1, 2, 3}, "nucleus", 2),
              synth.marker_plane(labels, set(range(1, 19)), "cytoplasm", 3)]
    image = synth.fake_image(planes)
    from cellcounter.channels import build_table
    from cellcounter.pipeline import open_session, run_detection, run_judgement
    from cellcounter.settings import Settings

    table = build_table(image.meta)
    table.set_marker(1, "NUC", "nuclear")
    table.set_marker(2, "TAU", "", method="imv")
    session = open_session(image, table, Settings())
    run_detection(session, synth.known_labels(labels))
    run_judgement(session, None)
    return session


def test_shapes_cover_the_pixels_zen_would_measure():
    shape = (200, 200)
    assert RECT.mask(shape).sum() == 30 * 40
    assert RECT.mask(shape)[10:40, 20:60].all()
    # 直径 60 px の円。面積は π × 30² にほぼ等しい
    assert CIRCLE.mask(shape).sum() == pytest.approx(np.pi * 30 ** 2, rel=0.01)
    assert CIRCLE.contains(np.array([[130, 130], [101, 101]])).tolist() == [True, False]
    # 縁の上の画素も入れる（四角形と同じ決まり）ので、直角の辺が 100 px なら 101 × 102 / 2 個
    triangle = Region.of("polygon", [[0, 0], [0, 100], [100, 0]])
    assert triangle.mask(shape).sum() == 101 * 102 // 2
    rotated = Region.of("ellipse", [[50, 0], [0, 50], [50, 100], [100, 50]])
    assert rotated.mask(shape).sum() == pytest.approx(np.pi * (50 / np.sqrt(2)) ** 2, rel=0.01)
    with pytest.raises(ValueError, match="頂点が 3 つ以上"):
        Region.of("polygon", [[0, 0], [5, 5]])


def test_markers_measured_by_intensity_are_not_judged(session):
    assert list(session.judgements) == ["NUC"]
    assert session.imv_channels == {"TAU": 2}
    assert [row.name for row in summarize(session)] == ["DAPI のみ", "DAPI＋NUC"]
    header, _rows = cell_table(session)
    assert not any("TAU" in text for text in header)
    assert all("TAU" not in row.name for row in coexpression(session))


def test_whole_image_is_measured_until_a_region_is_drawn(session):
    [row] = session.intensity()
    plane = session.image.planes[2]
    assert (row.name, row.area_px, row.nuclei) == (WHOLE_IMAGE, plane.size, 36)
    assert row.stats[2].mean == pytest.approx(plane.mean())
    assert row.stats[2].sd == pytest.approx(plane.std())
    assert (row.stats[2].minimum, row.stats[2].maximum) == (plane.min(), plane.max())
    assert row.area_um2 == pytest.approx(plane.size * synth.UM_PER_PX ** 2, abs=0.01)


def test_each_region_and_their_union_are_measured(session):
    assert session.set_regions([RECT, CIRCLE]) and session.dirty
    plane = session.image.planes[2]
    rect, circle, both = session.intensity()
    assert (rect.name, rect.shape, circle.name, both.name) == ("範囲 1", "四角形", "範囲 2",
                                                               ALL_REGIONS)
    assert rect.stats[2].mean == pytest.approx(plane[10:40, 20:60].mean())
    union = RECT.mask(plane.shape) | CIRCLE.mask(plane.shape)
    assert both.area_px == union.sum() == rect.area_px + circle.area_px
    assert both.stats[2].mean == pytest.approx(plane[union].mean())
    inside = [n for n in session.nuclei.values()
              if RECT.contains(np.array([[n.y, n.x]]))[0]]
    assert rect.nuclei == len(inside) > 0


def test_region_edits_can_be_undone(session):
    session.set_regions([RECT])
    session.set_regions([RECT, CIRCLE])
    assert not session.set_regions([RECT, CIRCLE]), "変わらなければ履歴に積まない"
    session.undo()
    assert session.regions == [RECT]
    session.undo()
    assert session.regions == [] and session.intensity()[0].name == WHOLE_IMAGE
    session.redo()
    assert session.regions == [RECT]


def test_clicks_on_the_intensity_tab_do_not_touch_nuclei(session):
    nucleus = session.nuclei[1]
    with pytest.raises(ValueError, match="平均蛍光強度のタブ"):
        session.click(IMV_TAB, nucleus.y, nucleus.x)
    assert session.shown_channels(IMV_TAB) == [0, 2], "DAPI と平均蛍光強度のマーカー"


def test_regions_are_saved_in_the_work_file(session, tmp_path):
    session.set_regions([RECT, CIRCLE])
    path = str(tmp_path / "work.cellcounter")
    save_project(session, path)
    resumed = load_project(path, loader=lambda czi, scene, z: synth.fake_image(
        list(session.image.planes)))
    assert resumed.regions == [RECT, CIRCLE] and resumed.imv_channels == {"TAU": 2}
    assert [row.stats[2].mean for row in resumed.intensity()] == [
        row.stats[2].mean for row in session.intensity()]


def test_result_file_name_has_the_chosen_name_and_the_date():
    day = date(2026, 11, 23)
    assert results_name("", day) == "result_2026-11-23.xlsx"
    assert results_name("  tau day40 ", day) == "tau day40_result_2026-11-23.xlsx"
    assert results_name("実験A", day) == "実験A_result_2026-11-23.xlsx"
    with pytest.raises(ValueError, match="使えない文字"):
        results_name("a/b", day)


def test_export_keeps_intensity_out_of_the_existing_sheets(session, tmp_path):
    session.set_regions([RECT, CIRCLE])
    folder = export_results(session, str(tmp_path / "out"), "tau")
    name = results_name("tau")
    names = set(os.listdir(folder))
    assert {name, "確認_平均蛍光強度.png", "確認_DAPI＋NUC.png"} <= names
    assert "確認_DAPI＋TAU.png" not in names

    book = load_workbook(os.path.join(folder, name))
    assert book.sheetnames == ["Summary", IMV_SHEET, "Coexpression", "Cells", "Settings",
                               "Thresholds"]
    for sheet in ("Coexpression", "Cells", "Thresholds"):
        text = " ".join(str(cell) for row in book[sheet].iter_rows(values_only=True)
                        for cell in row if cell is not None)
        assert "TAU" not in text and "平均蛍光強度" not in text, sheet

    imv = book[IMV_SHEET]
    header = [cell.value for cell in imv[TABLE_TOP]]
    assert header[:7] == ["範囲", "形", "面積 (px)", "面積 (µm²)", "範囲内の数える核",
                          "位置（px、外接する四角形）", "TAU 平均蛍光強度"]
    assert header[7:10] == ["TAU 蛍光強度の標準偏差", "TAU 蛍光強度の最小値", "TAU 蛍光強度の最大値"]
    assert any(text and text.startswith("NUC ") for text in header), "ほかのチャンネルも参考に出す"
    rows = [[cell.value for cell in row] for row in imv.iter_rows(min_row=TABLE_TOP + 1)
            if row[0].value]
    measured = session.intensity()
    assert [row[0] for row in rows] == [row.name for row in measured]
    assert [row[6] for row in rows] == [round(row.stats[2].mean, 2) for row in measured]
    assert len(imv._charts) == 1

    summary = [[cell.value for cell in row] for row in book["Summary"].iter_rows()]
    top = next(number for number, row in enumerate(summary) if row[0] == IMV_TITLE)
    assert summary[top + 1][:4] == ["範囲", "面積 (µm²)", "範囲内の数える核", "TAU 平均蛍光強度"]
    assert [row[0] for row in summary[top + 2:top + 5]] == ["範囲 1", "範囲 2", ALL_REGIONS]
    marker_rows = [row[0] for row in summary[TABLE_TOP:top] if row[0]]
    assert marker_rows[:2] == ["DAPI のみ", "DAPI＋NUC"] and "DAPI＋TAU" not in marker_rows

    record = dict(settings_record(session))
    assert "判定法 平均蛍光強度" in record["チャンネル 2: AF555-T1（AF555）"]


def test_export_without_intensity_markers_is_unchanged(tmp_path):
    session = synth.two_marker_session(4, 4, {1}, {2})
    folder = export_results(session, str(tmp_path / "out"))
    book = load_workbook(os.path.join(folder, results_name()))
    assert IMV_SHEET not in book.sheetnames
    assert "確認_平均蛍光強度.png" not in os.listdir(folder)
    assert not any(cell == IMV_TITLE for row in book["Summary"].iter_rows(values_only=True)
                   for cell in row)


def test_float32_rounding_is_not_a_change():
    from cellcounter.intensity import same_regions

    # 大きなタイル画像では、32 ビットの小数が小数第 3 位を持てない（65432.123 → 65432.125）
    far = Region.of("rectangle", [[65432.123, 43210.987], [65432.123, 43300.0],
                                  [65500.0, 43300.0], [65500.0, 43210.987]])
    stored = Region.of("rectangle", np.array(far.points, dtype=np.float32))
    assert stored != far and same_regions([stored], [far])
    assert not same_regions([far], [CIRCLE]) and not same_regions([far], [])


def test_intensity_tab_follows_the_judged_state(session):
    session.table.set_marker(1, "NUC2", "nuclear", method="imv")
    assert session.imv_markers() == {"TAU": 2}, "判定し直すまでは、判定したときのまま"
