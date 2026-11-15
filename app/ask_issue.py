"""分け方・対象・読み方を、1つの GitHub Issue（チェックボックス）にまとめて聞く。

    uv run python ask_issue.py --plan ../output/<書名>/articles.json --title "<書名>"              # 本文を表示するだけ
    uv run python ask_issue.py --plan ../output/<書名>/articles.json --title "<書名>" --create     # Issue を作る
    uv run python ask_issue.py --plan ... --title "<書名>" --update 20      # 分け方を変えたとき、本文を書き換える

人は、スマホで Issue にチェックを付けるだけでよい（「提案どおり」を1つ選べば、個別の選択は要らない）。
答えは `read_answers.py` が読んで、`split.approved`・`target`・`reading.json` に写す。

提案（推奨）は本文へ書く。チェックを付けてあるのは、「2. 対象」の★だけ（人の指示。外せる）。ほかは人に代わって答えない。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from plan_issue import MIN_CHARS, SKIP_WORDS

PURPOSES = {
    "概要をつかむ": "各章の主張と、全体の骨子",
    "実務に使う": "手順・設計上の注意",
    "体系的に学ぶ": "用語・概念の定義、因果関係",
    "後で探すための索引にする": "用語・概念を引けるようにする",
}
# 色の選択肢: ラベル -> (使う色, warning の扱い)
COLOR_CHOICES = {
    "3色（注意は主張に直結するものだけ）": (["know", "do", "warn"], "記事の主張に直結するものだけ"),
    "3色（注意を積極的に）": (["know", "do", "warn"], "積極的に拾う"),
    "2色（知る・方針・実践。注意は使わない）": (["know", "do"], None),
    "2色（方針・実践・注意。知るは使わない）": (["do", "warn"], "積極的に拾う"),
}
# 目的ごとの既定の色（docs/workflow.md の「目的ごとの配色」）
DEFAULT_COLOR = {
    "概要をつかむ": "2色（知る・方針・実践。注意は使わない）",
    "実務に使う": "3色（注意を積極的に）",
    "体系的に学ぶ": "3色（注意は主張に直結するものだけ）",
    "後で探すための索引にする": "2色（知る・方針・実践。注意は使わない）",
}
START = "作業開始OK（上の回答を終えました）"
CHANGE = "分け方を変えたい（コメントに書く）"
RECOMMENDED = " ← 推奨"  # 太字だと見づらいので、文字で示す
NO_EMPHASIS = "特になし（全章を同じ密度で）"
IDS_MARK = "<!-- plan-ids: "


def recommended_ids(articles: list[dict]) -> list[str]:
    """対象にすることを提案する記事。本編と関係が薄いもの・文字が取れないものは外す。"""
    return [
        a["id"]
        for a in articles
        if a.get("readable", "ok") == "ok"
        and a.get("chars", MIN_CHARS) >= MIN_CHARS  # 部の扉など、文字がほとんど無いもの
        and (a.get("merged") or not any(w.lower() in a["title"].lower() for w in SKIP_WORDS))  # 前書き・索引・付録など
    ]


def label(a: dict, pages: bool = False) -> str:
    title = a["name"] if a.get("merged") and a.get("name") else a["title"]  # 合体した記事は、短い名前で
    count = f"・{a['last'] - a['first'] + 1}ページ" if pages else ""
    return f"{title.replace(chr(0x3000), ' ')}（`{a['id']}` p.{a['first']}-{a['last']}{count}）"


def contents(a: dict) -> list[str]:
    """合体した記事に含まれる章・見出しを、1行ずつ（インデントした箇条書き）。短い名前だけでは、中身が分からないため。"""
    if not a.get("merged"):
        return []
    return [f"  - {t.strip().replace(chr(0x3000), ' ')}" for t in a["title"].split("+") if t.strip()]


def item(box: str, a: dict, *, pages: bool = False, star: bool = False, rec: bool = False) -> list[str]:
    """チェックボックス1行と、その下に含まれる章の見出し。"""
    head = f"- [{box}] {'★ ' if star else ''}{label(a, pages=pages)}{RECOMMENDED if rec else ''}"
    return [head, *contents(a)]


def render_body(plan: dict, book: str, *, purpose: str, recommend: list[str], emphasis: list[str]) -> str:
    arts = plan["articles"]
    star = set(recommend)
    color = DEFAULT_COLOR[purpose]
    out = [
        f"{IDS_MARK}{','.join(a['id'] for a in arts)} -->",
        f"**{book}** を取り込みます。チェックを付けるだけで答えられます（スマホのアプリで可）。",
        "★と「← 推奨」は私（Claude）の提案です。「1.」の★だけは、提案としてチェック済みにしてあります（外せます）。",
        "それ以外は、チェックを付けていません。決めるのはあなたです。",
        "",
        "## 1. 分け方と対象",
        "",
        "一覧は、分け方（章とページ範囲）の案です。チェックが付いた記事が対象になります（外すと対象外）。",
        "この分け方でよければ、何もしなくて大丈夫です（最後の「作業開始OK」で、承認したことになります）。",
        "",
        *[line for a in arts for line in item("x" if a["id"] in star else " ", a, pages=True, star=a["id"] in star)],
        "",
        "分け方を変えたいときだけ、これをチェックして、コメントに書いてください。",
        "",
        f"- [ ] {CHANGE}",
        "",
        "## 2. 読み方",
        "",
        "### 目的（1つ）",
        "",
        *[f"- [ ] {k}（{v}）{RECOMMENDED if k == purpose else ''}" for k, v in PURPOSES.items()],
        "",
        "### 重点にする章（複数可）",
        "",
        *[line for a in arts if a["id"] in star for line in item(" ", a, rec=a["id"] in emphasis)],
        f"- [ ] {NO_EMPHASIS}",
        "",
        "### 使う色（1つ）",
        "",
        *[f"- [ ] {k}{RECOMMENDED if k == color else ''}" for k in COLOR_CHOICES],
        "",
        "## 3. その他",
        "",
        "自由に書きたいことは、コメントにお願いします（例: 「2章の設定例は読み飛ばす」）。",
        "",
        "---",
        "",
        "## 4. 作業開始",
        "",
        "ここまで答え終わったら、最後にこれをチェックしてください。チェックが付くまで、作業は始めません。",
        "",
        f"- [ ] {START}",
        "",
        "Claude のセッションが開いている間は、「作業開始OK」が付いたら自動で反映して次へ進みます（合図は要りません）。",
        "セッションが閉じているときは、次に開いたときに「答えたよ」と伝えてください。",
    ]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(
        description="分け方・対象・読み方を、1つの Issue にまとめて聞く（既定は本文を表示するだけ）"
    )
    p.add_argument("--plan", type=Path, required=True, help="articles.json")
    p.add_argument("--title", required=True, help="書名または号（Issue のタイトルに使う）")
    p.add_argument("--purpose", default="実務に使う", choices=list(PURPOSES), help="目的の推奨")
    p.add_argument("--recommend", nargs="*", metavar="ID", help="対象にすることを提案する記事（省略時は自動）")
    p.add_argument("--emphasis", nargs="*", default=[], metavar="ID", help="重点にすることを提案する記事")
    p.add_argument("--create", action="store_true", help="Issue を作る")
    p.add_argument("--update", type=int, metavar="ISSUE", help="すでにある Issue の本文を、新しい分割案で書き換える")
    args = p.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        known = {a["id"] for a in plan["articles"]}
        recommend = args.recommend if args.recommend is not None else recommended_ids(plan["articles"])
        bad = [i for i in [*recommend, *args.emphasis] if i not in known]
        if bad:
            raise ValueError(f"記事 {', '.join(bad)} が {args.plan.name} にありません")
        body = render_body(plan, args.title, purpose=args.purpose, recommend=recommend, emphasis=args.emphasis)
        if not (args.create or args.update):
            print(body)
            return 0
        if args.update:
            subprocess.run(
                ["gh", "issue", "edit", str(args.update), "--body-file", "-"],
                input=body,
                text=True,
                encoding="utf-8",
                check=True,
                stdout=subprocess.DEVNULL,
            )
            print(f"#{args.update} の本文を書き換えました")
            return 0
        out = subprocess.run(
            ["gh", "issue", "create", "--title", f"取り込み確認: {args.title}", "--body-file", "-"],
            input=body,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (ValueError, OSError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    print(out.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
