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
        launch_change=lambda path, n: calls.append(("change", path.parent.name, n)) or FakeProc(),
        fetch=lambda n: ("本文", "コメント"),
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
    mon, calls = make_monitor(tmp_path, {"本": 20}, "incomplete")
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


def test_answer_button_reports_missing_items(tmp_path):
    make_plan(tmp_path, "本", [])
    mon = Monitor(
        open_issues=lambda: {"本": 20},
        evaluate=lambda p, n: ra.Result("incomplete", ["2. 使う色は1つだけ選んでください（いま 0 個）"]),
        output=tmp_path,
    )
    r = mon.answer("本")
    assert r["ok"] is False and "使う色" in r["problems"][0]


def test_answer_button_starts_work_without_waiting(tmp_path):
    make_plan(tmp_path, "本", [])
    mon, calls = make_monitor(tmp_path, {"本": 20})
    assert mon.answer("本")["ok"] is True
    assert calls == [("apply", "本", 20), ("launch", "本", 20)]
    assert mon.answer("本")["ok"] is True and len(calls) == 2  # 2回押しても、二重に起動しない


def test_answer_button_unknown_book(tmp_path):
    mon, _ = make_monitor(tmp_path, {})
    assert mon.answer("無い本")["ok"] is False


def test_change_request_is_handed_to_claude_once_per_content(tmp_path):
    plan = make_plan(tmp_path, "本", [])
    mon, calls = make_monitor(tmp_path, {"本": 20}, "change")
    assert mon.tick() == [] and calls == [("change", "本", 20)]
    mon.running[plan] = FakeProc(alive=False)  # Claude が終わったあと
    assert mon.tick() == [] and len(calls) == 1  # Issue が変わらなければ、もう渡さない
    mon._fetch = lambda n: ("本文", "新しいコメント")
    mon.tick()
    assert len(calls) == 2  # 人が書き足したら、もう一度渡す
    assert mon.answer("本")["ok"] is True and len(calls) == 2


def test_only_one_claude_runs_at_a_time(tmp_path):
    a = make_plan(tmp_path, "本A", [])
    make_plan(tmp_path, "本B", [])
    mon, calls = make_monitor(tmp_path, {"本A": 20, "本B": 21})
    assert mon.tick() == ["本A"]  # 先の1本だけ起動する。本B は順番待ち（反映もまだしない）
    assert calls == [("apply", "本A", 20), ("launch", "本A", 20)]
    assert mon.info()["queued"] == ["本B"]
    assert mon.answer("本B")["ok"] is True and len(calls) == 2
    a.write_text(
        a.read_text(encoding="utf-8").replace('"approved": []', '"approved": ["p1-9"]'), encoding="utf-8"
    )  # 本物の apply が書く
    mon.running[a] = FakeProc(alive=False)  # 本A が終わったら、次の確認で本B が始まる
    assert mon.tick() == ["本B"] and ("launch", "本B", 21) in calls
    assert mon.info()["queued"] == []


def test_same_issue_content_is_not_handed_again_after_restart(tmp_path):
    """画面を閉じて起動し直しても、同じ内容の Issue を、もう一度 Claude に渡さない（返事待ちとして表示する）。"""
    make_plan(tmp_path, "本", [])
    mon, calls = make_monitor(tmp_path, {"本": 20}, "change")
    mon.tick()
    assert calls == [("change", "本", 20)] and mon.info()["waiting"] == []
    restarted, calls2 = make_monitor(tmp_path, {"本": 20}, "change")
    restarted.tick()
    assert calls2 == [] and restarted.info()["waiting"] == ["本"]
    assert "返事を待っています" in restarted.answer("本")["message"]


def test_interrupt_stops_claude_and_the_monitor_leaves_the_book_alone(tmp_path, monkeypatch):
    import monitor

    killed = []
    monkeypatch.setattr(monitor, "kill_tree", lambda proc: killed.append(proc) or setattr(proc, "alive", False))
    plan = make_plan(tmp_path, "本", [])
    mon, calls = make_monitor(tmp_path, {"本": 20})
    mon.tick()
    assert mon.interrupt(plan) == "work" and len(killed) == 1
    assert monitor.stopped_stage(plan.parent) == "work"
    calls.clear()
    mon.tick()
    assert calls == []  # 中断の印があるあいだは、起動し直さない
    assert mon.answer("本")["problems"] == ["中断しています。続けるときは「再開」を押してください"]


def test_resume_of_an_applied_book_starts_claude_again_even_without_a_mark(tmp_path):
    import monitor

    plan = make_plan(tmp_path, "本", ["p1-9"])
    mon, calls = make_monitor(tmp_path, {"本": 20})
    assert mon.resume(plan, 20)["ok"] and calls == [("launch", "本", 20)]  # 途中で止まった（印なし）ものも再開できる
    try:
        mon.resume(plan, 20)
        raise AssertionError("二重に起動した")
    except ValueError as e:
        assert "すでに動いています" in str(e)
    monitor.mark_stopped(plan.parent, "work")
    mon.running[plan].alive = False
    other = make_plan(tmp_path, "別", ["p1-9"])
    mon.running[other] = FakeProc()  # ほかの本・号が動いている
    try:
        mon.resume(plan, 20)
        raise AssertionError("同時に2本動いた")
    except ValueError as e:
        assert "ほかの本・号" in str(e)
    assert monitor.stopped_stage(plan.parent) == "work"  # 断ったときは、印を残す


def test_resume_of_an_interrupted_change_review_hands_it_over_again(tmp_path):
    import monitor

    plan = make_plan(tmp_path, "本", [])
    (plan.parent / "claude-change.hash").write_text("古い", encoding="utf-8")
    monitor.mark_stopped(plan.parent, "change")
    mon, calls = make_monitor(tmp_path, {"本": 20}, "change")
    mon.resume(plan, 20)
    assert not (plan.parent / monitor.STOP_MARK).exists() and calls == [("change", "本", 20)]
