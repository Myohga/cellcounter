"""読み込みまわり（軸・Z 投影・メタデータ・色素・チャンネル表・設定）。"""

import numpy as np
import pytest

import synth
from cellcounter.channels import apply_preset, build_table, load_preset, preset_of, save_preset
from cellcounter.czi import project_z, read_scene, to_czyx
from cellcounter.dyes import identify_dye
from cellcounter.markers import guess_location
from cellcounter.metadata import compare_acquisition, parse_metadata
from cellcounter.quality import assess, quality_warning
from cellcounter.segment import display_clip
from cellcounter.settings import Settings

XML = """<ImageDocument><Metadata>
<Information>
 <Image><ComponentBitCount>12</ComponentBitCount>
  <ObjectiveSettings><ObjectiveRef Id="Objective:1"/></ObjectiveSettings>
  <Dimensions><Channels>
   <Channel Id="Channel:0" Name="AF555-T1"><Fluor>Alexa Fluor 555</Fluor><Color>#FFFF7E00</Color>
    <ExcitationWavelength>553</ExcitationWavelength><EmissionWavelength>568</EmissionWavelength>
    <ContrastMethod>Fluorescence</ContrastMethod>
    <DetectorSettings><Voltage>{gain}</Voltage><DigitalGain>1</DigitalGain></DetectorSettings>
    <LightSourcesSettings><LightSourceSettings><Attenuation>0.8</Attenuation>
     <Wavelength>561</Wavelength></LightSourceSettings></LightSourcesSettings></Channel>
   <Channel Id="Channel:1" Name="H3342-T3"><Fluor>Hoechst 33342</Fluor>
    <EmissionWavelength>455</EmissionWavelength><ContrastMethod>Fluorescence</ContrastMethod>
   </Channel>
   <Channel Id="Channel:2" Name="T-PMT-T3"><ContrastMethod>Other</ContrastMethod></Channel>
  </Channels></Dimensions></Image>
 <Instrument><Objectives>
  <Objective Id="Objective:1" Name="Plan-Apochromat 20x/0.8 M27"/></Objectives></Instrument>
</Information>
<Scaling><Items><Distance Id="X"><Value>3.12e-07</Value></Distance></Items></Scaling>
</Metadata></ImageDocument>"""


def test_axes_are_reordered_by_name():
    array = np.arange(1 * 1 * 3 * 1 * 2 * 5 * 6).reshape(1, 1, 3, 1, 2, 5, 6, 1)
    czyx, notes = to_czyx(array, "BVCTZYX0")
    assert czyx.shape == (3, 2, 5, 6) and notes == []
    assert np.array_equal(czyx[2, 1], array[0, 0, 2, 0, 1, :, :, 0])

    yx, _ = to_czyx(np.zeros((5, 6)), "YX")
    assert yx.shape == (1, 1, 5, 6)


def test_dropped_axes_are_reported_not_hidden():
    _, notes = to_czyx(np.zeros((2, 3, 5, 6)), "TCYX")
    assert len(notes) == 1 and "時間" in notes[0]
    with pytest.raises(ValueError, match="RGB"):
        to_czyx(np.zeros((5, 6, 3)), "YX0")


def test_z_projection():
    stack = np.array([[[1, 9]], [[5, 2]], [[3, 3]]])
    assert project_z(stack, "max").tolist() == [[5, 9]]
    assert project_z(stack, "mean").tolist() == [[3.0, pytest.approx(14 / 3)]]
    assert project_z(stack, "best").tolist() == [[1, 9]]
    with pytest.raises(ValueError, match="Z 投影"):
        project_z(stack, "none")


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_scene(str(tmp_path / "無い.czi"))


def test_metadata_is_parsed():
    meta = parse_metadata(XML.format(gain=550))
    assert meta.um_per_px == pytest.approx(0.312)
    assert meta.bits == 12 and meta.objective == "Plan-Apochromat 20x/0.8 M27"
    first = meta.channels[0]
    assert (first.name, first.emission_nm, first.contrast) == ("AF555-T1", 568.0, "Fluorescence")
    assert first.acquisition == {"検出器ゲイン (V)": "550", "デジタルゲイン": "1",
                                 "光源 561 nm の減衰": "0.8"}


def test_different_acquisition_is_warned():
    sample = parse_metadata(XML.format(gain=550))
    assert compare_acquisition(sample, parse_metadata(XML.format(gain=550.0001)), "対照") == []
    warnings = compare_acquisition(sample, parse_metadata(XML.format(gain=700)), "対照")
    assert len(warnings) == 1 and "検出器ゲイン" in warnings[0] and "700" in warnings[0]

    sample.objective = ""
    unknown = compare_acquisition(sample, parse_metadata(XML.format(gain=550)), "対照")
    assert len(unknown) == 1 and "比較していません" in unknown[0] and "対物レンズ" in unknown[0]


