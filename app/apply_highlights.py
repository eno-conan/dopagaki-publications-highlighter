"""「重要」と判断した箇所のリスト（JSON）をもとに、PDFへカテゴリ別の色でハイライトを付ける。

重要箇所の選定（本文と参考リンクを読んで判断する部分）は別工程で行い、その結果を JSON に残す。
このスクリプトは JSON を機械的に適用するだけなので、同じ JSON なら何度実行しても同じ結果になる。

    uv run python apply_highlights.py --pdf ../book_第1特集.pdf --highlights ../highlights/p31-72.json --dry-run
    uv run python apply_highlights.py --pdf ../book_第1特集.pdf --highlights ../highlights/p31-72.json

JSON の形式:
    {"highlights": [
        {"page": 4, "text": "ハイライトする本文", "category": "definition", "reason": "なぜ重要か",
         "check": "参考リンクとの照合結果（任意）", "occurrence": 1}
    ]}
page は --pdf のPDFページ番号（1始まり）。text は改行・空白の位置が違っても、全角半角の違いがあっても一致する。
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import pymupdf

from mark_pdf import derived_path, open_pdf, write_annotated_copy

OUT_LABEL = "重要箇所"


class Group(NamedTuple):
    """ハイライトの色。4色ボールペンの発想で、色は3つに絞る（黒＝通常の文字）。"""

    label: str
    color: tuple[float, float, float]  # ハイライト色（RGB 0-1）
    description: str


GROUPS: dict[str, Group] = {
    "know": Group("知る", (0.55, 0.82, 1.0), "用語の意味と、それを裏づける数値・事実"),  # 青
    "do": Group("方針・実践", (0.6, 0.9, 0.5), "設計の方針・主張と、具体的にやること"),  # 緑
    "warn": Group("注意", (1.0, 0.5, 0.5), "やってはいけないこと、成り立たない条件、手法の限界"),  # 赤
}


class Category(NamedTuple):
    """色の下位ラベル。色の下位の名前。"""

    label: str
    group: str  # GROUPS のキー
    criteria: str  # どういう箇所に使うか


CATEGORIES: dict[str, Category] = {
    "definition": Category("定義", "know", "用語の意味（専門用語、略語 など）"),
    "evidence": Category("根拠・数値", "know", "研究・計測の数値。主張を裏づける事実"),
    "principle": Category("原則・主張", "do", "結論・設計方針。特集の主張を理解するのに欠かせない文"),
    "practice": Category("実践", "do", "具体的にやること。導入・運用の手順や方針"),
    "warning": Category("注意・限界", "warn", "やってはいけないこと、成り立たない条件、手法の限界"),
}


def color_of(category: str) -> tuple[float, float, float]:
    return GROUPS[CATEGORIES[category].group].color


# 照合状況。参考リンクで裏づけを確認できた箇所にだけ印を付ける（印がない＝本誌の記述に基づく選定）
VERIFICATION: dict[str, str] = {
    "verified": "照合済み",
    "partial": "一部照合",
}


@dataclass
class Highlight:
    page: int
    text: str
    category: str
    reason: str
    check: str = ""  # 照合結果のメモ（自由記述）
    verification: str = ""  # 空＝印なし。VERIFICATION のキー
    refs: list[str] = field(default_factory=list)  # Reference.id
    occurrence: int = 1


@dataclass
class Reference:
    id: str
    name: str
    url: str
    checked: str  # 何を確認したか
    result: str  # VERIFICATION のキー


@dataclass
class Document:
    title: str = ""
    source_pdf: str = ""
    page_offset: int | None = None  # 元PDFのページ = page + page_offset
    references: list[Reference] = field(default_factory=list)
    highlights: list[Highlight] = field(default_factory=list)


@dataclass
class HighlightResult:
    highlight: Highlight
    found: int = 0  # 一致した箇所の数（ページ内）
    applied: bool = False
    warning: str = ""
    lines: int = 0  # ハイライトした行数
    rects: list[pymupdf.Rect] = field(default_factory=list)


# --------------------------------------------------------------------------- 読み込み


def load_document(path: Path) -> Document:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    items = data["highlights"] if isinstance(data, dict) else data
    references = []
    for i, ref in enumerate(meta.get("references", []), 1):
        try:
            references.append(
                Reference(
                    id=str(ref["id"]),
                    name=str(ref["name"]),
                    url=str(ref["url"]),
                    checked=str(ref.get("checked", "")),
                    result=str(ref["result"]),
                )
            )
        except KeyError as e:
            raise ValueError(f"{path.name} の references {i} 件目が不正です: {e!r}") from e
        if references[-1].result not in VERIFICATION:
            raise ValueError(f"{path.name} の references {i} 件目: result '{references[-1].result}' は不明です")
    ref_ids = {r.id for r in references}

    highlights = []
    for i, item in enumerate(items, 1):
        try:
            h = Highlight(
                page=int(item["page"]),
                text=str(item["text"]),
                category=str(item.get("category", "principle")),
                reason=str(item.get("reason", "")),
                check=str(item.get("check", "")),
                verification=str(item.get("verification", "")),
                refs=[str(r) for r in item.get("refs", [])],
                occurrence=int(item.get("occurrence", 1)),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"{path.name} の {i} 件目が不正です: {e!r}") from e
        if h.category not in CATEGORIES:
            raise ValueError(f"{path.name} の {i} 件目: category '{h.category}' は不明です（{', '.join(CATEGORIES)}）")
        if h.verification and h.verification not in VERIFICATION:
            raise ValueError(f"{path.name} の {i} 件目: verification '{h.verification}' は不明です")
        unknown = [r for r in h.refs if r not in ref_ids]
        if unknown:
            raise ValueError(f"{path.name} の {i} 件目: refs {unknown} が meta.references にありません")
        if not normalize(h.text):
            raise ValueError(f"{path.name} の {i} 件目: text が空です")
        highlights.append(h)

    offset = meta.get("page_offset")
    return Document(
        title=str(meta.get("title", "")),
        source_pdf=str(meta.get("source_pdf", "")),
        page_offset=int(offset) if offset is not None else None,
        references=references,
        highlights=highlights,
    )


def load_highlights(path: Path) -> list[Highlight]:
    return load_document(path).highlights


# --------------------------------------------------------------------------- 検索


def normalize(text: str) -> str:
    """NFKC にして空白をすべて除く（改行位置・全角半角・空白の差を吸収する）。"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", text) if not ch.isspace())


