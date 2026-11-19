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
    "Bash(uv run --directory app python *)",
    "Bash(gh issue *)",
    "Bash(gh api *)",
    "Bash(git status*)",
    "Bash(git diff*)",
    "Bash(git log*)",
    "Bash(git show*)",
    "Bash(git ls-tree*)",
    "Bash(git add *)",
    "Bash(git commit *)",
    "Bash(git push*)",
)

PROMPT_HEAD = """\
取り込み確認の Issue #{issue} に回答が付き、「作業開始OK」がチェックされました。`{plan_rel}` と `reading.json` には、すでに反映してあります。
AGENTS.md と docs/workflow.md に従って、続きを進めてください。

"""

STEPS = """\
1. `{book_rel}` の対象の記事（`articles.json` の `target` が true）の本文を読み、`reading.json` の答えに沿って、重要箇所を `highlights/<ID>.json` に選ぶ
   （docs/highlight-criteria.md を読む。`apply_highlights.py --dry-run` で一致を確認する）
2. 記事ごとに参考文献・関連リンクの候補を `references/<ID>.json` に書く（有益な順。docs/workflow.md の「参考文献を集める」）
3. `uv run --directory app python pipeline.py --plan ../{plan_rel} --issue {issue_refs} --close` を実行する（問題が無ければ、Issue が閉じる。マーカーの未適用や投稿の失敗があれば閉じない）
4. 未適用のマーカーや、載せられなかったリンクがあれば直す
5. docs/records.md の実績の表に行を足し、`uv run --directory app python -m pytest` と `uv run --directory app python -m ruff check .` を通して、コミット・プッシュする
6. 最後に、仕上がりと「人が見ること」を、日本語で短く報告する

作業中に作る一時ファイル（本文の抜き出しや使い捨てのスクリプトなど）は、`work-gai/{book_name}/` に作る（.gitignore 済み。ほかの場所に作らない。手順3で Issue が閉じると、このフォルダは自動で消える）。
{comment_rule}
{bash_rule}
人の判断（分け方の承認・対象・読み方）は変えないこと。
"""

# Claude のコメントを、人のコメントと見分けるための印（画面の「やりとり」と、人の補足の読み取りで使う）
COMMENT_RULE = (
    "Issue にコメントを書くときは、本文の1行目を必ず `<!-- claude -->` だけにする"
    "（人のコメントと見分けるため。`gh issue comment <番号> --body-file <ファイル>` で、ファイルの1行目に書く）。"
)

# 無人の Claude は、許可に無い操作を断られると、そこで作業ごと終わる（承認を求める相手がいない）
BASH_RULE = (
    "Bash は、1回に1つのコマンドだけを実行する（`cd` や `&&`・`|`・`;` でつながない。許可されず、作業がそこで止まる）。"
    "`app/` のスクリプトは、リポジトリ直下から `uv run --directory app python <スクリプト> ...` で動かす"
    "（引数のパスは `app/` からの相対。本文の抜き出しなどの使い捨てスクリプトは、上の一時フォルダに置き、"
    "`uv run --directory app python ../work-gai/<本・号の名前>/<スクリプト>.py` で動かす）。ファイルの中身は Read で読む（cat・head は使わない）。"
)

PROMPT = PROMPT_HEAD + STEPS

