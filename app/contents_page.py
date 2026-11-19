"""合体した記事の「マーカー付きPDF」の先頭に、自作の目次ページを1枚入れる。

雑誌の連載を何本かまとめたPDF（`p104-145` など）は、どこから何の記事かが分かりにくい。そこで、元の記事ごとに、
題名・元のページ・このPDFの中のページ番号を並べた目次ページを、先頭に足す（行をクリックすると、その記事へ飛ぶ）。

目次ページを足すのは `マーカー付き/` のPDFだけ。`分割/` の切り出しPDFと、重要箇所JSONの `page`（切り出しPDFのページ）は
そのままなので、目次の分だけ番号がずれる心配はない。日本語は、PDFに組み込まれていない標準の日本語フォント（`japan`）で描く。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from mark_pdf import write_annotated_copy

ID_PAGES = re.compile(r"^p(\d+)(?:-(\d+))?")
TITLE_AUTHOR = re.compile(r"\s*\.{3,}\s*")
MARGIN = 56.0
GRAY = (0.4, 0.4, 0.4)
LINK_BLUE = (0.1, 0.25, 0.6)


@dataclass
class Part:
    title: str
    author: str
    first: int  # 元PDFのページ
    last: int

    @property
    def pages(self) -> int:
        return self.last - self.first + 1


def split_title(raw: str) -> tuple[str, str]:
    """「題名 ......著者」を、題名と著者に分ける。"""
    pieces = TITLE_AUTHOR.split(raw.strip(), maxsplit=1)
    return pieces[0].strip(), (pieces[1].strip() if len(pieces) > 1 else "")


def article_parts(article: dict) -> list[Part]:
    """合体した記事の、元の記事の並び。`parts` があればそれを、なければ `merged` のIDと題名（`+` 区切り）から作る。"""
    raw: list[dict] = list(article.get("parts") or [])
    if not raw:
        ids = article.get("merged") or []
        titles = str(article.get("title", "")).split("+")
        raw = [{"id": i, "title": titles[n] if len(titles) == len(ids) else i} for n, i in enumerate(ids)]
    parts: list[Part] = []
    for p in raw:
        if "first" in p and "last" in p:
            first, last = int(p["first"]), int(p["last"])
        else:
            m = ID_PAGES.match(str(p.get("id", "")))
            if not m:
                continue
            first = int(m.group(1))
            last = int(m.group(2) or first)
        title, author = split_title(str(p.get("title", p.get("id", ""))))
        parts.append(Part(title, author, first, last))
    return parts


# --------------------------------------------------------------------------- 描画


def _font(ch: str) -> str:
    return "helv" if ord(ch) < 0x80 else "japan"  # 英数字は helv（japan だと全角幅に広がる）


def _runs(text: str) -> list[tuple[str, str]]:
    runs: list[tuple[str, str]] = []
    for ch in text:
        font = _font(ch)
        if runs and runs[-1][0] == font:
            runs[-1] = (font, runs[-1][1] + ch)
        else:
            runs.append((font, ch))
    return runs


def text_width(text: str, size: float) -> float:
    return sum(pymupdf.get_text_length(t, fontname=f, fontsize=size) for f, t in _runs(text))


def draw(page: pymupdf.Page, x: float, y: float, text: str, size: float, color=(0, 0, 0)) -> None:
    """英数字と日本語で字体を切り替えながら、1行描く（y は文字の下端）。"""
    for font, run in _runs(text):
        page.insert_text((x, y), run, fontname=font, fontsize=size, color=color)
        x += pymupdf.get_text_length(run, fontname=font, fontsize=size)


def wrap(text: str, size: float, width: float) -> list[str]:
    """幅に収まるように、1文字ずつ数えて折り返す。"""
    lines, cur = [], ""
    for ch in text:
        if cur and text_width(cur + ch, size) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    return [*lines, cur] if cur else lines or [""]


def draw_contents(page: pymupdf.Page, name: str, parts: list[Part], starts: list[int | None]) -> None:
    """目次ページに描き、各行に、その記事の先頭ページへ飛ぶリンクを付ける。"""
    width, height = page.rect.width, page.rect.height
    inner = width - MARGIN * 2
    draw(page, MARGIN, MARGIN + 18, "目次", 22)
    draw(page, MARGIN, MARGIN + 38, name, 10, GRAY)
    page.draw_line((MARGIN, MARGIN + 48), (width - MARGIN, MARGIN + 48), color=GRAY, width=0.6)

    for size in (13, 12, 11, 10, 9, 8):  # 収まる大きさを探す
        title_w = inner - 56
        rows = [wrap(p.title, size, title_w) for p in parts]
        total = sum(len(r) * (size + 4) + (size + 2) + 10 for r in rows)
        if MARGIN + 70 + total <= height - MARGIN:
            break
    y = MARGIN + 74
    for part, lines, start in zip(parts, rows, starts, strict=True):
        top = y - size
        for line in lines:
            draw(page, MARGIN, y, line, size)
            y += size + 4
        if start is not None:
            label = f"p.{start + 1}"
            draw(page, width - MARGIN - text_width(label, size), top + size, label, size, LINK_BLUE)
        pages = (
            f"元の p.{part.first}" + (f"-{part.last}" if part.last != part.first else "") + f"（{part.pages}ページ）"
        )
        sub = f"{part.author}　{pages}" if part.author else pages
        draw(page, MARGIN, y, sub, size - 2, GRAY)
        y += size + 2
        if start is not None:
            page.insert_link(
                {
                    "kind": pymupdf.LINK_GOTO,
                    "from": pymupdf.Rect(MARGIN, top, width - MARGIN, y),
                    "page": start,
                    "to": pymupdf.Point(0, 0),
                }
            )
        y += 10


def add_contents_page(pdf: Path, article: dict) -> bool:
    """pdf の先頭に目次ページを足す（元の記事が2本未満なら、何もしない）。足したら True。"""
    parts = article_parts(article)
    if len(parts) < 2:
        return False
    tmp = pdf.with_name(pdf.name + ".contents.tmp")

    def annotate(doc: pymupdf.Document) -> bool:
        first = doc[0].rect
        starts: list[int | None] = []
        at = 1  # 目次ページが0なので、最初の記事は1（0始まり）
        consistent = sum(p.pages for p in parts) == doc.page_count
        for p in parts:
            starts.append(at if consistent else None)
            at += p.pages
        page = doc.new_page(0, width=first.width, height=first.height)
        draw_contents(page, str(article.get("name") or article.get("title") or ""), parts, starts)
        return True

    try:
        write_annotated_copy(pdf, tmp, annotate)
        os.replace(tmp, pdf)
    finally:
        tmp.unlink(missing_ok=True)
    return True
