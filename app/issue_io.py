"""質問の Issue を、画面（`web.py`）から読み書きするための部品。Issue が正で、画面は答えを手元に持たない。

- コメントの書き手の区別: 先頭が `<!-- claude -->` なら Claude、ほかの `<!--` で始まるものは自動投稿、それ以外は人
- 回答フォーム: Issue の本文から、見出しとチェックボックスを取り出す。保存するときは、人が変えたチェックだけを書き戻す
- 二重に答えたとき: フォームを開いた時点の本文（の版）と、保存の直前の本文が違えば、書かずに Conflict にする
  （後勝ちで上書きしない）
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess

CLAUDE_MARK = "<!-- claude -->"
CHECKBOX = re.compile(r"^- \[([ xX])\] (.*)$")
CHILD = re.compile(r"^\s+- (.*)$")  # 合体した記事に含まれる章（チェックボックスの下の、インデントした箇条書き）
MAX_COMMENT = 4000


class Conflict(ValueError):
    """フォームを開いたあとに、Issue の本文が変わった"""


def who(body: str) -> str:
    """コメントの書き手: claude / auto（自動投稿）/ human"""
    head = body.lstrip()
    if head.startswith(CLAUDE_MARK):
        return "claude"
    return "auto" if head.startswith("<!--") else "human"


def version(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _gh(args: list[str], stdin: str | None = None) -> str:
    return subprocess.run(
        ["gh", *args], input=stdin, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60
    ).stdout


def view(number: int) -> dict:
    """Issue の本文・コメント・URL。"""
    return json.loads(_gh(["issue", "view", str(number), "--json", "body,comments,url"]))


def post_comment(number: int, body: str) -> None:
    """人の返事を投稿する。本文は引数でなく標準入力で渡す。"""
    _gh(["issue", "comment", str(number), "--body-file", "-"], stdin=body)


def edit_body(number: int, body: str) -> None:
    _gh(["issue", "edit", str(number), "--body-file", "-"], stdin=body)


def close_issue(number: int, comment: str) -> None:
    _gh(["issue", "close", str(number), "--comment", comment])


def thread(comments: list[dict]) -> list[dict]:
    """画面に出すやりとり（人と Claude のコメント）。自動投稿（反映・参考文献）は出さない。"""
    out = []
    for c in comments:
        kind = who(c.get("body", ""))
        if kind == "auto":
            continue
        text = c["body"].lstrip()
        text = text[len(CLAUDE_MARK) :].lstrip() if kind == "claude" else text.strip()
        out.append({"who": kind, "created_at": c.get("createdAt", ""), "body": text})
    return out


def form(body: str) -> list[dict]:
    """回答フォームの項目。見出し（チェックボックスを含むものだけ）・チェックボックス・含まれる章を、本文の順に。"""
    items: list[dict] = []
    pending: list[dict] = []  # まだチェックボックスが出てきていない見出し
    after_check = False
    for i, raw in enumerate(body.splitlines()):
        line = raw.rstrip()
        if line.startswith(("## ", "### ")):
            kind = "h2" if line.startswith("## ") else "h3"
            # 大見出しは、それまでの未出力の見出しを捨てる。小見出しは、未出力の大見出しだけ残す
            kept = [p for p in pending if p["kind"] == "h2"] if kind == "h3" else []
            pending = [*kept, {"kind": kind, "text": line.lstrip("#").strip()}]
            after_check = False
            continue
        m = CHECKBOX.match(line)
        if m:
            items += pending
            pending = []
            items.append({"kind": "check", "line": i, "text": m.group(2), "checked": m.group(1) != " "})
            after_check = True
            continue
        c = CHILD.match(raw)
        if c and after_check:
            items.append({"kind": "child", "text": c.group(1).strip()})
            continue
        if line.strip():
            after_check = False
    return items


def toggle(body: str, changes: list[dict]) -> str:
    """指定した行のチェックだけを切り替える。行の文字が違う（本文が変わった）ときは Conflict。"""
    lines = body.splitlines(keepends=True)
    for ch in changes:
        i = ch.get("line")
        if not isinstance(i, int) or not 0 <= i < len(lines):
            raise Conflict("回答フォームの行が見つかりません")
        end = lines[i][len(lines[i].rstrip("\r\n")) :]
        m = CHECKBOX.match(lines[i].rstrip("\r\n"))
        if not m or m.group(2) != ch.get("text"):
            raise Conflict("Issue の本文が変わっています")
        lines[i] = f"- [{'x' if ch.get('checked') else ' '}] {m.group(2)}{end}"
    return "".join(lines)


def save_answers(number: int, base_version: str, changes: list[dict]) -> bool:
    """フォームで変えたチェックを Issue に書き戻す。変更が無ければ書かずに False。"""
    body = view(number)["body"]
    if version(body) != base_version:
        raise Conflict("フォームを開いたあとに、Issue 側で回答が変わりました")
    new = toggle(body, changes)
    if new == body:
        return False
    edit_body(number, new)
    return True


def check_comment(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("返事が空です")
    if len(text) > MAX_COMMENT:
        raise ValueError(f"返事が長すぎます（{MAX_COMMENT}字まで）")
    if who(text) != "human":
        raise ValueError("返事を <!-- で始めることはできません")  # 自動投稿や Claude と見分けがつかなくなる
    return text
