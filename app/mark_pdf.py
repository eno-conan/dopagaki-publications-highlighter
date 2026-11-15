"""Issue のコメント（ページ番号＋引用）をもとに、書籍PDFへハイライト注釈を付ける。

uv run python mark_pdf.py --dry-run   # パース結果と検索ヒット数だけ確認
uv run python mark_pdf.py             # <元ファイル名>_コメント付き.pdf を出力
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import pymupdf

T = TypeVar("T")

DEFAULT_REPO = "eno-conan/books-articles"
DEFAULT_ISSUE = 526
ANNOT_TITLE = "book-marker"
MARKED_LABEL = "コメント付き"

# 先頭行: P20 / P20-22 / p.20 / P20〜22（全角数字・全角ハイフンは NFKC で半角になる）
PAGE_LINE_RE = re.compile(r"^[Pp]\.?\s*(\d+)(?:\s*[-‐–—―〜~ー]\s*(\d+))?$")
ALERT_RE = re.compile(r"^\[!\w+\]$")  # > [!IMPORTANT] などの GitHub アラート行
QUOTE_PREFIX_RE = re.compile(r"^\s*>+\s?")
URL_LINE_RE = re.compile(r"^https?://\S+$")
BRACKET_RE = re.compile(r"「([^「」]+)」")

NOTE_X = 20  # 付箋を置く位置（ページ左上からのオフセット）
NOTE_STEP = 24  # 同一ページに複数付箋を置くときの縦間隔


@dataclass
class Entry:
    """Issue コメント1件分のパース結果。"""

    comment_id: int
    first_page: int  # 印刷ページ番号
    last_page: int
    terms: list[str]  # 検索語。行をまたぐ引用は "\n" を残す
    note: str  # 注釈ポップアップに入れる本文（ページ行・アラート行を除く）

    @property
    def pages(self) -> range:
        return range(self.first_page, self.last_page + 1)

    @property
    def label(self) -> str:
        if self.first_page == self.last_page:
            return f"P{self.first_page}"
        return f"P{self.first_page}-{self.last_page}"


@dataclass
class Hit:
    printed_page: int
    pdf_page: int  # 1始まり
    term: str
    variant: str  # 実際にヒットした検索語
    count: int  # ヒット箇所数（行をまたぐと複数 quad）


@dataclass
class EntryResult:
    entry: Entry
    hits: list[Hit] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: int = 0  # 付けた（dry-run では付ける予定の）付箋の数
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- コメント取得・パース


def fetch_comments(repo: str, issue: int) -> list[dict]:
    """gh api で Issue コメントを全件取得する（GraphQL 系の gh issue view は使わない）。"""
    cmd = ["gh", "api", f"repos/{repo}/issues/{issue}/comments", "--paginate"]
    try:
        proc = subprocess.run(cmd, capture_output=True, encoding="utf-8", check=False)
    except FileNotFoundError as e:
        raise RuntimeError("gh コマンドが見つかりません（GitHub CLI を入れて gh auth login してください）") from e
    if proc.returncode != 0:
        raise RuntimeError(f"gh api が失敗しました: {proc.stderr.strip()}")
    return parse_json_stream(proc.stdout)


def parse_json_stream(text: str) -> list[dict]:
    """`--paginate` は JSON 配列をページ数ぶん連結して出力するので、順に decode して平坦化する。"""
    decoder = json.JSONDecoder()
    items: list[dict] = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        obj, pos = decoder.raw_decode(text, pos)
        items.extend(obj if isinstance(obj, list) else [obj])
    return items


def parse_comment(body: str, comment_id: int = 0) -> Entry | None:
    """コメント本文から Entry を作る。先頭行がページ番号でなければ None（無視）。"""
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip()), None)
    if start is None:
        return None
    m = PAGE_LINE_RE.match(unicodedata.normalize("NFKC", lines[start]).strip())
    if not m:
        return None
    first = int(m.group(1))
    last = int(m.group(2)) if m.group(2) else first
    if first > last:
        first, last = last, first
    if first < 1:
        return None

    quote_lines: list[str] = []
    note_lines: list[str] = []
    in_quote = False
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if ALERT_RE.match(QUOTE_PREFIX_RE.sub("", stripped).strip()):
            continue
        note_lines.append(line.rstrip())
        if stripped.startswith(">"):
            in_quote = True
            text = QUOTE_PREFIX_RE.sub("", stripped).strip()
            if text:
                quote_lines.append(text)
        elif in_quote and stripped and not URL_LINE_RE.match(stripped):
            # 引用の途中で改行されて ">" が付かない行（Markdown の lazy continuation）も引用の続き
            quote_lines.append(stripped)
        else:
            in_quote = False

    terms: list[str] = []
    if quote_lines:
        quote = "\n".join(quote_lines)
        bracketed = [t.strip() for t in BRACKET_RE.findall(quote) if t.strip()]
        terms = bracketed or [quote]
    return Entry(comment_id, first, last, terms, "\n".join(note_lines).strip())


def parse_comments(comments: list[dict]) -> list[Entry]:
    entries = []
    for c in comments:
        entry = parse_comment(c.get("body") or "", int(c.get("id") or 0))
        if entry:
            entries.append(entry)
    return entries


# --------------------------------------------------------------------------- 検索


def _to_halfwidth(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        elif ch == "　":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _to_fullwidth_symbols(s: str) -> str:
    """ASCII 記号だけを全角にする（英数字は PDF 側も半角のことが多いので触らない）。"""
    return "".join(chr(ord(ch) + 0xFEE0) if 0x21 <= ord(ch) <= 0x7E and not ch.isalnum() else ch for ch in s)


def _strip_spaces(s: str) -> str:
    return re.sub(r"\s+", "", s)


def search_variants(term: str) -> list[str]:
    """検索語の候補を、試す順に返す。

    改行は「除去」「空白に置換」の両方を作る（PDF 側で行をまたぐ語は空白扱いでないと一致しない）。
    そのうえで 原文 → 全角↔半角 → 空白除去 → NFKC の順に変える。
    """
    bases = [term.replace("\n", "").strip(), term.replace("\n", " ").strip()]

    def nfkc(s: str) -> str:
        return unicodedata.normalize("NFKC", s)

    transforms = [
        lambda s: s,
        _to_halfwidth,
        _to_fullwidth_symbols,
        lambda s: _strip_spaces(s),
        lambda s: _strip_spaces(_to_halfwidth(s)),
        lambda s: _strip_spaces(_to_fullwidth_symbols(s)),
        nfkc,
        lambda s: _strip_spaces(nfkc(s)),
    ]
    seen: set[str] = set()
    variants: list[str] = []
    for transform in transforms:
        for base in bases:
            v = transform(base)
            if v and v not in seen:
                seen.add(v)
                variants.append(v)
    return variants


def find_hits(page: pymupdf.Page, term: str) -> tuple[str, list[pymupdf.Quad]] | None:
    for variant in search_variants(term):
        quads = page.search_for(variant, quads=True)
        if quads:
            return variant, quads
    return None


# --------------------------------------------------------------------------- 注釈


def _add_note(page: pymupdf.Page, text: str, slot: int) -> None:
    point = pymupdf.Point(page.rect.x0 + NOTE_X, page.rect.y0 + NOTE_X + NOTE_STEP * slot)
    annot = page.add_text_annot(point, text, icon="Note")
    annot.set_info(content=text, title=ANNOT_TITLE)
    annot.update()


def process_entry(
    doc: pymupdf.Document, entry: Entry, offset: int, dry_run: bool, note_slots: Counter[int]
) -> EntryResult:
    """1コメント分の検索と注釈付け。dry_run なら検索だけ行い、注釈は付けない。"""
    res = EntryResult(entry)
    targets: list[tuple[int, int]] = []  # (印刷ページ, PDFのページindex)
    for printed in entry.pages:
        idx = printed + offset - 1
        if 0 <= idx < doc.page_count:
            targets.append((printed, idx))
        else:
            res.warnings.append(
                f"{entry.label}: PDFページ {idx + 1} は範囲外です（全{doc.page_count}ページ）。offset を要確認"
            )
    if not targets:
        return res

    first_idx = targets[0][1]

    if not entry.terms:
        res.warnings.append(f"{entry.label}: 引用がないため、ページに付箋だけ付けます")
        _finish_note(doc, res, entry.note, first_idx, dry_run, note_slots)
        return res

    for term in entry.terms:
        found = False
        for printed, idx in targets:
            page = doc[idx]
            hit = find_hits(page, term)
            if not hit:
                continue
            variant, quads = hit
            found = True
            res.hits.append(Hit(printed, idx + 1, term, variant, len(quads)))
            if not dry_run:
                annot = page.add_highlight_annot(quads=quads)
                if annot is not None:
                    annot.set_info(content=entry.note, title=ANNOT_TITLE)
                    annot.update()
        if not found:
            res.missing.append(term)
            res.warnings.append(f"{entry.label}: 引用が見つかりません: {_short(term)}")

    if res.missing:
        no_text = [idx + 1 for _, idx in targets if not doc[idx].get_text("text").strip()]
        if no_text:
            pages = ", ".join(f"p.{n}" for n in no_text)
            res.warnings.append(f"{entry.label}: PDF {pages} にテキストがありません（画像PDFの可能性。検索できません）")
        missing_text = "\n".join(f"- {t.replace(chr(10), '')}" for t in res.missing)
        text = f"{entry.note}\n\n[未検出の引用]\n{missing_text}".strip()
        _finish_note(doc, res, text, first_idx, dry_run, note_slots)
    return res


def _finish_note(
    doc: pymupdf.Document, res: EntryResult, text: str, idx: int, dry_run: bool, note_slots: Counter[int]
) -> None:
    res.notes += 1
    if not dry_run:
        _add_note(doc[idx], text, note_slots[idx])
        note_slots[idx] += 1


def process_entries(doc: pymupdf.Document, entries: list[Entry], offset: int, dry_run: bool) -> list[EntryResult]:
    note_slots: Counter[int] = Counter()
    return [process_entry(doc, e, offset, dry_run, note_slots) for e in entries]


def _short(text: str, limit: int = 40) -> str:
    flat = text.replace("\n", "")
    return repr(flat if len(flat) <= limit else flat[:limit] + "…")


# --------------------------------------------------------------------------- PDF入出力


def derived_path(pdf: Path, label: str) -> Path:
    """元PDF以外の成果物の名前 `<元ファイル名>_<日本語の名前>.pdf` を作る。"""
    return pdf.with_name(f"{pdf.stem}_{label}.pdf")


def default_out_path(pdf: Path) -> Path:
    return derived_path(pdf, MARKED_LABEL)


def find_pdf(folder: Path) -> Path:
    """folder 直下の元PDFを1つだけ返す。成果物（名前に "_" を含む *_xxx.pdf）は除く。"""
    candidates = sorted(p for p in folder.glob("*.pdf") if "_" not in p.stem)
    if not candidates:
        raise ValueError(f"{folder} に PDF が見つかりません。--pdf で指定してください")
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        raise ValueError(f"{folder} に PDF が複数あります（{names}）。--pdf で指定してください")
    return candidates[0]


def open_pdf(pdf: Path) -> pymupdf.Document:
    doc = pymupdf.open(pdf)
    if doc.needs_pass:
        doc.close()
        raise ValueError(f"{pdf.name} はパスワードが必要なPDFです（空パスワード以外は未対応）")
    return doc


def write_marked_pdf(pdf: Path, out: Path, entries: list[Entry], offset: int) -> list[EntryResult]:
    """元PDFのコピーにコメント由来の注釈を追記して out に保存する。"""
    return write_annotated_copy(pdf, out, lambda doc: process_entries(doc, entries, offset, dry_run=False))


def write_annotated_copy(pdf: Path, out: Path, annotate: Callable[[pymupdf.Document], T]) -> T:
    """元PDFをコピーし、annotate で注釈を追記して、incremental save で out に保存する。

    常に元PDFから作り直すので、再実行しても注釈は重複しない。元PDFは読み取りのみ。
    """
    if out.resolve() == pdf.resolve():
        raise ValueError("--out が元PDFと同じです。元PDFは上書きしません")
    work = out.with_name(out.name + ".tmp")
    rewritten = out.with_name(out.name + ".rewrite.tmp")
    shutil.copyfile(pdf, work)
    try:
        doc = open_pdf(work)
        try:
            results = annotate(doc)
            if doc.can_save_incrementally():
                doc.saveIncr()
            else:
                # 破損修復済み等で追記できない場合のみ、最小限の設定で全体を書き直す
                doc.save(rewritten, garbage=0, deflate=False)
        finally:
            doc.close()
        if rewritten.exists():
            os.replace(rewritten, work)
        os.replace(work, out)
    finally:
        work.unlink(missing_ok=True)
        rewritten.unlink(missing_ok=True)
    return results


# --------------------------------------------------------------------------- CLI


def format_report(results: list[EntryResult], offset: int) -> Iterator[str]:
    for r in results:
        e = r.entry
        pdf_pages = f"{e.first_page + offset}"
        if e.first_page != e.last_page:
            pdf_pages += f"-{e.last_page + offset}"
        yield f"[comment {e.comment_id}] {e.label} (PDF p.{pdf_pages}) 検索語 {len(e.terms)}件"
        for h in r.hits:
            via = "" if h.variant == h.term.replace("\n", "") else f"  (一致した検索語: {_short(h.variant)})"
            yield f"  OK  p.{h.pdf_page}: {_short(h.term)} -> {h.count}箇所{via}"
        for t in r.missing:
            yield f"  NG  {_short(t)} -> 0箇所"
        if not e.terms:
            yield "  --  引用なし"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Issue のコメント（ページ＋引用）をもとに書籍PDFへハイライトを付ける")
    p.add_argument(
        "--pdf",
        type=Path,
        help="対象PDF。省略時はカレントフォルダの元PDF（名前に _ を含まない *.pdf）を1つだけ自動検出",
    )
    p.add_argument("--issue", type=int, default=DEFAULT_ISSUE, help=f"Issue 番号（既定 {DEFAULT_ISSUE}）")
    p.add_argument("--repo", default=DEFAULT_REPO, help=f"owner/repo（既定 {DEFAULT_REPO}）")
    p.add_argument("--offset", type=int, default=0, help="PDFページ = 印刷ページ + offset（既定 0）")
    p.add_argument("--out", type=Path, help="出力先。省略時は <元ファイル名>_コメント付き.pdf（元PDFと同じフォルダ）")
    p.add_argument("--dry-run", action="store_true", help="注釈は付けず、パース結果と検索ヒット数だけ表示する")
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # Windows コンソールで表示できない文字があっても落とさない
    args = build_parser().parse_args(argv)
    try:
        pdf = args.pdf or find_pdf(Path.cwd())
        if not pdf.is_file():
            raise ValueError(f"PDF が見つかりません: {pdf}")
        out = args.out or default_out_path(pdf)

        comments = fetch_comments(args.repo, args.issue)
        entries = parse_comments(comments)
        print(f"PDF: {pdf.name}  /  Issue {args.repo}#{args.issue} (offset={args.offset})")
        print(f"コメント{len(comments)}件中 {len(entries)}件が対象（先頭行がページ番号のもの）")

        if args.dry_run:
            doc = open_pdf(pdf)
            try:
                results = process_entries(doc, entries, args.offset, dry_run=True)
            finally:
                doc.close()
        else:
            results = write_marked_pdf(pdf, out, entries, args.offset)
    except (ValueError, RuntimeError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    for line in format_report(results, args.offset):
        print(line)
    warnings = [w for r in results for w in r.warnings]
    for w in warnings:
        print(f"警告: {w}")
    highlights = sum(len(r.hits) for r in results)
    notes = sum(r.notes for r in results)
    verb = "付ける予定" if args.dry_run else "付けました"
    print(f"ハイライト {highlights}件 / 付箋 {notes}件 {verb}、警告 {len(warnings)}件")
    if not args.dry_run:
        print(f"出力: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
