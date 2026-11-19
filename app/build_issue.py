"""articles.json で「対象」にした記事を、まとめて仕上げる（重要箇所を適用 → マーカー付きPDF）。

    uv run python build_issue.py --plan ../output/<PDF名>/articles.json

重要箇所のJSON（記事ごとの `highlights`）がある記事だけ、ハイライトを付ける。
JSONが無い記事は「重要箇所が未選定」と表示して、何も作らない（本文を読んで選ぶ工程は別）。
出力は `<articles.json のフォルダ>/分割/<name>.pdf`（切り出しただけ）と `マーカー付き/<name>.pdf`（重要箇所を付けた）。
何度実行しても、同じJSONなら同じ結果になる。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from apply_highlights import apply_highlights, load_document
from contents_page import add_contents_page
from mark_pdf import write_annotated_copy
from split_pdf import article_name, article_ranges, excerpt_path, extract_ranges, file_stem, markers_path


@dataclass
class Built:
    id: str
    name: str
    pages: int
    status: str  # 「重要箇所が未選定」「ハイライト N件」など
    unmatched: int = 0


def build_article(base: Path, plan_dir: Path, article: dict) -> Built:
    name = article_name(article)
    ranges = article_ranges(article)
    pages = sum(last - first + 1 for first, last in ranges)
    json_path = plan_dir / (article.get("highlights") or f"highlights/{article['id']}.json")
    if not json_path.is_file():
        return Built(article["id"], name, pages, "重要箇所が未選定（PDFは作らない）")

    out = markers_path(plan_dir, article)
    doc = load_document(json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    extract = excerpt_path(plan_dir, article)  # 切り出しただけのPDFも `分割/` に残す（あとで移動しやすいように）
    extract_ranges(base, ranges, extract)
    results = write_annotated_copy(extract, out, lambda d: apply_highlights(d, doc.highlights, dry_run=False))
    toc = add_contents_page(out, article) if article.get("merged") else False  # 合体した記事は、先頭に目次ページ
    applied = sum(1 for r in results if r.applied)
    unmatched = len(results) - applied
    status = f"ハイライト {applied}/{len(results)}件 → {out.parent.name}/{out.name}" + (
        f"（未適用 {unmatched}件）" if unmatched else ""
    )
    status += "（先頭に目次ページ）" if toc else ""
    return Built(article["id"], name, pages, status, unmatched)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="「対象」の記事を、切り出し・ハイライトまでまとめて作る")
    p.add_argument("--plan", type=Path, required=True, help="articles.json（plan_issue.py の出力）")
    p.add_argument("--only", nargs="*", default=[], metavar="ID", help="このIDの記事だけ処理する")
    args = p.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        base = args.plan.parent / plan["pdf"]
        if not base.is_file():
            raise ValueError(f"元PDF が見つかりません: {base}")
        known = {a["id"] for a in plan["articles"]}
        unknown = [i for i in args.only if i not in known]
        if unknown:
            raise ValueError(f"記事 {', '.join(unknown)} が {args.plan.name} にありません")
        targets = [a for a in plan["articles"] if a.get("target") is True and (not args.only or a["id"] in args.only)]
        if not targets:
            raise ValueError("対象の記事がありません（plan_issue.py --include で対象にしてください）")
        stems = [file_stem(a) for a in targets]
        dup = sorted({n for n in stems if stems.count(n) > 1})
        if dup:
            raise ValueError(f"記事のPDFのファイル名が重複しています（name から作ります）: {', '.join(dup)}")
        built = [build_article(base, args.plan.parent, a) for a in targets]
    except (ValueError, OSError, json.JSONDecodeError, KeyError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    for b in built:
        print(f"{b.id:<10} {b.pages:>3}ページ  {b.name}  → {b.status}")
    print(f"{len(built)}記事を処理しました")
    return 1 if any(b.unmatched for b in built) else 0


if __name__ == "__main__":
    sys.exit(main())
