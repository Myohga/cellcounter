"""時間のかかる処理を裏で走らせ、進み具合を表示する。"""

from __future__ import annotations

import time
from typing import Callable, Generator

from qtpy.QtCore import QObject, QTimer, Signal
from qtpy.QtWidgets import QLabel, QProgressBar
from superqt.utils import create_worker

Task = Callable[[], Generator[str, None, object]]


class TaskRunner(QObject):
    """処理は 1 つずつ。task は段階の名前を yield し、最後に結果を return する。

    所要時間が読めない処理（Cellpose など）ばかりなので、バーは動き続ける表示にして、
    経過秒数を添える。
    """

    busy_changed = Signal(bool)
    failed = Signal(str, object)
    stage = Signal(str)

    def __init__(self, bar: QProgressBar, label: QLabel) -> None:
        super().__init__()
        self._bar, self._label = bar, label
        self._bar.setRange(0, 0)
        self._bar.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self.stage.connect(self._set_stage)
        self._worker = None
        self._stage = ""
        self._started = 0.0

    @property
    def busy(self) -> bool:
        return self._worker is not None

    def start(self, title: str, task: Task, on_done: Callable[[object], None]) -> None:
        if self.busy:
            raise RuntimeError("別の処理が動いています。")
        self._stage, self._started = title, time.monotonic()
        self._worker = create_worker(task)
        self._worker.yielded.connect(self._set_stage)
        self._worker.returned.connect(lambda result: self._finish(lambda: on_done(result)))
        self._worker.errored.connect(
            lambda error: self._finish(lambda: self.failed.emit(title, error)))
        self._bar.show()
        self._tick()
        self._timer.start()
        self.busy_changed.emit(True)
        self._worker.start()

    def _set_stage(self, stage: str) -> None:
        self._stage = stage
        self._tick()

    def _tick(self) -> None:
        self._label.setText(f"{self._stage}（{time.monotonic() - self._started:.0f} 秒）")

    def _finish(self, then: Callable[[], None]) -> None:
        self._timer.stop()
        self._bar.hide()
        self._label.setText("")
        self._worker = None
        self.busy_changed.emit(False)
        then()
