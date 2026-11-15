"""start（ダブルクリックの入口）のテスト。Claude も gh も起動しない。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import start


def make_plan(output: Path, name: str, approved: list[str] | None) -> Path:
    plan = output / name / "articles.json"
    plan.parent.mkdir(parents=True)
    data: dict = {"pdf": f"{name}.pdf", "articles": []}
    if approved is not None:
        data["split"] = {"unit": "book", "approved": approved}
    plan.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return plan


def test_inbox_pdfs_ignores_other_files(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / ".gitkeep").write_bytes(b"")
    (tmp_path / "メモ.txt").write_text("x", encoding="utf-8")
    assert [p.name for p in start.inbox_pdfs(tmp_path)] == ["a.pdf"]


def test_move_to_output_moves_into_pdf_named_folder_and_never_overwrites(tmp_path):
    inbox, output = tmp_path / "inbox", tmp_path / "output"
    inbox.mkdir()
    pdf = inbox / "サンプルの本.pdf"
    pdf.write_bytes(b"abc")
    dest = start.move_to_output(pdf, output)
    assert dest == output / "サンプルの本" / "サンプルの本.pdf" and dest.read_bytes() == b"abc" and not pdf.exists()
    pdf.write_bytes(b"new")
    with pytest.raises(ValueError, match="上書きしません"):
        start.move_to_output(pdf, output)
    assert pdf.read_bytes() == b"new"  # 失敗したら、inbox の PDF はそのまま


def test_pending_books_are_open_issues_not_yet_applied(tmp_path):
    waiting = make_plan(tmp_path, "待ち", [])  # 承認が空 = まだ反映していない
    make_plan(tmp_path, "反映済み", ["p1-9"])
    make_plan(tmp_path, "Issueなし", [])
    make_plan(tmp_path, "split無し", None)
    issues = {"待ち": 20, "反映済み": 21, "split無し": 22, "計画なし": 23}
    assert start.pending_books(issues, tmp_path) == [
        (tmp_path / "split無し" / "articles.json", 22),
        (waiting, 20),
    ]  # 名前順


def test_plan_command_is_limited_and_names_the_issue_after_the_folder():
    cmd = start.plan_command("本")
    assert cmd[:2] == ["claude", "-p"] and "output/本/本.pdf" in cmd[2] and "取り込み確認: 本" in cmd[2]
    tools = cmd[cmd.index("--allowedTools") + 1 :]
    assert "Bash(uv run python *)" in tools and not any(t in ("Bash", "Bash(*)") for t in tools)


def test_watch_command_quotes_paths_with_japanese_and_spaces():
    text = start.watch_command(Path("C:/a b/要件/articles.json"), 20)
    assert 'watch.py --plan "C:' in text and "--issue 20" in text and text.endswith("& pause")
