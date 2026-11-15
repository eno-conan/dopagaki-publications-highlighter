"""ダブルクリックで始める入口（リポジトリ直下の `作業開始.bat` から呼ばれる）。

    uv run python start.py              # 実行する
    uv run python start.py --dry-run    # 何をするかだけ表示する

やること:
1. `inbox/` の PDF を、`output/<PDF名>/` に移す（中身は書き換えない）
2. 移した PDF ごとに、許可を絞った Claude（`claude -p`）で、分割案・本文の把握・質問の Issue の作成まで進める
3. 回答待ち（質問の Issue が開いていて、まだ反映していない）の本・号ごとに、見張り（`watch.py`）を別ウィンドウで起動する
   - 「作業開始OK」が付くと、反映して、続き（重要箇所の選定〜参考文献〜 Issue を閉じる）まで自動で進む

PC が起動していて、見張りのウィンドウが開いている間だけ働く。ウィンドウを閉じると止まる（もう一度ダブルクリックすれば再開）。
"""

# ruff: noqa: E501  （Claude に渡す日本語のプロンプトは、行が長くなる）
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"
OUTPUT = ROOT / "output"
ISSUE_TITLE = "取り込み確認: "

# 分割案・質問の Issue まで進める Claude に許す操作
PLAN_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep", "Bash(uv run python *)", "Bash(gh issue *)")

PLAN_PROMPT = """\
`inbox/` に置かれた PDF を `output/{stem}/{stem}.pdf` に移してあります（中身は書き換えていません）。
AGENTS.md と docs/workflow.md の「自動で進める」の手順に従い、質問の Issue を作るところまで進めてください。

1. `app/` で `uv run python plan_issue.py --pdf ../output/{stem}/{stem}.pdf` で分割案を作る
   - 書籍（章に分かれた本）は `--unit book --auto-merge` を付ける。雑誌は付けない
   - しおりが無くて作れないときは、人に章名とページ範囲を聞く必要がある。Issue は作らず、その旨を報告して終了する
2. 対象の本文を読んで把握し、読み方の推奨（目的、重点にする章）を決める
3. `uv run python ask_issue.py --plan ../output/{stem}/articles.json --title "{stem}" --purpose <目的> --emphasis <重点のID> --create` で、質問の Issue を作る
   - Issue のタイトルは、必ず「取り込み確認: {stem}」になる（`--title` は `{stem}` のままにする）
4. 作った Issue の番号とリンク、分割案の件数を、日本語で短く報告する

重要箇所の選定は、まだ始めない（人が回答してから、見張りが続きを進める）。人の判断（分け方の承認・対象・読み方）は決めない。
作業中に作る一時ファイルは、リポジトリ直下の `work-gai/` に作る。
"""


def inbox_pdfs(inbox: Path = INBOX) -> list[Path]:
    return sorted(p for p in inbox.glob("*.pdf") if p.is_file())


def move_to_output(pdf: Path, output: Path = OUTPUT) -> Path:
    """PDF 名（拡張子なし）のフォルダへ移す。すでに同名のPDFがあるときは、上書きせずエラーにする。"""
    dest = output / pdf.stem / pdf.name
    if dest.exists():
        raise ValueError(f"{dest} がすでにあります（上書きしません）。inbox の PDF は移していません")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf), str(dest))
    return dest


def plan_command(stem: str) -> list[str]:
    prompt = PLAN_PROMPT.format(stem=stem)
    return ["claude", "-p", prompt, "--permission-mode", "acceptEdits", "--allowedTools", *PLAN_TOOLS]


def open_issues() -> dict[str, int]:
    """開いている「取り込み確認: <名前>」の Issue を、{名前: 番号} で返す。"""
    out = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--limit", "100", "--json", "number,title"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return {
        i["title"][len(ISSUE_TITLE) :]: i["number"]
        for i in json.loads(out.stdout)
        if i["title"].startswith(ISSUE_TITLE)
    }


def pending_books(issues: dict[str, int], output: Path = OUTPUT) -> list[tuple[Path, int]]:
    """回答待ちの本・号。質問の Issue が開いていて、articles.json があり、まだ反映していない（split.approved が空）もの。"""
    found = []
    for name, number in sorted(issues.items()):
        plan = output / name / "articles.json"
        if not plan.is_file():
            continue
        approved = json.loads(plan.read_text(encoding="utf-8")).get("split", {}).get("approved")
        if not approved:
            found.append((plan, number))
    return found


def watch_command(plan: Path, issue: int) -> str:
    """別ウィンドウで動かす見張りのコマンド（終わっても、結果を読めるように pause する）。"""
    return f'cd /d "{ROOT / "app"}" && uv run python watch.py --plan "{plan}" --issue {issue} & pause'


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="inbox の PDF を取り込み、回答待ちの見張りを起動する")
    p.add_argument("--dry-run", action="store_true", help="何をするかだけ表示する")
    p.add_argument(
        "--no-watch", action="store_true", help="回答待ちの見張り（別ウィンドウ）を起動しない（web.py が見張る）"
    )
    args = p.parse_args(argv)

    try:
        pdfs = inbox_pdfs()
        print(f"inbox の PDF: {len(pdfs)}件" + "".join(f"\n  - {p.name}" for p in pdfs))
        for pdf in pdfs:
            if args.dry_run:
                print(f"[dry-run] {pdf.name} を output/{pdf.stem}/ に移し、分割案と質問の Issue を作る")
                continue
            moved = move_to_output(pdf)
            print(f"\n== {pdf.stem}: 分割案と質問の Issue を作ります（数分かかります）")
            log = moved.parent / "claude-plan.log"
            with log.open("w", encoding="utf-8") as f:
                code = subprocess.run(
                    plan_command(pdf.stem), cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, text=True, encoding="utf-8"
                ).returncode
            print(f"   結果: {log.read_text(encoding='utf-8').strip()[-600:] or '(出力なし)'}")
            if code != 0:
                print(f"   Claude が異常終了しました（終了コード {code}）。経過: {log}")

        if args.no_watch:
            return 0
        books = pending_books(open_issues())
        if not books:
            print("\n回答待ちの本・号はありません。")
            return 0
        print(f"\n回答待ち: {len(books)}件")
        for plan, number in books:
            print(f"  - {plan.parent.name}（Issue #{number}）→ 見張りを別ウィンドウで起動します")
            if not args.dry_run:
                flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
                subprocess.Popen(["cmd", "/c", watch_command(plan, number)], creationflags=flags, cwd=ROOT / "app")
        if not args.dry_run:
            print("\nIssue にチェックを付けて、最後の「作業開始OK」を付けると、自動で進みます。")
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
