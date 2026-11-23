"""抗体マーカーの辞書。既定の判定法・核を数える・登録と編集と削除・保存・プリセット。"""

import json

import numpy as np
import pytest

import synth
from cellcounter.channels import apply_preset, build_table, preset_of
from cellcounter.markers import (DEFAULT_ENTRIES, MarkerDictionary, MarkerEntry, active_dictionary,
                                 guess_location, lookup, marker_key, use_dictionary)
from cellcounter.userdata import MARKERS_FILE, UserData


@pytest.fixture(autouse=True)
def fresh_dictionary():
    """テストごとに初期の辞書から始め、終わったら元に戻す（辞書はモジュール全体で 1 つ）。"""
    before = active_dictionary()
    use_dictionary(MarkerDictionary())
    yield
    use_dictionary(before)


def _table():
    return build_table(synth.fake_image([np.zeros((4, 4), np.uint16)] * 3).meta)


@pytest.mark.parametrize("marker", ["AT8", "EP2456Y", "ep-2456y", "Tau", "pTau-S396"])
def test_tau_markers_switch_to_mean_intensity(marker):
    table = _table()
    table.set_marker(1, marker)
    row = table.rows[1]
    assert row.method == "imv" and row.judge
    assert table.imv() == [row] and table.judged() == []
    assert table.problems() == []


def test_other_markers_stay_on_positive_rate():
    table = _table()
    table.set_marker(1, "MAP2")
    table.set_marker(2, "MyNewProtein", method="imv")
    assert table.rows[1].method == "rate" and table.judged() == [table.rows[1]]
    # 平均蛍光強度は染まる場所を使わないので、辞書に無い名前でも直すところは無い
    assert table.rows[2].location == "" and table.problems() == []
    table.set_marker(2, "MyNewProtein", method="rate")
    assert any("染まる場所を選んでください" in text for text in table.problems())


def test_marker_named_like_the_intensity_tab_is_rejected():
    table = _table()
    table.set_marker(1, "平均蛍光強度", "nuclear")
    assert any("タブの名前と同じ" in text for text in table.problems())


def test_nuclear_stain_in_the_dictionary_becomes_the_counting_channel():
    image = synth.fake_image([np.zeros((4, 4), np.uint16)] * 3)
    for channel in image.meta.channels:
        channel.name, channel.fluor = f"Ch{channel.index}", ""
        channel.emission_nm = 700.0 + channel.index * 50
    table = build_table(image.meta)
    assert all(row.role == "marker" for row in table.rows)
    table.set_marker(2, "DRAQ5")
    assert table.dapi.index == 2 and table.rows[2].marker == "DRAQ5"


def test_dictionary_can_be_edited():
    dictionary = MarkerDictionary()
    dictionary.add(MarkerEntry("MyTau", "fibrillar", imv=True, comment="自作の抗体"))
    use_dictionary(dictionary)
    assert lookup("my-tau").imv and guess_location("MYTAU") == "fibrillar"
    assert "自作の抗体" in lookup("MyTau").describe()

    with pytest.raises(ValueError, match="同じ名前"):
        dictionary.add(MarkerEntry("my tau"))
    with pytest.raises(ValueError, match="文字か数字"):
        dictionary.add(MarkerEntry("--"))

    dictionary.replace("MyTau", MarkerEntry("MyTau2", "cytoplasmic"))
    assert lookup("MyTau2").location == "cytoplasmic" and dictionary.exact("MyTau") is None
    dictionary.replace("AT8", MarkerEntry("AT8", "fibrillar", imv=False))
    table = _table()
    table.set_marker(1, "AT8")
    assert table.rows[1].method == "rate"

    dictionary.remove("MAP2")
    assert guess_location("MAP2") is None
    dictionary.reset()
    assert guess_location("MAP2") == "fibrillar" and lookup("AT8").imv


def test_names_with_greek_or_japanese_letters_can_be_registered():
    dictionary = MarkerDictionary()
    dictionary.add(MarkerEntry("βIII-tubulin（自家製）", "fibrillar"))
    assert marker_key("ＭＡＰ２") == "map2", "全角は半角として扱う"
    assert dictionary.find("βiii tubulin（自家製）").location == "fibrillar"


def test_dictionary_is_saved_and_a_broken_file_is_reported(tmp_path):
    folder = tmp_path / "user"
    data = UserData(str(folder))
    assert len(data.markers.entries) == len(DEFAULT_ENTRIES)
    data.markers.add(MarkerEntry("NewAb", "nuclear", comment="メモ"))
    data.markers.remove("AT8")
    data.save_markers()

    again = UserData(str(folder))
    assert again.markers.exact("NewAb").comment == "メモ" and again.markers.exact("AT8") is None
    assert again.notice == ""

    (folder / MARKERS_FILE).write_text("{broken", encoding="utf-8")
    broken = UserData(str(folder))
    assert "マーカー辞書" in broken.notice and (folder / (MARKERS_FILE + ".broken")).exists()
    assert broken.markers.exact("AT8") is not None, "読めなければ初期の辞書を使う"


def test_presets_keep_the_method_and_old_presets_still_load():
    table = _table()
    table.set_marker(1, "MAP2")
    table.set_marker(2, "AT8")
    preset = preset_of(table, "タウ")
    assert [entry["method"] for entry in preset["channels"]] == ["rate", "rate", "imv"]

    fresh = _table()
    apply_preset(fresh, json.loads(json.dumps(preset)))
    assert [row.method for row in fresh.rows] == ["rate", "rate", "imv"]

    for entry in preset["channels"]:
        del entry["method"]
    old = _table()
    apply_preset(old, preset)
    assert all(row.method == "rate" for row in old.rows), "判定法の無いプリセットは陽性率"
