import subprocess

import pytest

import ask_issue
import pipeline
import post_references
import read_answers
import repo_guard
import start
import watch


def public(monkeypatch):
    monkeypatch.setattr(repo_guard, "repo_info", lambda: ("me/public-repo", "PUBLIC"))


def test_public_repo_is_refused(monkeypatch):
    public(monkeypatch)
    with pytest.raises(repo_guard.PublicRepoError, match="me/public-repo"):
        repo_guard.require_private()


def test_private_and_unknown_are_allowed(monkeypatch):
    repo_guard.require_private()  # conftest: PRIVATE
    monkeypatch.setattr(repo_guard, "repo_info", lambda: None)  # gh が使えない
    repo_guard.require_private()
    monkeypatch.setattr(repo_guard, "repo_info", lambda: ("me/x", "INTERNAL"))
    repo_guard.require_private()


def test_allow_public_flag_sets_env_and_passes(monkeypatch):
    public(monkeypatch)
    repo_guard.require_private(allow_public=True)
    assert repo_guard.ENV_ALLOW in __import__("os").environ
    repo_guard.require_private()  # 環境変数が引き継がれて、続く呼び出しも通る


def test_env_var_allows(monkeypatch):
    public(monkeypatch)
    monkeypatch.setenv(repo_guard.ENV_ALLOW, "1")
    repo_guard.require_private()


def test_repo_info_parses_gh_output(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout='{"nameWithOwner":"a/b","visibility":"public"}')

    monkeypatch.undo()  # conftest の差し替えを戻して、本物の repo_info を試す
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert repo_guard.repo_info() == ("a/b", "PUBLIC")


def test_repo_info_returns_none_when_gh_missing(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("gh")

    monkeypatch.undo()
    monkeypatch.setattr(subprocess, "run", boom)
    assert repo_guard.repo_info() is None


PLAN = (
    '{"articles": [{"id": "p1-2", "title": "第1章", "first": 1, "last": 2,'
    ' "chars": 500, "readable": "ok", "target": true}]}'
)


def test_ask_issue_create_refuses_on_public(monkeypatch, tmp_path, capsys):
    public(monkeypatch)
    plan = tmp_path / "articles.json"
    plan.write_text(PLAN, encoding="utf-8")
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    assert ask_issue.main(["--plan", str(plan), "--title", "t", "--create"]) == 1
    assert "公開" in capsys.readouterr().err
    assert called == []  # gh issue create は呼ばれない


def test_ask_issue_preview_does_not_check(monkeypatch, tmp_path, capsys):
    public(monkeypatch)
    plan = tmp_path / "articles.json"
    plan.write_text(PLAN, encoding="utf-8")
    assert ask_issue.main(["--plan", str(plan), "--title", "t"]) == 0  # 本文を表示するだけなら、止めない


def test_pipeline_with_issue_refuses_on_public(monkeypatch, tmp_path, capsys):
    public(monkeypatch)
    assert pipeline.main(["--plan", str(tmp_path / "articles.json"), "--issue", "5"]) == 1
    assert "公開" in capsys.readouterr().err


def test_watch_refuses_on_public(monkeypatch, tmp_path, capsys):
    public(monkeypatch)
    assert watch.main(["--plan", str(tmp_path / "articles.json"), "--issue", "5"]) == 1
    assert "公開" in capsys.readouterr().err


def test_start_refuses_on_public_before_moving_pdf(monkeypatch, tmp_path, capsys):
    public(monkeypatch)
    moved = []
    monkeypatch.setattr(start, "move_to_output", lambda pdf: moved.append(pdf))
    assert start.main([]) == 1
    assert moved == []


def test_start_dry_run_does_not_check(monkeypatch, capsys):
    public(monkeypatch)
    monkeypatch.setattr(start, "inbox_pdfs", lambda: [])
    monkeypatch.setattr(start, "open_issues", lambda: {})
    assert start.main(["--dry-run"]) == 0


def test_read_answers_apply_refuses_on_public(monkeypatch, tmp_path, capsys):
    public(monkeypatch)
    plan = tmp_path / "articles.json"
    plan.write_text(PLAN, encoding="utf-8")
    assert read_answers.main(["--plan", str(plan), "--issue", "5", "--apply"]) == 1
    assert "公開" in capsys.readouterr().err


def test_post_references_post_refuses_on_public(monkeypatch, tmp_path, capsys):
    public(monkeypatch)
    refs = tmp_path / "p1-2.json"
    refs.write_text(
        '{"title": "t", "references": [{"url": "https://e.com", "title": "x", "status": "ok", "summary": "s"}]}',
        encoding="utf-8",
    )
    assert post_references.main(["--refs", str(refs), "--issue", "5", "--post"]) == 1
    assert "公開" in capsys.readouterr().err
