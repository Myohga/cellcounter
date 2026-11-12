"""陽性判定。Otsu が失敗する条件（陽性率 0%・100%）を含めて、数が合うことを確かめる。"""

import numpy as np
import pytest

import synth
from cellcounter.control import collect_control
from cellcounter.judge import MeasureInput, RULES, judge_marker, measure
from cellcounter.pipeline import run_judgement
from cellcounter.rois import Geometry
from cellcounter.settings import JudgeSettings
from cellcounter.tally import summarize


def _positive_ids(session, marker: str) -> set[int]:
    return {i for i, positive in session.marks.positive[marker].items() if positive}


def _rate(session, marker: str) -> float:
    return next(row.rate for row in summarize(session) if row.name == f"DAPI＋{marker}")


def test_image_like_the_control_gives_about_one_percent():
    control = synth.negative_control(40, 40, seed=100)
    session = synth.two_marker_session(40, 40, set(), set(), control, seed=200)
    assert not session.provisional
    for marker in ("NUC", "CYT"):
        assert 0.2 <= _rate(session, marker) <= 2.5


def test_ninety_five_percentile_gives_about_five_percent():
    control = synth.negative_control(40, 40, seed=100)
    session = synth.two_marker_session(40, 40, set(), set(), seed=200)
    session.settings.judge.control_percentile = 95.0
    data = collect_control(session, [("control.czi", 0)], synth.by_threshold,
                           lambda path, scene, z: control)
    run_judgement(session, data)
    for marker in ("NUC", "CYT"):
        assert 3.0 <= _rate(session, marker) <= 7.5


@pytest.mark.parametrize("fraction", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("with_control", [True, False])
def test_known_number_of_positive_cells_is_counted(fraction, with_control):
    total = 400
    nuclear = set(range(1, int(total * fraction) + 1))
    cytoplasmic = set(range(total - int(total * fraction) + 1, total + 1))
    control = synth.negative_control(20, 20, seed=300) if with_control else None
    session = synth.two_marker_session(20, 20, nuclear, cytoplasmic, control)

    assert session.provisional is not with_control
    for marker, truth in (("NUC", nuclear), ("CYT", cytoplasmic)):
        found = _positive_ids(session, marker)
        assert truth <= found, "陽性の細胞を取りこぼしている"
        allowed = 0.04 * (total - len(truth)) if with_control else 0
        assert len(found - truth) <= allowed, "陰性の細胞を陽性にしすぎている"


def test_touching_positive_neighbour_does_not_break_the_ratio():
    """核が接していても、陽性は陽性、陰性は陰性のまま。隣からのにじみ（ぼけ）も入れる。"""
    pairs = 60
    labels = synth.pair_labels(pairs)
    left = set(range(1, 2 * pairs, 2))
    both = set(range(2, pairs + 1, 2))  # 前半の組は右も陽性、後半の組は右が陰性
    positive = left | both
    planes = [synth.dapi_plane(labels, 1),
              synth.marker_plane(labels, positive, "nucleus", 2, blur=1.0)]
    session = synth.build_session(labels, planes, [(1, "NUC", "nuclear")],
                                  synth.negative_control(20, 20, seed=300, stains=("nucleus",)))
    assert _positive_ids(session, "NUC") == positive

    ratio = session.judgements["NUC"].values
    beside_positive = np.median([ratio[i] for i in range(1, pairs, 2)])
    beside_negative = np.median([ratio[i] for i in range(pairs + 1, 2 * pairs, 2)])
    assert beside_positive >= 0.95 * beside_negative, "隣が陽性だと比が下がっている"


def test_dark_8bit_image_does_not_stick_to_100_percent():
    """背景がほぼ 0 の 8bit 画像。旧版はここで全マーカーが陽性率 100% になった。"""
    rng = np.random.default_rng(5)
    labels = synth.grid_labels(15, 15)
    planes = [(60 * (labels > 0) + rng.poisson(0.5, labels.shape)).astype(np.uint8),
              rng.poisson(0.5, labels.shape).astype(np.uint8),
              rng.poisson(0.5, labels.shape).astype(np.uint8)]
    markers = [(1, "NUC", "nuclear"), (2, "CYT", "cytoplasmic")]

    fixed = synth.build_session(labels, planes, markers, bits=8)
    assert _rate(fixed, "NUC") == 0.0 and _rate(fixed, "CYT") == 0.0
    assert any("階調が足りない" in warning for warning in fixed.warnings)

    control = synth.fake_image(planes, bits=8)
    with_control = synth.build_session(labels, planes, markers, control, bits=8,
                                       control_segmenter=synth.known_labels(labels))
    assert _rate(with_control, "CYT") <= 2.5
    assert any("ほとんど同じ" in warning for warning in with_control.warnings)


def test_small_control_is_warned():
    control = synth.negative_control(10, 10, seed=300)
    session = synth.two_marker_session(10, 10, {1, 2}, set(), control)
    assert any("100 個しかありません" in warning for warning in session.warnings)


def _input(labels: np.ndarray) -> MeasureInput:
    plane = synth.marker_plane(labels, set(), "nucleus", 1)
    return MeasureInput.build(plane, Geometry(labels), 14.0, synth.UM_PER_PX, 12, JudgeSettings())


def test_unknown_rule_or_location_raises():
    labels = synth.grid_labels(3, 3)
    ids = np.arange(1, 10)
    with pytest.raises(ValueError, match="未知の判定法"):
        measure("nuclear", "otsu", _input(labels), ids, JudgeSettings())
    with pytest.raises(ValueError, match="染まる場所"):
        measure("somewhere", "fixed", _input(labels), ids, JudgeSettings())
    assert "otsu" not in RULES


def test_control_rule_without_control_values_raises():
    labels = synth.grid_labels(3, 3)
    session = synth.build_session(labels, [synth.dapi_plane(labels, 1),
                                           synth.marker_plane(labels, set(), "nucleus", 2)],
                                  [(1, "NUC", "nuclear")])
    row = session.table.judged()[0]
    with pytest.raises(ValueError, match="陰性対照の値がありません"):
        judge_marker(row, "control_percentile", _input(labels), np.arange(1, 10),
                     JudgeSettings(), None)


def test_unreadable_control_raises(tmp_path):
    session = synth.two_marker_session(5, 5, set(), set())
    with pytest.raises(FileNotFoundError):
        collect_control(session, [(str(tmp_path / "無い.czi"), 0)], synth.by_threshold)
    with pytest.raises(ValueError, match="指定されていません"):
        collect_control(session, [], synth.by_threshold)


def test_control_with_different_channels_raises():
    session = synth.two_marker_session(5, 5, set(), set())
    labels = synth.grid_labels(5, 5)
    other = synth.fake_image([synth.dapi_plane(labels, 1),
                              synth.marker_plane(labels, set(), "nucleus", 2)])
    with pytest.raises(ValueError, match="チャンネルの構成"):
        collect_control(session, [("control.czi", 0)], synth.by_threshold,
                        lambda path, scene, z: other)
