"""PDF の指定ページ範囲だけを小さい別PDFに切り出す（元PDFは読み取りのみ）。

    uv run python split_pdf.py --pdf ../book.pdf --first 31 --last 72 --name 第1特集   # → book_第1特集.pdf
    uv run python split_pdf.py --plan ../output/<PDF名>/articles.json                         # 「対象」の記事をまとめて

ページ番号はビューアに表示される PDF ページ番号（1始まり）。印刷ページ番号ではない。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pymupdf

from mark_pdf import derived_path, find_pdf, open_pdf


def default_name(first: int, last: int) -> str:
    return f"{first}-{last}ページ抜粋"


def default_out_path(pdf: Path, name: str) -> Path:
    return derived_path(pdf, name)


def article_name(article: dict) -> str:
    return article.get("name") or default_name(article["first"], article["last"])


EXCERPT_DIR = "分割"  # 切り出しただけのPDF（マーカーなし）
MARKERS_DIR = "マーカー付き"  # 重要箇所を付けたPDF


_UNSAFE_IN_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\s]')


def safe_filename(name: str) -> str:
    """記事の名前を、PDFのファイル名にできる形にする。

    Windows のファイル名に使えない文字（バックスラッシュ / : * ? " < > | と制御文字）と、
    半角スペース・タブは、ハイフンにする。
    ハイフンが続くときは1つにまとめ、両端のハイフンとピリオドは落とす。全角の文字（：や？など）はそのまま。
    """
    stem = re.sub(r"-{2,}", "-", _UNSAFE_IN_FILENAME.sub("-", name)).strip("-.")
    return stem or "article"


def file_stem(article: dict) -> str:
    """PDFのファイル名（拡張子なし）。記事の名前（`name`）から作る。"""
    return safe_filename(article_name(article))


def output_path(plan_dir: Path, article: dict, kind_dir: str) -> Path:
    """記事のPDFの出力先 `<articles.json のフォルダ>/<kind_dir>/<name>.pdf`。

    出力先の組み立てはここだけに置く。ファイル名は記事の名前（`name`）から作り（`safe_filename`）、同じファイル名になる記事があると衝突する。
    """
    return plan_dir / kind_dir / f"{file_stem(article)}.pdf"


def markers_path(plan_dir: Path, article: dict) -> Path:
    """重要箇所を付けたPDFの出力先 `マーカー付き/<name>.pdf`。"""
    return output_path(plan_dir, article, MARKERS_DIR)


def excerpt_path(plan_dir: Path, article: dict) -> Path:
    """記事を切り出しただけのPDF（`split_pdf.py --plan` で作る）の出力先 `分割/<name>.pdf`。"""
    return output_path(plan_dir, article, EXCERPT_DIR)


def shift_toc(toc: list[list], first: int, last: int) -> list[list]:
    """範囲内のしおりだけ残し、ページ番号を切り出し後に合わせる（set_toc の階層制約も満たす）。"""
    inside = [e for e in toc if first <= e[2] <= last]
    if not inside:
        return []
    base = min(e[0] for e in inside)
    shifted: list[list] = []
    prev = 0
    for level, title, page, *rest in inside:
        level = min(level - base + 1, prev + 1)
        shifted.append([level, title, page - first + 1, *rest])
        prev = level
    return shifted


def article_ranges(article: dict) -> list[tuple[int, int]]:
    """記事のページ範囲。離れた記事を合体したもの（`ranges`）は複数、ふつうは first〜last の1つ。"""
    if article.get("ranges"):
        return [(int(f), int(last)) for f, last in article["ranges"]]
    return [(article["first"], article["last"])]


def extract_pages(pdf: Path, first: int, last: int, out: Path) -> int:
    """pdf の first〜last ページ（1始まり、両端含む）を out に保存し、ページ数を返す。"""
    return extract_ranges(pdf, [(first, last)], out)


def extract_ranges(pdf: Path, ranges: list[tuple[int, int]], out: Path) -> int:
    """pdf の複数のページ範囲（1始まり、両端含む）を、並べて1つの out に保存し、ページ数を返す。"""
    if out.resolve() == pdf.resolve():
        raise ValueError("--out が元PDFと同じです。元PDFは上書きしません")
    src = open_pdf(pdf)
    try:
        for first, last in ranges:
            if not 1 <= first <= last <= src.page_count:
                raise ValueError(f"ページ範囲 {first}-{last} が不正です（全{src.page_count}ページ）")
        new = pymupdf.open()
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            for first, last in ranges:
                new.insert_pdf(src, from_page=first - 1, to_page=last - 1)
            if len(ranges) == 1:  # 離れた範囲の合体は、しおりを引き継がない
                toc = shift_toc(src.get_toc(simple=False), *ranges[0])
                if toc:
                    new.set_toc(toc)
            tmp = out.with_name(out.name + ".tmp")
            try:
                new.save(tmp, garbage=3, deflate=True)  # 新規ファイルなので未使用オブジェクトも落として小さくする
                os.replace(tmp, out)
            finally:
                tmp.unlink(missing_ok=True)
            return new.page_count
        finally:
            new.close()
    finally:
        src.close()


def split_plan(plan_path: Path, only: list[str]) -> int:
    """articles.json（plan_issue.py の出力）で「対象」にした記事を、まとめて切り出す。"""
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    pdf = plan_path.parent / plan["pdf"]
    if not pdf.is_file():
        raise ValueError(f"元PDF が見つかりません: {pdf}")
    targets = [a for a in plan["articles"] if a.get("target") is True and (not only or a["id"] in only)]
    unknown = [i for i in only if i not in {a["id"] for a in plan["articles"]}]
    if unknown:
        raise ValueError(f"記事 {', '.join(unknown)} が {plan_path.name} にありません")
    if not targets:
        raise ValueError("対象の記事がありません（plan_issue.py --include で対象にしてください）")
    for a in targets:
        out = excerpt_path(plan_path.parent, a)
        count = extract_ranges(pdf, article_ranges(a), out)
        size_mb = out.stat().st_size / 1024 / 1024
        print(f"{a['id']:<10} {count:>3}ページ {size_mb:>5.1f}MB  {out.parent.name}/{out.name}")
    print(f"{len(targets)}記事を切り出しました")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="PDF の指定ページ範囲を別PDFに切り出す")
    p.add_argument("--pdf", type=Path, help="元PDF。省略時はカレントフォルダの元PDF（名前に _ を含まない *.pdf）")
    p.add_argument("--first", type=int, help="開始ページ（PDFページ番号、1始まり）")
    p.add_argument("--last", type=int, help="終了ページ（含む）")
    p.add_argument(
        "--name",
        help="出力ファイル名の日本語部分（例: 第1特集 → <元ファイル名>_第1特集.pdf）。省略時は「31-72ページ抜粋」の形",
    )
    p.add_argument("--out", type=Path, help="出力先。--name より優先")
    p.add_argument("--plan", type=Path, help="articles.json。「対象」の記事をまとめて切り出す（--first/--last は不要）")
    p.add_argument("--only", nargs="*", default=[], metavar="ID", help="--plan のうち、このIDの記事だけ切り出す")
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if args.plan:
            return split_plan(args.plan, args.only)
        if args.first is None or args.last is None:
            raise ValueError("--first と --last を指定してください（または --plan）")
        pdf = args.pdf or find_pdf(Path.cwd())
        if not pdf.is_file():
            raise ValueError(f"PDF が見つかりません: {pdf}")
        out = args.out or default_out_path(pdf, args.name or default_name(args.first, args.last))
        count = extract_pages(pdf, args.first, args.last, out)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"{pdf.name} の p.{args.first}-{args.last}（{count}ページ）を切り出しました: {out}（{size_mb:.1f}MB）")
    print(f"元PDFのページ = 切り出し後のページ + {args.first - 1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