@pytest.mark.parametrize("names, emission, dye", [
    (("AF647-T3", "Alexa Fluor 647"), 668.0, "AF647"),
    (("AF568",), None, "AF568"),
    (("H3342-T3", "Hoechst 33342"), 455.0, "Hoechst"),
    (("Cy5",), None, "AF647"),
    (("Dye5",), 519.0, "AF488"),
    (("Dye5",), None, ""),
    (("Ch1",), 900.0, ""),
])
def test_dye_is_identified_by_name_then_wavelength(names, emission, dye):
    assert identify_dye(*names, emission_nm=emission) == dye


def test_table_is_built_from_metadata():
    table = build_table(parse_metadata(XML.format(gain=550)))
    assert [row.role for row in table.rows] == ["marker", "dapi", "unused"]
    assert table.dapi.name == "H3342-T3" and table.rows[0].dye == "AF555"
    assert [row.color for row in table.rows] == ["#FF7E00", "#0076FF", "#FFFFFF"], (
        "表示色は ZEN の色。無ければ蛍光波長から決め、蛍光でなければ白")
    with pytest.raises(ValueError, match="蛍光チャンネルではない"):
        table.set_dapi(2)


def test_dapi_is_not_guessed_when_ambiguous():
    image = synth.fake_image([np.zeros((4, 4), np.uint16)] * 2)
    image.meta.channels[1].name, image.meta.channels[1].fluor = "DAPI", "DAPI"
    table = build_table(image.meta)
    assert all(row.role == "marker" for row in table.rows)
    assert "DAPI のチャンネルが決まっていません。" in table.problems()
    table.set_dapi(1)
    assert table.dapi.index == 1 and table.problems() == []


@pytest.mark.parametrize("marker, location", [
    ("Islet-1", "nuclear"), ("NKX2.1", "nuclear"), ("MAP2", "fibrillar"), ("ChAT", "cytoplasmic"),
    ("Synapsin 1", "punctate"), ("Islet-1 (mouse)", "nuclear"), ("TH", "cytoplasmic"),
    ("AT8", "fibrillar"), ("EP2456Y", "fibrillar"), ("6E10", "cytoplasmic"),
    ("Cathepsin D", None), ("MyNewProtein", None),
])
def test_location_is_guessed_only_from_the_dictionary(marker, location):
    assert guess_location(marker) == location


def test_unknown_marker_needs_a_location_from_the_user():
    table = build_table(synth.fake_image([np.zeros((4, 4), np.uint16)] * 3).meta)
    table.set_marker(1, "MyNewProtein")
    assert any("染まる場所を選んでください" in problem for problem in table.problems())
    table.set_marker(1, "MyNewProtein", "membrane")
    assert table.problems() == []
    table.set_marker(2, "MyNewProtein", "nuclear")
    assert any("重複" in problem for problem in table.problems())
    with pytest.raises(ValueError, match="染まる場所"):
        table.set_marker(2, "X", "everywhere")


def test_preset_round_trip(tmp_path):
    meta = synth.fake_image([np.zeros((4, 4), np.uint16)] * 3).meta
    table = build_table(meta)
    table.set_marker(1, "MAP2")
    table.set_marker(2, "Islet-1", judge=False)
    path = str(tmp_path / "運動ニューロン.json")
    save_preset(path, preset_of(table, "運動ニューロン"))

    other = build_table(meta)
    apply_preset(other, load_preset(path))
    assert other.to_list() == table.to_list()

    with pytest.raises(ValueError, match="形式"):
        apply_preset(other, {"format": 2, "channels": []})
    two_channels = build_table(synth.fake_image([np.zeros((4, 4), np.uint16)] * 2).meta)
    with pytest.raises(ValueError, match="対応するチャンネル"):
        apply_preset(two_channels, load_preset(path))


def test_settings_reject_unknown_values():
    assert Settings.from_dict(Settings().to_dict()) == Settings()
    with pytest.raises(ValueError, match="未知の項目"):
        Settings.from_dict({"judge": {"otsu": True}})
    with pytest.raises(ValueError, match="Z 投影"):
        Settings(z_projection="none")


def test_display_clip_and_quality():
    image = np.array([[0, 32, 64, 255]], np.uint8)
    assert display_clip(image, 0.0, 0.25, 255.0).round(2).tolist() == [[0.0, 0.5, 1.0, 1.0]]
    with pytest.raises(ValueError, match="Black < White"):
        display_clip(image, 0.5, 0.25, 255.0)

    dark = assess(np.full((10, 10), 30, np.uint8), 8)
    assert "階調が足りない" in quality_warning("MAP2", dark)
    bright = assess(np.full((10, 10), 4095, np.uint16), 12)
    assert bright.saturated_fraction == 1.0 and "飽和" in quality_warning("MAP2", bright)
    assert quality_warning("MAP2", assess(np.full((10, 10), 2000, np.uint16), 12)) is None


def test_launch_bat_is_readable_by_cmd():
    """cmd.exe は .bat を日本語 Windows の文字コードで読む。UTF-8 の日本語や LF だけの改行があると、

    行の途中から別のコマンドとして実行されて壊れる（「'onda' は…認識されていません」）。
    """
    import pathlib

    data = (pathlib.Path(__file__).parent.parent / "launch.bat").read_bytes()
    assert all(byte < 128 for byte in data)
    assert data.count(b"\n") == data.count(b"\r\n") > 0
