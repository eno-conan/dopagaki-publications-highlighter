"""activity（Claude のログから、いま何をしているかを取り出す）のテスト。"""

from __future__ import annotations

import json

from activity import describe_tool, latest_activity


def event(*parts):
    return json.dumps({"type": "assistant", "message": {"content": list(parts)}}, ensure_ascii=False)


def test_latest_tool_use_is_returned(tmp_path):
    log = tmp_path / "claude-run.log"
    log.write_text(
        "\n".join(
            [
                event({"type": "text", "text": "本文を読みます"}),
                event({"type": "tool_use", "name": "Read", "input": {"file_path": "C:/x/work-gai/ch1.txt"}}),
                json.dumps({"type": "user"}),
            ]
        ),
        encoding="utf-8",
    )
    assert latest_activity(log) == "ch1.txt を読んでいる"


def test_text_only_and_unreadable_logs(tmp_path):
    log = tmp_path / "a.log"
    log.write_text("途中の行\n" + event({"type": "text", "text": "意図を読み取ります"}), encoding="utf-8")
    assert latest_activity(log) == "考えている: 意図を読み取ります"
    assert latest_activity(tmp_path / "無い.log") == ""


def test_describe_tool():
    assert describe_tool("Bash", {"command": "uv run python pipeline.py"}).startswith("コマンドを実行: uv run")
    assert describe_tool("Foo", {}) == "Foo"
