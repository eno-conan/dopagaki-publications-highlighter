# ruff: noqa: E501  （docstring と、Claude に渡す日本語のプロンプトは、行が長くなる）
"""取り込み確認の Issue を見張り、「作業開始OK」が付いたら、反映して、Claude を起動して続きを進める。

    uv run python watch.py --plan ../output/<書名>/articles.json --issue 20 --issue-refs 20

1. `read_answers.py --apply --wait` で、回答が揃い、「作業開始OK」が付くまで待つ（揃ったら articles.json と reading.json に写す。Issue はまだ閉じない）
2. 続きを、ヘッドレスの Claude（`claude -p`）に任せる: 重要箇所の選定 → 参考文献の候補 → `pipeline.py`
   - 許可は、必要な操作だけに絞る（本文を読む・編集・Python の実行・gh の Issue 操作・git のコミット／プッシュ・Web検索）
   - 経過は `<作業フォルダ>/claude-run.log` に残る（コミットしない）

PC が起動していて、この見張りが動いている間だけ働く（ローカル限定）。セッションを開いている必要はない。
「分け方を変えたい」が選ばれたとき、回答が矛盾しているまま待ち時間が過ぎたときは、Claude を起動せずに終わる。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import read_answers
import repo_guard

# 無人で起動した Claude に許す操作（必要な分だけ）
ALLOWED_TOOLS = (
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "Bash(uv run python *)",
    "Bash(gh issue *)",
    "Bash(gh api *)",
    "Bash(git status*)",
    "Bash(git diff*)",
    "Bash(git add *)",
    "Bash(git commit *)",
    "Bash(git push*)",
)

PROMPT = """\
取り込み確認の Issue #{issue} に回答が付き、「作業開始OK」がチェックされました。`{plan_rel}` と `reading.json` には、すでに反映してあります。
AGENTS.md と docs/workflow.md に従って、続きを進めてください。

1. `{book_rel}` の対象の記事（`articles.json` の `target` が true）の本文を読み、`reading.json` の答えに沿って、重要箇所を `highlights/<ID>.json` に選ぶ
   （docs/highlight-criteria.md を読む。`apply_highlights.py --dry-run` で一致を確認する）
2. 記事ごとに参考文献・関連リンクの候補を `references/<ID>.json` に書く（有益な順。docs/workflow.md の「参考文献を集める」）
3. `app/` で `uv run python pipeline.py --plan ../{plan_rel} --issue {issue_refs} --close` を実行する（問題が無ければ、Issue が閉じる。マーカーの未適用や投稿の失敗があれば閉じない）
4. 未適用のマーカーや、載せられなかったリンクがあれば直す
5. docs/records.md の実績の表に行を足し、`uv run python -m pytest` と `uv run python -m ruff check .` を通して、コミット・プッシュする
6. 最後に、仕上がりと「人が見ること」を、日本語で短く報告する

作業中に作る一時ファイル（本文の抜き出しや使い捨てのスクリプトなど）は、リポジトリ直下の `work-gai/` に作る（.gitignore 済み。ほかの場所に作らない）。
人の判断（分け方の承認・対象・読み方）は変えないこと。
"""


def build_prompt(plan: Path, issue: int, issue_refs: int, root: Path) -> str:
    plan_rel = plan.resolve().relative_to(root).as_posix()
    return PROMPT.format(
        issue=issue, plan_rel=plan_rel, book_rel=Path(plan_rel).parent.as_posix(), issue_refs=issue_refs
    )


def claude_command(prompt: str) -> list[str]:
    return ["claude", "-p", prompt, "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS]


def launch_claude(plan: Path, issue: int, issue_refs: int | None = None) -> subprocess.Popen:
    """続きを進める Claude を、裏で起動する（終わるのを待たない）。経過は <作業フォルダ>/claude-run.log。"""
    root = Path(__file__).resolve().parent.parent
    cmd = claude_command(build_prompt(plan, issue, issue_refs or issue, root))
    log = plan.parent / "claude-run.log"
    with log.open("w", encoding="utf-8") as f:
        return subprocess.Popen(cmd, cwd=root, stdout=f, stderr=subprocess.STDOUT, text=True, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="「作業開始OK」を待って反映し、Claude を起動して続きを進める")
    p.add_argument("--plan", type=Path, required=True, help="articles.json")
    p.add_argument("--issue", type=int, required=True, help="取り込み確認の Issue の番号")
    p.add_argument("--issue-refs", type=int, help="参考文献を投稿する Issue の番号（省略時は --issue と同じ）")
    p.add_argument("--interval", type=int, default=120, help="確認間隔（秒）")
    p.add_argument("--timeout", type=int, default=24 * 3600, help="待つ最長の時間（秒）")
    p.add_argument("--dry-run", action="store_true", help="Claude を起動せず、コマンドを表示する")
    p.add_argument("--allow-public", action="store_true", help="書き込み先が公開リポジトリでも止めない（既定は止める）")
    args = p.parse_args(argv)
    try:
        repo_guard.require_private(args.allow_public)
    except repo_guard.PublicRepoError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    code = read_answers.main(
        [
            "--plan", str(args.plan), "--issue", str(args.issue), "--apply", "--wait",
            "--interval", str(args.interval), "--timeout", str(args.timeout),
        ]
    )  # fmt: skip
    if code != 0:
        print(f"回答が揃わなかった（終了コード {code}）ので、Claude は起動しません")
        return code

    root = Path(__file__).resolve().parent.parent
    prompt = build_prompt(args.plan, args.issue, args.issue_refs or args.issue, root)
    cmd = claude_command(prompt)
    if args.dry_run:
        print(" ".join(cmd[:2]), "…", " ".join(cmd[3:]))
        print(prompt)
        return 0
    log = args.plan.parent / "claude-run.log"
    print(f"Claude を起動します。経過: {log}")
    with log.open("w", encoding="utf-8") as f:
        return subprocess.run(cmd, cwd=root, stdout=f, stderr=subprocess.STDOUT, text=True, encoding="utf-8").returncode


if __name__ == "__main__":
    sys.exit(main())
