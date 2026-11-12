"""× の操作（数えない・戻す・円い核を作る・陽性／陰性の切り替え）と Undo / Redo。"""

import numpy as np
import pytest

import synth
from cellcounter.marks import ADDED, AUTO, REMOVED
from cellcounter.tally import counted_ids


@pytest.fixture
def session():
    """5×5 の核。1〜3 が NUC 陽性。右下に、QC で外れる小さな核（ID 26）を足してある。"""
    labels = synth.grid_labels(5, 5)
    synth._stamp(labels, 170, 170, 26, radius=2)
    planes = [synth.dapi_plane(labels, 1), synth.marker_plane(labels, {1, 2, 3}, "nucleus", 2)]
    return synth.build_session(labels, planes, [(1, "NUC", "nuclear")])


def _at(session, nucleus_id: int) -> tuple[float, float]:
    nucleus = session.nuclei[nucleus_id]
    return nucleus.y, nucleus.x


def _state(session):
    marks = session.marks
    return (dict(marks.counted), {m: dict(v) for m, v in marks.positive.items()},
            sorted(session.nuclei), session.labels.copy())


def _same(a, b) -> bool:
    return a[:3] == b[:3] and np.array_equal(a[3], b[3])


def test_automatic_result(session):
    assert counted_ids(session) == list(range(1, 26))
    assert "面積が小さすぎる" in session.nuclei[26].qc_reasons
    assert [session.marks.category("NUC", i) for i in (1, 2, 3, 4)] == [AUTO, AUTO, AUTO, None]


def test_dapi_tab_uncount_and_restore(session):
    session.click(None, *_at(session, 1))
    assert session.marks.category(None, 1) == REMOVED
    assert session.marks.category("NUC", 1) is None, "数えない核はマーカーのタブに出さない"
    assert 1 not in counted_ids(session)

    session.click(None, *_at(session, 1))
    assert session.marks.category(None, 1) == AUTO
    assert session.marks.category("NUC", 1) == AUTO, "核のデータは残っているので判定も戻る"


def test_dapi_tab_counts_a_nucleus_excluded_by_qc(session):
    session.click(None, *_at(session, 26))
    assert session.marks.category(None, 26) == ADDED
    assert 26 in counted_ids(session)


def test_marker_tab_toggles_positive(session):
    session.click("NUC", *_at(session, 1))
    assert session.marks.category("NUC", 1) == REMOVED
    session.click("NUC", *_at(session, 4))
    assert session.marks.category("NUC", 4) == ADDED
    session.click("NUC", *_at(session, 4))
    assert session.marks.category("NUC", 4) is None


def test_marker_tab_click_on_uncounted_nucleus_counts_it_as_positive(session):
    session.click("NUC", *_at(session, 26))
    assert session.marks.counted[26] and session.marks.positive["NUC"][26]
    assert session.undo()
    assert not session.marks.counted[26] and not session.marks.positive["NUC"][26]


def test_click_on_empty_place_makes_a_round_nucleus(session):
    before = len(session.nuclei)
    session.click(None, 15.0, 100.0)
    created = session.nuclei[max(session.nuclei)]
    assert len(session.nuclei) == before + 1 and created.manual
    assert created.area_px == pytest.approx(np.pi * (session.diameter_px / 2) ** 2, rel=0.1)
    assert session.marks.category(None, created.id) == ADDED
    assert session.marks.positive["NUC"][created.id] is False, "暗い場所なので自動判定は陰性"
    assert np.isfinite(session.judgements["NUC"].values[created.id])

    session.click("NUC", 15.0, 60.0)
    second = max(session.nuclei)
    assert session.marks.category(None, second) == ADDED, "DAPI のみのタブにも × が付く"
    assert session.marks.category("NUC", second) == ADDED


def test_round_nucleus_does_not_overwrite_existing_nuclei(session):
    labels_before = session.labels.copy()
    nucleus = session.nuclei[7]
    session.click(None, nucleus.y, nucleus.x + synth.RADIUS + 3)
    kept = labels_before > 0
    assert np.array_equal(session.labels[kept], labels_before[kept])


def test_undo_and_redo_restore_every_step(session):
    states = [_state(session)]
    clicks = [(None, _at(session, 1)), ("NUC", _at(session, 4)), (None, (15.0, 100.0)),
              ("NUC", (15.0, 60.0)), (None, _at(session, 26)), ("NUC", _at(session, 2))]
    for marker, (y, x) in clicks:
        session.click(marker, y, x)
        states.append(_state(session))

    for expected in reversed(states[:-1]):
        assert session.undo()
        assert _same(_state(session), expected)
    assert not session.undo()

    for expected in states[1:]:
        assert session.redo()
        assert _same(_state(session), expected)
    assert not session.redo()


def test_new_edit_discards_redo(session):
    session.click(None, *_at(session, 1))
    session.undo()
    session.click(None, *_at(session, 2))
    assert not session.redo()


def test_history_keeps_at_least_fifty_steps(session):
    start = _state(session)
    for number in range(60):
        session.click("NUC", *_at(session, 1 + number % 25))
    for _ in range(60):
        assert session.undo()
    assert _same(_state(session), start)