def page_chars(page: pymupdf.Page) -> list[tuple[str, pymupdf.Rect, int]]:
    """ページの文字を (正規化した1文字, 外接矩形, 行ID) の列にする。空白は含めない。"""
    chars: list[tuple[str, pymupdf.Rect, int]] = []
    line_id = 0
    for block in page.get_text("rawdict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            line_id += 1
            for span in line["spans"]:
                for ch in span["chars"]:
                    rect = pymupdf.Rect(ch["bbox"])
                    chars.extend((n, rect, line_id) for n in unicodedata.normalize("NFKC", ch["c"]) if not n.isspace())
    return chars


def find_rects(chars: list[tuple[str, pymupdf.Rect, int]], text: str) -> list[list[pymupdf.Rect]]:
    """text が一致する箇所ごとに、行単位にまとめた矩形のリストを返す。"""
    needle = normalize(text)
    haystack = "".join(c for c, _, _ in chars)
    matches: list[list[pymupdf.Rect]] = []
    start = haystack.find(needle)
    while start != -1:
        per_line: dict[int, pymupdf.Rect] = {}
        for _, rect, line_id in chars[start : start + len(needle)]:
            per_line[line_id] = per_line[line_id] | rect if line_id in per_line else pymupdf.Rect(rect)
        matches.append(list(per_line.values()))
        start = haystack.find(needle, start + len(needle))
    return matches


# --------------------------------------------------------------------------- 適用


def apply_highlights(doc: pymupdf.Document, highlights: list[Highlight], dry_run: bool) -> list[HighlightResult]:
    results = []
    cache: dict[int, list[tuple[str, pymupdf.Rect, int]]] = {}
    for h in highlights:
        res = HighlightResult(h)
        results.append(res)
        if not 1 <= h.page <= doc.page_count:
            res.warning = f"p.{h.page} は範囲外です（全{doc.page_count}ページ）"
            continue
        if h.page not in cache:
            cache[h.page] = page_chars(doc[h.page - 1])
        chars = cache[h.page]
        if not chars:
            res.warning = f"p.{h.page} にテキストがありません（画像PDFの可能性）"
            continue
        matches = find_rects(chars, h.text)
        res.found = len(matches)
        if not matches:
            res.warning = f"p.{h.page} に見つかりません"
            continue
        if h.occurrence > len(matches):
            res.warning = f"p.{h.page} の一致は{len(matches)}箇所で、occurrence={h.occurrence} がありません"
            continue
        res.rects = matches[h.occurrence - 1]
        res.lines = len(res.rects)
        res.applied = True
        if not dry_run:
            page = doc[h.page - 1]  # 注釈は親ページの参照が必要なので、変数に保持しておく
            annot = page.add_highlight_annot(quads=[r.quad for r in res.rects])
            if annot is None:
                res.applied = False
                res.warning = f"p.{h.page} でハイライトを作れませんでした"
                continue
            annot.set_colors(stroke=color_of(h.category))
            annot.update()
    return results


# --------------------------------------------------------------------------- CLI


def default_out_path(pdf: Path) -> Path:
    """`<元>_<名前>.pdf` から `<元>_<名前>の重要箇所.pdf` を作る（元PDFなら `<元>_重要箇所.pdf`）。"""
    if "_" in pdf.stem:
        return pdf.with_name(f"{pdf.stem}の{OUT_LABEL}.pdf")
    return derived_path(pdf, OUT_LABEL)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="重要箇所リスト（JSON）をPDFへカテゴリ別の色のハイライトとして付ける")
    p.add_argument("--pdf", type=Path, required=True, help="対象PDF（切り出し済みのPDFを想定）")
    p.add_argument("--highlights", type=Path, required=True, help="重要箇所のJSON")
    p.add_argument(
        "--out",
        type=Path,
        help="出力先。省略時は <PDF名>の重要箇所.pdf（例: 元_第1特集.pdf → 元_第1特集の重要箇所.pdf）",
    )
    p.add_argument("--dry-run", action="store_true", help="注釈は付けず、一致するかだけ確認する")
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if not args.pdf.is_file():
            raise ValueError(f"PDF が見つかりません: {args.pdf}")
        highlights = load_highlights(args.highlights)
        out = args.out or default_out_path(args.pdf)
        if args.dry_run:
            doc = open_pdf(args.pdf)
            try:
                results = apply_highlights(doc, highlights, dry_run=True)
            finally:
                doc.close()
        else:
            results = write_annotated_copy(args.pdf, out, lambda doc: apply_highlights(doc, highlights, dry_run=False))
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    counts = {g: 0 for g in GROUPS}
    for r in results:
        h = r.highlight
        head = f"p.{h.page:>2} [{CATEGORIES[h.category].label}]"
        if r.applied:
            counts[CATEGORIES[h.category].group] += 1
            extra = f"（{r.found}箇所中 {h.occurrence} 番目）" if r.found > 1 else ""
            print(f"  OK  {head} {h.text[:30]}…{extra}")
        else:
            print(f"  NG  {head} {h.text[:30]}…  -> {r.warning}")
    applied = sum(counts.values())
    failed = len(results) - applied
    summary = " / ".join(f"{GROUPS[g].label} {n}" for g, n in counts.items())
    print(f"ハイライト {applied}/{len(results)}件（{summary}）、未適用 {failed}件")
    if not args.dry_run:
        print(f"出力: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
