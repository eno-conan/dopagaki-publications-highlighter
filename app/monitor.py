"""開いている質問の Issue を、一定の間隔で見張り、回答が揃ったら、反映して Claude を起動する（`web.py` の中で動く）。

`作業開始.bat` のウィンドウ（= `web.py`）が開いている間、ずっと続く。毎回、Issue と articles.json を読み直すので、
分け方を変えたあとでも、古い状態のまま止まることはない。

- 回答が揃った（目的・色・最後の「作業開始OK」）→ 反映して Issue にコメントし、Claude を起動する
- 「分け方を変えたい」が選ばれた / 回答が矛盾している → 何もしない（画面の状況は「回答待ち」のまま）
- すでに反映済み（split.approved が空でない）の本・号は、対象外
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import read_answers
import start
import watch


class Monitor:
    def __init__(
        self,
        interval: int = 120,
        open_issues: Callable[[], dict[str, int]] = start.open_issues,
        evaluate: Callable[[dict, int], read_answers.Result] = read_answers.evaluate,
        apply: Callable[[Path, dict, read_answers.Result, int], None] = read_answers.apply_and_comment,
        launch: Callable[[Path, int], subprocess.Popen] = watch.launch_claude,
        output: Path | None = None,
    ) -> None:
        self.interval = interval
        self._open_issues, self._evaluate, self._apply, self._launch = open_issues, evaluate, apply, launch
        self._output = output
        self.running: dict[Path, subprocess.Popen] = {}
        self.last_check: datetime | None = None
        self.error = ""
        self.started: list[str] = []  # 起動した本・号の名前
        self._stop = threading.Event()

    def tick(self) -> list[str]:
        """1回確認する。反映して Claude を起動した本・号の名前を返す。"""
        started = []
        try:
            for plan_path, number in start.pending_books(self._open_issues(), self._output or start.OUTPUT):
                proc = self.running.get(plan_path)
                if proc is not None and proc.poll() is None:
                    continue  # すでに Claude が動いている
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                result = self._evaluate(plan, number)
                if result.status != "ready":
                    continue
                self._apply(plan_path, plan, result, number)
                self.running[plan_path] = self._launch(plan_path, number)
                started.append(plan_path.parent.name)
            self.error = ""
        except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
            self.error = str(e)  # 一時的な失敗（ネットワークなど）。次の回で、もう一度試す
        self.last_check = datetime.now()
        self.started += started
        return started

    def loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval)

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.loop, daemon=True, name="monitor")
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    def info(self) -> dict:
        return {
            "interval": self.interval,
            "last_check": self.last_check.strftime("%H:%M:%S") if self.last_check else "",
            "error": self.error,
            "started": self.started,
            "working": [p.parent.name for p, proc in self.running.items() if proc.poll() is None],
        }
