"""集計・Excel・確認用画像・作業ファイル。出力の数字が内部の値と一致することを確かめる。"""

import json
import os
import zipfile

import pytest
from openpyxl import load_workbook

import synth
from cellcounter import __version__
from cellcounter.excel import PROVISIONAL, TABLE_TOP
from cellcounter.export import export_results, results_name
from cellcounter.project import load_project
from cellcounter.tally import cell_table, coexpression, counted_ids, summarize


@pytest.fixture(scope="module")
def session():
    """核 100 個。NUC は 1〜40、CYT は 21〜70 が陽性。そのあと人が何か所か直してある。"""
    session = synth.two_marker_session(10, 10, set(range(1, 41)), set(range(21, 71)))
    for marker, nucleus_id in ((None, 5), ("NUC", 1), ("NUC", 90), ("CYT", 30), ("CYT", 95)):
        nucleus = session.nuclei[nucleus_id]
        session.click(marker, nucleus.y, nucleus.x)
    session.click("CYT", 15.0, 100.0)
    return session


def _rows(sheet) -> list[list]:
    return [list(row) for row in sheet.iter_rows(min_row=TABLE_TOP + 1, values_only=True)
            if row[0] is not None]


def test_summary_counts(session):
    dapi, nuc, cyt = summarize(session)
    assert (dapi.total, dapi.auto_positive, dapi.added, dapi.removed) == (100, 100, 1, 1)
    assert (nuc.positive, nuc.auto_positive, nuc.added, nuc.removed) == (39, 40, 1, 1)
    assert nuc.rate == 39.0 and nuc.auto_rate == 40.0
    # CYT: 自動 50、30 を消し、95 と手で作った核を足した。数えない核 5 は CYT 陰性なので影響しない
    assert (cyt.positive, cyt.added, cyt.removed) == (51, 2, 1)


def test_coexpression_matches_the_cell_table(session):
    header, rows = cell_table(session)
    counted = [row for row in rows if row[header.index("数える")] == "はい"]
    assert len(counted) == len(counted_ids(session))

    table = coexpression(session)
    assert sum(row.cells for row in table) == len(counted)
    for row in table:
        wanted = {part[:-1]: part[-1] == "＋" for part in row.name.split("/")}
        cells = sum(all((r[header.index(f"{marker} 確定判定")] == "陽性") == positive
                        for marker, positive in wanted.items()) for r in counted)
        assert cells == row.cells, row.name


def test_export_writes_everything_into_a_new_folder(session, tmp_path):
    folder = str(tmp_path / "結果 フォルダ")
    assert not os.path.exists(folder)
    assert export_results(session, folder) == folder
    names = set(os.listdir(folder))
    assert {results_name(), "synthetic.cellcounter", "確認_DAPI_のみ.png", "確認_DAPI＋NUC.png",
            "確認_DAPI＋CYT.png"} <= names
    assert not session.dirty

    book = load_workbook(os.path.join(folder, results_name()))
    assert book.sheetnames == ["Summary", "Coexpression", "Cells", "Settings", "Thresholds"]
    for sheet in book:
        assert sheet["A2"].value == PROVISIONAL

    summary = _rows(book["Summary"])
    for written, row in zip(summary, summarize(session)):
        assert written[:9] == [row.name, row.total, row.positive, row.auto_positive, row.added,
                               row.removed, row.undetermined, row.auto_rate, row.rate]
    assert len(book["Summary"]._charts) == 1
    assert len(book["Coexpression"]._charts) == 1

    assert [row[:3] for row in _rows(book["Coexpression"])] == [
        [row.name, row.cells, row.rate] for row in coexpression(session)]
    assert len(_rows(book["Cells"])) == len(session.nuclei)
    settings = dict(row[:2] for row in _rows(book["Settings"]))
    assert settings["ソフトの版"] == f"cellcounter {__version__}"
    assert settings["判定の状態"] == "暫定（陰性対照なし）"
    assert "NUC: 閾値" in settings and "CYT: 測り方" in settings


def test_project_file_resumes_the_work(session, tmp_path):
    folder = export_results(session, str(tmp_path / "out"))
    path = os.path.join(folder, "synthetic.cellcounter")
    resumed = load_project(path, loader=lambda czi, scene, z: synth.fake_image(
        list(session.image.planes)))

    assert summarize(resumed) == summarize(session)
    assert coexpression(resumed) == coexpression(session)
    assert cell_table(resumed) == cell_table(session)
    assert resumed.provisional

    nucleus = resumed.nuclei[50]
    resumed.click("NUC", nucleus.y, nucleus.x)
    assert summarize(resumed)[1].positive == summarize(session)[1].positive + 1


def test_project_with_unknown_format_is_rejected(session, tmp_path):
    folder = export_results(session, str(tmp_path / "out"))
    path = os.path.join(folder, "synthetic.cellcounter")
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("project.json"))
        labels = archive.read("labels.npy")
    newer = str(tmp_path / "newer.cellcounter")
    with zipfile.ZipFile(newer, "w") as archive:
        archive.writestr("project.json", json.dumps({**data, "format": 99}))
        archive.writestr("labels.npy", labels)
    with pytest.raises(ValueError, match="形式"):
        load_project(newer)


def test_project_needs_the_original_czi(session, tmp_path):
    folder = export_results(session, str(tmp_path / "out"))
    with pytest.raises(FileNotFoundError):
        load_project(os.path.join(folder, "synthetic.cellcounter"))
