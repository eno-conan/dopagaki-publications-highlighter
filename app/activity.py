"""Claude（`claude -p --output-format stream-json`）のログから、「いま何をしているか」を1行で取り出す。

画面の表示用。
"""

from __future__ import annotations

import json
from pathlib import Path

TAIL_BYTES = 128 * 1024


def _short(text: str, n: int = 70) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe_tool(name: str, args: dict) -> str:
    """ツール呼び出しを、人が読める短い説明にする。"""
    path = args.get("file_path") or args.get("path")
    if name in ("Read", "Edit", "Write") and path:
        verb = {"Read": "読んでいる", "Edit": "編集している", "Write": "書いている"}[name]
        return f"{Path(str(path)).name} を{verb}"
    if name == "Bash":
        return f"コマンドを実行: {_short(args.get('command', ''))}"
    if name in ("Grep", "Glob"):
        return f"検索: {_short(args.get('pattern', ''))}"
    if name == "WebSearch":
        return f"Web検索: {_short(args.get('query', ''))}"
    if name == "WebFetch":
        return f"ページを取得: {_short(args.get('url', ''))}"
    return name


def latest_activity(log: Path) -> str:
    """ログの終わりのほうから、いちばん新しい操作（なければ発言）を返す。読めなければ空。"""
    try:
        size = log.stat().st_size
        with log.open("rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        for part in reversed(event.get("message", {}).get("content", [])):
            if part.get("type") == "tool_use":
                return describe_tool(part.get("name", ""), part.get("input", {}))
            if part.get("type") == "text" and part.get("text", "").strip():
                return f"考えている: {_short(part['text'])}"
    return ""
