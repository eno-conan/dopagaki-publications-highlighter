"""watch（Claude を起動する見張り）のテスト。Claude は起動しない。"""

from __future__ import annotations

from pathlib import Path

import watch


def test_prompt_points_to_the_book_and_issues():
    root = Path(__file__).resolve().parents[2]
    plan = root / "output" / "本" / "articles.json"
    text = watch.build_prompt(plan, 20, 21, root)
    assert "output/本/articles.json" in text and "#20" in text
    assert "pipeline.py --plan ../output/本/articles.json --issue 21" in text


def test_claude_is_started_with_limited_permissions():
    cmd = watch.claude_command("p")
    assert cmd[:3] == ["claude", "-p", "p"]
    assert "acceptEdits" in cmd and "--dangerously-skip-permissions" not in cmd
    tools = cmd[cmd.index("--allowedTools") + 1 :]
    assert "Bash(uv run python *)" in tools and "Bash(gh issue *)" in tools
    assert not any(t in ("Bash", "Bash(*)") for t in tools)  # 任意のコマンドは許さない


def test_claude_is_not_started_when_answers_are_not_ready(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(watch.read_answers, "main", lambda argv: 3)
    started = []
    monkeypatch.setattr(watch.subprocess, "run", lambda *a, **k: started.append(a))
    assert watch.main(["--plan", str(tmp_path / "articles.json"), "--issue", "1"]) == 3
    assert started == []
