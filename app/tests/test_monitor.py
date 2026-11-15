"""monitor（開いている質問の Issue の見張り）のテスト。gh も Claude も起動しない。"""

from __future__ import annotations

import json
from pathlib import Path

import read_answers as ra
from monitor import Monitor


class FakeProc:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive

    def poll(self):
        return None if self.alive else 0


def make_plan(output: Path, name: str, approved: list[str]) -> Path:
    plan = output / name / "articles.json"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        json.dumps(
            {"pdf": f"{name}.pdf", "split": {"approved": approved}, "articles": [{"id": "p1-9", "target": True}]}
        ),
        encoding="utf-8",
    )
    return plan


def make_monitor(tmp_path, issues, status="ready", calls=None):
    calls = calls if calls is not None else []
    return Monitor(
        interval=1,
        open_issues=lambda: issues,
        evaluate=lambda plan, n: ra.Result(status),
        apply=lambda path, plan, result, n: calls.append(("apply", path.parent.name, n)),
        launch=lambda path, n: calls.append(("launch", path.parent.name, n)) or FakeProc(),
        output=tmp_path,
    ), calls


def test_ready_answers_are_applied_and_claude_is_started(tmp_path):
    make_plan(tmp_path, "本", [])
    mon, calls = make_monitor(tmp_path, {"本": 20})
    assert mon.tick() == ["本"]
    assert calls == [("apply", "本", 20), ("launch", "本", 20)]  # 反映してから、Claude を起動する
    assert mon.last_check is not None and mon.info()["working"] == ["本"]


def test_nothing_happens_until_the_answers_are_ready(tmp_path):
    make_plan(tmp_path, "本", [])
    for status in ("incomplete", "change"):
        mon, calls = make_monitor(tmp_path, {"本": 20}, status)
        assert mon.tick() == [] and calls == []


def test_already_applied_books_and_books_without_an_open_issue_are_skipped(tmp_path):
    make_plan(tmp_path, "反映済み", ["p1-9"])
    make_plan(tmp_path, "Issueなし", [])
    mon, calls = make_monitor(tmp_path, {"反映済み": 21})
    assert mon.tick() == [] and calls == []


def test_a_running_claude_is_not_started_twice(tmp_path):
    plan = make_plan(tmp_path, "本", [])
    mon, calls = make_monitor(tmp_path, {"本": 20})
    mon.running[plan] = FakeProc(alive=True)
    assert mon.tick() == [] and calls == []


def test_the_plan_is_read_again_every_time(tmp_path):
    """分け方を変えたあとでも、古い状態のまま止まらない（毎回 articles.json を読み直す）。"""
    plan = make_plan(tmp_path, "本", [])
    seen = []
    mon = Monitor(
        open_issues=lambda: {"本": 20},
        evaluate=lambda p, n: seen.append(len(p["articles"])) or ra.Result("incomplete"),
        output=tmp_path,
    )
    mon.tick()
    data = json.loads(plan.read_text(encoding="utf-8"))
    data["articles"].append({"id": "p10-19", "target": True})
    plan.write_text(json.dumps(data), encoding="utf-8")
    mon.tick()
    assert seen == [1, 2]


def test_a_failure_is_recorded_and_the_next_round_tries_again(tmp_path):
    make_plan(tmp_path, "本", [])

    def broken():
        raise OSError("ネットワークに繋がりません")

    mon = Monitor(open_issues=broken, output=tmp_path)
    assert mon.tick() == [] and "ネットワーク" in mon.info()["error"] and mon.last_check is not None
    mon._open_issues = lambda: {}
    mon.tick()
    assert mon.info()["error"] == ""
