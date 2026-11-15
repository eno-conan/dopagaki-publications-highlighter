"""`ask_issue.py` で作った Issue のチェックを読み、`articles.json` と `reading.json` に写す。

    uv run python read_answers.py --plan ../output/<書名>/articles.json --issue 20           # 読んで状況を表示するだけ
    uv run python read_answers.py --plan ../output/<書名>/articles.json --issue 20 --apply   # 揃っていれば写して閉じる
    uv run python read_answers.py --plan ... --issue 20 --apply --wait                       # 揃うまで待つ

終了コード: 0 = 回答が揃った（--apply なら反映した） / 2 = まだ揃っていない / 3 = 「分け方を変えたい」 / 1 = エラー。

写すのは人が付けたチェックだけ。対象は、チェックの付いた記事（★は最初からチェック済み）。読み方は目的と色は、人が選んだものだけを使う（「推奨」は提案で、答えにはしない）。
チェックが矛盾しているとき（提案どおりと個別の両方、目的が複数など）は、揃っていない扱いにして理由を表示する。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ask_issue import (
    CHANGE,
    COLOR_CHOICES,
    IDS_MARK,
    NO_EMPHASIS,
    PURPOSES,
    START,
)

CHECKBOX = re.compile(r"^- \[([ xX])\] (.*)$")
ID_IN_TEXT = re.compile(r"`(p\d+(?:-\d+)?[a-z]?)`")
RECOMMENDED = " ← 推奨"


@dataclass
class Answers:
    plan_ids: list[str] = field(default_factory=list)
    start: bool = False
    change: bool = False
    target_ids: list[str] = field(default_factory=list)
    purposes: list[str] = field(default_factory=list)
    emphasis: list[str] = field(default_factory=list)
    no_emphasis: bool = False
    colors: list[str] = field(default_factory=list)


@dataclass
class Result:
    status: str  # ready / incomplete / change
    problems: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    reading: dict = field(default_factory=dict)


def parse_body(body: str) -> Answers:
    a = Answers()
    section = sub = ""
    for raw in body.splitlines():
        line = raw.rstrip()
        if line.startswith(IDS_MARK):
            a.plan_ids = [i for i in line[len(IDS_MARK) :].removesuffix("-->").strip().split(",") if i]
        elif line.startswith("### "):
            sub = line[4:]
        elif line.startswith("## "):
            section, sub = line[3:], ""
        m = CHECKBOX.match(line)
        if not m:
            continue
        checked, text = m.group(1) != " ", m.group(2)
        ids = ID_IN_TEXT.findall(text)
        text = text.removesuffix(RECOMMENDED)
        if section.startswith("1."):
            if text == CHANGE:
                a.change = checked
            elif ids and checked:
                a.target_ids += ids
        elif section.startswith("4."):
            if text == START:
                a.start = checked
        elif section.startswith("2."):
            if sub.startswith("目的"):
                key = text.split("（")[0]
                if key in PURPOSES and checked:
                    a.purposes.append(key)
            elif sub.startswith("重点"):
                if text == NO_EMPHASIS:
                    a.no_emphasis = checked
                elif ids and checked:
                    a.emphasis += ids
            elif sub.startswith("使う色") and text in COLOR_CHOICES and checked:
                a.colors.append(text)
    return a


def resolve(a: Answers, titles: dict[str, str], note: str = "", today: str | None = None) -> Result:
    if a.change:
        return Result("change", ["「分け方を変えたい」が選ばれています。コメントを読んで、分け方を直してください"])
    problems: list[str] = []
    if not a.start:
        problems.append("4. 最後の「作業開始OK」が未チェックです（チェックが付くまで、作業は始めません）")

    targets: list[str] = []
    if a.target_ids:
        targets = list(a.target_ids)
    else:
        problems.append("1. 対象が1つも選ばれていません")
    unknown = [i for i in targets if i not in titles]
    if unknown:
        problems.append(f"1. 一覧にない記事です: {', '.join(unknown)}")

    purpose, emphasis, color = "", [], ""
    if len(a.purposes) != 1:
        problems.append(f"2. 目的は1つだけ選んでください（いま {len(a.purposes)} 個）")
    else:
        purpose = a.purposes[0]
    if len(a.colors) != 1:
        problems.append(f"2. 使う色は1つだけ選んでください（いま {len(a.colors)} 個）")
    else:
        color = a.colors[0]
    if a.no_emphasis and a.emphasis:
        problems.append("2. 重点の「特になし」と章のチェックが両方あります")
    emphasis = a.emphasis  # 重点は、選ばなくてもよい

    if problems:
        return Result("incomplete", problems)
    colors, warning = COLOR_CHOICES[color]
    reading = {
        "answered": today or date.today().isoformat(),
        "purpose": purpose,
        "emphasis": [titles[i] for i in emphasis if i in titles],
        "colors": colors,
    }
    if warning:
        reading["warning"] = warning
    if note:
        reading["note"] = note
    return Result("ready", [], targets, reading)


def write_plan(path: Path, plan: dict) -> None:
    """plan_issue.py の保存形式（記事は1行ずつ）に合わせて書く。"""
    head = f'  "pdf": {json.dumps(plan["pdf"], ensure_ascii=False)},\n'
    if "split" in plan:
        head += f'  "split": {json.dumps(plan["split"], ensure_ascii=False)},\n'
    lines = ",\n".join("    " + json.dumps(a, ensure_ascii=False) for a in plan["articles"])
    text = f'{{\n{head}  "articles": [\n{lines}\n  ]\n}}\n'
    assert json.loads(text) == plan
    path.write_text(text, encoding="utf-8", newline="\n")


def apply_answers(plan_path: Path, plan: dict, result: Result) -> None:
    plan.setdefault("split", {})["approved"] = [a["id"] for a in plan["articles"]]
    for a in plan["articles"]:
        a["target"] = a["id"] in result.targets
    write_plan(plan_path, plan)
    (plan_path.parent / "reading.json").write_text(
        json.dumps(result.reading, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def apply_and_comment(plan_path: Path, plan: dict, result: Result, issue: int) -> None:
    """回答を articles.json と reading.json に写し、反映したことを Issue にコメントする（閉じない）。"""
    apply_answers(plan_path, plan, result)
    names = ", ".join(a["id"] for a in plan["articles"] if a.get("target"))
    body = (
        f"<!-- applied -->\n反映しました（対象: {names}）。`articles.json` と `reading.json` に写しました。"
        "作業が終わったら閉じます。"
    )
    subprocess.run(["gh", "issue", "comment", str(issue), "--body", body], check=True, stdout=subprocess.DEVNULL)


def fetch_issue(issue: int) -> tuple[str, str]:
    """Issue の本文と、人が書いたコメント（自動投稿の `<!--` で始まるものを除く）を返す。"""
    out = subprocess.run(
        ["gh", "issue", "view", str(issue), "--json", "body,comments"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    data = json.loads(out.stdout)
    notes = [c["body"].strip() for c in data["comments"] if not c["body"].lstrip().startswith("<!--")]
    return data["body"], "\n\n".join(n for n in notes if n)


def evaluate(plan: dict, issue: int) -> Result:
    body, note = fetch_issue(issue)
    a = parse_body(body)
    current = [x["id"] for x in plan["articles"]]
    if a.plan_ids and a.plan_ids != current:
        return Result(
            "incomplete",
            ["Issue の分割案が articles.json と違います（分け方を変えたあとは Issue を作り直してください）"],
        )
    titles = {x["id"]: x["title"].replace("　", " ") for x in plan["articles"]}
    return resolve(a, titles, note)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="取り込み確認の Issue を読んで、articles.json と reading.json に写す")
    p.add_argument("--plan", type=Path, required=True, help="articles.json")
    p.add_argument("--issue", type=int, required=True, help="ask_issue.py で作った Issue の番号")
    p.add_argument(
        "--apply",
        action="store_true",
        help="揃っていれば写して、Issue にコメントする（閉じるのは、作業が終わってから。pipeline.py --close）",
    )
    p.add_argument("--wait", action="store_true", help="揃う（または分け方の変更が選ばれる）まで待つ")
    p.add_argument("--interval", type=int, default=120, help="待つときの確認間隔（秒）")
    p.add_argument("--timeout", type=int, default=6 * 3600, help="待つ最長の時間（秒）")
    args = p.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        deadline = time.monotonic() + args.timeout
        while True:
            result = evaluate(plan, args.issue)
            if result.status != "incomplete" or not args.wait or time.monotonic() >= deadline:
                break
            time.sleep(args.interval)
        if result.status == "ready" and args.apply:
            apply_and_comment(args.plan, plan, result, args.issue)
    except (ValueError, OSError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    if result.status == "ready":
        print(f"回答が揃っています。対象: {', '.join(result.targets)}")
        print(json.dumps(result.reading, ensure_ascii=False, indent=2))
        return 0
    for line in result.problems:
        print(line)
    return 3 if result.status == "change" else 2


if __name__ == "__main__":
    sys.exit(main())
