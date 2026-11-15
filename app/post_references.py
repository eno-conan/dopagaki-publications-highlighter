"""章・記事ごとの参考文献JSONを、Issue のコメントとして投稿する。

    uv run python post_references.py --refs ../output/<書名>/references/p11-64.json            # 本文を表示するだけ
    uv run python post_references.py --refs ../output/<書名>/references/p11-64.json --issue 19 --post

載せるのは `status` が `ok` のリンクだけ（`check_links.py` で確認したもの）。それ以外は載せず、理由を表示する。
並びは JSON の配列の順のまま（先頭ほど、見る価値が高いもの）。
1つの章（記事）につきコメント1つ。同じ章のコメントが Issue にすでにあるときは、重複して投稿しない。
JSON が正で、Issue は表示先。直したときは `--update` で、すでにあるコメントを書き換える。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import repo_guard
from check_links import load_refs

KINDS = {
    "official": "公式",
    "paper": "論文",
    "article": "記事",
    "book": "書籍",
    "tool": "ツール",
    "video": "動画",
    "course": "講座",
    "site": "サイト",
}


def marker(ref_id: str) -> str:
    return f"<!-- references:{ref_id} -->"


def render_comment(ref_id: str, data: dict) -> tuple[str, list[dict]]:
    """コメント本文と、載せなかったリンクを返す。"""
    ok = [r for r in data["references"] if r.get("status") == "ok"]
    skipped = [r for r in data["references"] if r.get("status") != "ok"]
    title = data.get("title") or ref_id
    lines = [marker(ref_id), f"## 参考文献・関連リンク: {title}", ""]
    for r in ok:
        kind = KINDS.get(r.get("kind", ""), "")
        head = f"- [{r['title']}]({r['url']})" + (f"（{kind}）" if kind else "")
        lines.append(head + (f" — {r['summary']}" if r.get("summary") else ""))
    return "\n".join(lines) + "\n", skipped


def find_comment_id(issue: int, ref_id: str) -> int | None:
    """目印のあるコメントの id を返す（無ければ None）。"""
    out = subprocess.run(
        ["gh", "api", f"repos/{{owner}}/{{repo}}/issues/{issue}/comments", "--paginate"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    # --paginate は複数ページの JSON 配列をつなげて返すので、1つずつ読む
    decoder, text, i = json.JSONDecoder(), out.stdout, 0
    while i < len(text):
        page, i = decoder.raw_decode(text, i)
        for c in page:
            if marker(ref_id) in c["body"]:
                return c["id"]
        while i < len(text) and text[i].isspace():
            i += 1
    return None


def existing_markers(issue: int) -> str:
    out = subprocess.run(
        ["gh", "issue", "view", str(issue), "--json", "comments", "-q", ".comments[].body"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return out.stdout


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="参考文献JSONを Issue のコメントにする（既定は表示だけ）")
    p.add_argument("--refs", type=Path, required=True, help="references/<ID>.json")
    p.add_argument("--issue", type=int, help="投稿先の Issue 番号（読み方の Issue）")
    p.add_argument("--post", action="store_true", help="実際に投稿する（--issue が要る）")
    p.add_argument("--update", action="store_true", help="すでにあるコメントを書き換える（--issue が要る）")
    p.add_argument("--sync", action="store_true", help="コメントがあれば書き換え、無ければ投稿する（--issue が要る）")
    p.add_argument("--allow-public", action="store_true", help="書き込み先が公開リポジトリでも止めない（既定は止める）")
    args = p.parse_args(argv)
    try:
        data = load_refs(args.refs)
        body, skipped = render_comment(args.refs.stem, data)
        if all(r.get("status") != "ok" for r in data["references"]):
            raise ValueError("載せられるリンク（status が ok）がありません。check_links.py を実行してください")
        for r in skipped:
            print(f"載せない: {r.get('status', '未確認')}  {r['title']}  {r['url']}", file=sys.stderr)
        if not (args.post or args.update or args.sync):
            print(body)
            return 0
        if not args.issue:
            raise ValueError("--post / --update / --sync には --issue が要ります")
        repo_guard.require_private(args.allow_public)
        cid = find_comment_id(args.issue, args.refs.stem) if (args.update or args.sync) else None
        if args.update or (args.sync and cid is not None):
            if cid is None:
                raise ValueError(
                    f"#{args.issue} に {args.refs.stem} のコメントがありません（--post で投稿してください）"
                )
            subprocess.run(
                ["gh", "api", "-X", "PATCH", f"repos/{{owner}}/{{repo}}/issues/comments/{cid}", "--input", "-"],
                input=json.dumps({"body": body}),
                text=True,
                encoding="utf-8",
                check=True,
                stdout=subprocess.DEVNULL,
            )
            print(f"#{args.issue} の {args.refs.stem} のコメントを更新しました")
            return 0
        if marker(args.refs.stem) in existing_markers(args.issue):
            raise ValueError(f"#{args.issue} には {args.refs.stem} のコメントがすでにあります（重複して投稿しません）")
        subprocess.run(
            ["gh", "issue", "comment", str(args.issue), "--body-file", "-"],
            input=body,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (ValueError, OSError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(f"#{args.issue} に {args.refs.stem} のコメントを投稿しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