CHANGE_PROMPT = (
    """\
取り込み確認の Issue #{issue}（`{plan_rel}`）で、人が「分け方を変えたい」にチェックを付けました。AGENTS.md と docs/workflow.md を読んでから、意図をくみ取ってください。

`gh issue view {issue} --comments` で、Issue の本文（チェックの状態）と、人のコメントをすべて読む。「分け方を変えたい」のチェックだけで決めず、
次の3つをあわせて判断する: (1)「1. 分け方と対象」でチェックした記事、(2) ほかの項目（目的・色・作業開始OK）の状態、(3) コメントの内容。

判断は3つに分かれる。

A. 分け方は今のままでよく、補足やメモを伝えたいだけ（例: 「この5つは同じPDFでOK」「2章の設定例は読み飛ばす」。章の合体・分割・範囲の変更を求めていない）
   → 回答が揃っているときだけ、次を実行する: `uv run --directory app python read_answers.py --plan ../{plan_rel} --issue {issue} --apply --ignore-change`
     （コメントは reading.json の note に入る）。Issue に「補足だけと読み取って、このまま進めます」とコメントしてから、下の「続きの手順」を進める。
     回答が足りないときは、足りない項目を Issue にコメントして終える（B と同じ扱い）。
B. 意図があいまい、または回答が足りない
   → 勝手に決めない。どう読み取ったかと、確認したいこと（選択式で2〜3個）を Issue にコメントして、終える（`split.approved` も `target` も書かない）。
     人は、画面の「やりとり」欄からも返事を書く。番号や記号で答えられる聞き方にする。
C. 章の合体・分割・ページ範囲を、はっきり変えたい
   → `plan_issue.py` で分割案を直し（書籍は `--ranges` などで。`split.approved` は書かない）、直した一覧（ID・ページ範囲・ページ数・章名）を Issue にコメントして、
     古い Issue を閉じ、`ask_issue.py --create` で質問の Issue を作り直す。番号とリンクを報告して終える（重要箇所の選定は始めない）。

分け方の承認と `target` は人の判断。人の言葉から意図が読み取れないときは、B にする。
{comment_rule}
{bash_rule}

【A のときの続きの手順】
"""
    + STEPS
)


def build_change_prompt(plan: Path, issue: int, issue_refs: int, root: Path) -> str:
    plan_rel = plan.resolve().relative_to(root).as_posix()
    return CHANGE_PROMPT.format(
        issue=issue,
        plan_rel=plan_rel,
        book_rel=Path(plan_rel).parent.as_posix(),
        issue_refs=issue_refs,
        comment_rule=COMMENT_RULE,
        book_name=Path(plan_rel).parent.name,
        bash_rule=BASH_RULE,
    )


def build_prompt(plan: Path, issue: int, issue_refs: int, root: Path) -> str:
    plan_rel = plan.resolve().relative_to(root).as_posix()
    return PROMPT.format(
        issue=issue,
        plan_rel=plan_rel,
        book_rel=Path(plan_rel).parent.as_posix(),
        issue_refs=issue_refs,
        comment_rule=COMMENT_RULE,
        book_name=Path(plan_rel).parent.name,
        bash_rule=BASH_RULE,
    )


def claude_command(prompt: str) -> list[str]:
    # stream-json: 経過をログに1行ずつ残す（画面の「いま何をしているか」に使う。最後の `result` 行が最終報告）
    return [
        "claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
        "--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED_TOOLS,
    ]  # fmt: skip


def launch_claude(plan: Path, issue: int, issue_refs: int | None = None) -> subprocess.Popen:
    """続きを進める Claude を、裏で起動する（終わるのを待たない）。経過は <作業フォルダ>/claude-run.log。"""
    root = Path(__file__).resolve().parent.parent
    cmd = claude_command(build_prompt(plan, issue, issue_refs or issue, root))
    log = plan.parent / "claude-run.log"
    with log.open("w", encoding="utf-8") as f:
        return subprocess.Popen(cmd, cwd=root, stdout=f, stderr=subprocess.STDOUT, text=True, encoding="utf-8")


def launch_change_review(plan: Path, issue: int, issue_refs: int | None = None) -> subprocess.Popen:
    """「分け方を変えたい」の意図を、Claude に読み取らせる。経過は <作業フォルダ>/claude-change.log。"""
    root = Path(__file__).resolve().parent.parent
    cmd = claude_command(build_change_prompt(plan, issue, issue_refs or issue, root))
    log = plan.parent / "claude-change.log"
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
