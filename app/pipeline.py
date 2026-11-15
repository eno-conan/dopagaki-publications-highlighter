"""決まった作業を、続けて1回で行う（切り出し・ハイライト → 参考リンクの確認 → Issue のコメント）。

    uv run python pipeline.py --plan ../output/<書名>/articles.json --issue 19

前提: 重要箇所 `highlights/<ID>.json` と参考文献 `references/<ID>.json` を、先に書いておく（本文を読んで選ぶ部分）。
ここでは、機械的にできる部分だけを順に行う。

1. `build_issue.py`: 対象の記事を切り出して、マーカーを付ける
2. `check_links.py`: `references/*.json` のリンクを取得して確認する
3. `post_references.py --sync`: 確認できたリンクだけを、章ごとに Issue へ投稿する（すでにあれば書き換える）

どこかで失敗しても、あとの手順は続ける。最後に、人が見るべきこと（マーカーの未適用、載せられなかったリンク）をまとめて表示する。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import build_issue
import check_links
import post_references
import repo_guard


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="切り出し・ハイライト・リンク確認・コメント投稿を、続けて行う")
    p.add_argument("--plan", type=Path, required=True, help="articles.json")
    p.add_argument("--issue", type=int, help="参考文献を投稿する Issue の番号（省略時は投稿しない）")
    p.add_argument("--close", action="store_true", help="マーカーも投稿も問題なく終わったら、--issue の Issue を閉じる")
    p.add_argument("--allow-public", action="store_true", help="書き込み先が公開リポジトリでも止めない（既定は止める）")
    args = p.parse_args(argv)
    if args.issue is not None:
        try:
            repo_guard.require_private(args.allow_public)
        except repo_guard.PublicRepoError as e:
            print(f"エラー: {e}", file=sys.stderr)
            return 1

    todo: list[str] = []
    failed = False  # Issue を閉じてよいか（マーカーの未適用・投稿の失敗があれば閉じない）
    print("== 1. 切り出し・ハイライト")
    if build_issue.main(["--plan", str(args.plan)]) != 0:
        todo.append("ハイライトの未適用か、エラーがあります（上の表示を見てください）")
        failed = True

    refs = sorted((args.plan.parent / "references").glob("*.json"))
    print(f"\n== 2. 参考リンクの確認（{len(refs)}ファイル）")
    for path in refs:
        print(f"-- {path.name}")
        if check_links.main(["--refs", str(path)]) != 0:
            todo.append(f"{path.name}: 載せられないリンクがあります（not_found・login・blocked など）")

    print("\n== 3. Issue への投稿")
    if args.issue is None:
        print("--issue が無いので、投稿しません")
    else:
        for path in refs:
            if post_references.main(["--refs", str(path), "--issue", str(args.issue), "--sync"]) != 0:
                todo.append(f"{path.name}: 投稿できませんでした")
                failed = True

    if args.close and args.issue is not None:
        if failed or not refs:
            why = "参考文献がまだありません" if not refs else "マーカーか投稿に問題があります"
            print(f"\n#{args.issue} は閉じません（{why}）")
        else:
            subprocess.run(["gh", "issue", "close", str(args.issue)], check=True, stdout=subprocess.DEVNULL)
            print(f"\n#{args.issue} を閉じました（マーカーと参考文献の作業が終わったため）")

    print("\n== 人が見ること")
    for line in todo or ["なし"]:
        print(f"- {line}")
    return 1 if todo else 0


if __name__ == "__main__":
    sys.exit(main())
