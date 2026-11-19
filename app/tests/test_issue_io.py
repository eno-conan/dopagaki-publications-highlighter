"""issue_io（画面から Issue を読み書きする部品）のテスト。gh は呼ばない。"""

from __future__ import annotations

import pytest

import ask_issue as ask
import issue_io
import read_answers as ra

PLAN = {
    "pdf": "book.pdf",
    "articles": [
        {"id": "p3-9", "title": "第1章 はじめの章", "first": 3, "last": 9},
        {"id": "p10-19", "title": "第2章 つぎの章", "first": 10, "last": 19},
    ],
}


def body(crlf: bool = False) -> str:
    text = ask.render_body(PLAN, "本", purpose="実務に使う", recommend=["p3-9"], emphasis=[])
    return text.replace("\n", "\r\n") if crlf else text


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("<!-- claude -->\nどれにしますか？", "claude"),
        ("  <!-- claude --> 確認です", "claude"),
        ("<!-- applied -->\n反映しました", "auto"),
        ("<!-- references:p3-9 -->\n## 参考", "auto"),
        ("1で", "human"),
    ],
)
def test_who_tells_claude_auto_and_human_apart(text, kind):
    assert issue_io.who(text) == kind


def test_thread_hides_automatic_comments_and_strips_the_claude_mark():
    comments = [
        {"body": "<!-- claude -->\nA と B のどちらですか？", "createdAt": "2026-11-18T10:00:00Z"},
        {"body": "<!-- applied -->\n反映しました", "createdAt": "2026-11-18T10:01:00Z"},
        {"body": " A で \n", "createdAt": "2026-11-18T10:02:00Z"},
    ]
    assert issue_io.thread(comments) == [
        {"who": "claude", "created_at": "2026-11-18T10:00:00Z", "body": "A と B のどちらですか？"},
        {"who": "human", "created_at": "2026-11-18T10:02:00Z", "body": "A で"},
    ]


def test_claude_comments_are_not_read_as_human_notes(monkeypatch):
    comments = [{"body": "<!-- claude -->\n確認です"}, {"body": "2章は読み飛ばす"}]
    monkeypatch.setattr(
        ra.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"stdout": __import__("json").dumps({"body": "x", "comments": comments})})(),
    )
    assert ra.fetch_issue(1) == ("x", "2章は読み飛ばす")


def test_form_lists_headings_checkboxes_and_children_in_order():
    items = issue_io.form(body())
    kinds = [i["kind"] for i in items]
    texts = [i["text"] for i in items if i["kind"] in ("h2", "h3")]
    assert texts == [
        "1. 分け方と対象",
        "2. 読み方",
        "目的（1つ）",
        "重点にする章（複数可）",
        "使う色（1つ）",
        "4. 作業開始",
    ]
    assert "3. その他" not in texts  # チェックボックスの無い見出しは出さない
    checks = [i for i in items if i["kind"] == "check"]
    assert checks[0]["checked"] and checks[0]["text"].startswith("★ 第1章")  # ★ は初期チェック済み
    assert not checks[1]["checked"]
    assert checks[-1]["text"] == ask.START and kinds[0] == "h2"
    lines = body().splitlines()
    assert all(lines[c["line"]].endswith(c["text"]) for c in checks)  # 行番号が本文と合っている


@pytest.mark.parametrize("crlf", [False, True])
def test_toggle_changes_only_the_given_lines(crlf):
    b = body(crlf)
    checks = [i for i in issue_io.form(b) if i["kind"] == "check"]
    start = checks[-1]
    new = issue_io.toggle(b, [{"line": start["line"], "text": start["text"], "checked": True}])
    old_lines, new_lines = b.splitlines(keepends=True), new.splitlines(keepends=True)
    diff = [i for i, (x, y) in enumerate(zip(old_lines, new_lines, strict=True)) if x != y]
    assert diff == [start["line"]] and new_lines[start["line"]].startswith("- [x] ")
    assert ra.parse_body(new).start
    assert new_lines[start["line"]].endswith("\r\n" if crlf else "\n")


def test_toggle_refuses_when_the_line_text_differs():
    b = body()
    line = next(i for i in issue_io.form(b) if i["kind"] == "check")["line"]
    with pytest.raises(issue_io.Conflict):
        issue_io.toggle(b, [{"line": line, "text": "別の行", "checked": False}])
    with pytest.raises(issue_io.Conflict):
        issue_io.toggle(b, [{"line": 9999, "text": "x", "checked": True}])


def test_save_answers_does_not_overwrite_when_the_issue_changed(monkeypatch):
    b = body()
    edits = []
    monkeypatch.setattr(issue_io, "view", lambda n: {"body": b})
    monkeypatch.setattr(issue_io, "edit_body", lambda n, text: edits.append(text))
    start = [i for i in issue_io.form(b) if i["kind"] == "check"][-1]
    change = [{"line": start["line"], "text": start["text"], "checked": True}]
    with pytest.raises(issue_io.Conflict):
        issue_io.save_answers(1, "古い版", change)
    assert edits == []
    assert issue_io.save_answers(1, issue_io.version(b), []) is False and edits == []  # 変更が無ければ書かない
    assert issue_io.save_answers(1, issue_io.version(b), change) is True and ra.parse_body(edits[0]).start


@pytest.mark.parametrize(
    ("text", "err"), [(" ", "空"), ("あ" * 4001, "長すぎ"), ("<!-- claude --> なりすまし", "<!--")]
)
def test_check_comment_rejects_empty_long_and_marked_replies(text, err):
    with pytest.raises(ValueError, match=err):
        issue_io.check_comment(text)
    assert issue_io.check_comment(" 1で \n") == "1で"
