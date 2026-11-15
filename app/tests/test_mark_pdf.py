"""mark_pdf のテスト。PDF は pymupdf でその場で生成するので、実PDFやネットワークは不要。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

import mark_pdf

# Issue #526 の実コメント（1つ目は全角の「＝」「＋」、2つ目は行をまたぐ引用）
COMMENT_EQ = """P20
サンプルの定義
> [!IMPORTANT]
> 「Agent＝Model＋Harness」

https://example.com/sample
（2026年1月1日）"""

COMMENT_WRAPPED = """P20
サンプルを提供する会社
> [!IMPORTANT]
> 視点からサンプルを「モデルを取り巻くソフト
ウェアの足場（scaffolding）」と定義しています
"""


def make_pdf(path: Path, pages: list[list[str]]) -> Path:
    """pages[i] の各要素を、i+1 ページ目に1行ずつ書いたPDFを作る。空リストは文字なしページ。"""
    doc = pymupdf.open()
    font = pymupdf.Font("cjk")
    for lines in pages:
        page = doc.new_page()
        page.insert_font(fontname="cjk", fontbuffer=font.buffer)
        for i, line in enumerate(lines):
            page.insert_text((50, 100 + 20 * i), line, fontname="cjk", fontsize=12)
    doc.save(path)
    doc.close()
    return path


def annots_of(pdf: Path, page_no: int) -> list[tuple[int, str]]:
    doc = pymupdf.open(pdf)
    try:
        return [(a.type[0], a.info["content"]) for a in doc[page_no - 1].annots()]
    finally:
        doc.close()


def run(pdf: Path, bodies: list[str], offset: int = 0, tmp: Path | None = None):
    entries = [e for i, b in enumerate(bodies) if (e := mark_pdf.parse_comment(b, i + 1))]
    out = (tmp or pdf.parent) / "out.pdf"
    results = mark_pdf.write_marked_pdf(pdf, out, entries, offset)
    return out, results


HIGHLIGHT = pymupdf.PDF_ANNOT_HIGHLIGHT
TEXT = pymupdf.PDF_ANNOT_TEXT


# ---------------------------------------------------------------- パース


def test_parse_issue_comment_with_alert_and_brackets():
    e = mark_pdf.parse_comment(COMMENT_EQ, 1)
    assert e is not None
    assert (e.first_page, e.last_page) == (20, 20)
    assert e.terms == ["Agent＝Model＋Harness"]
    assert "[!IMPORTANT]" not in e.note
    assert "サンプルの定義" in e.note


def test_parse_wrapped_quote_keeps_inner_text_of_brackets():
    e = mark_pdf.parse_comment(COMMENT_WRAPPED, 2)
    assert e is not None
    assert e.terms == ["モデルを取り巻くソフト\nウェアの足場（scaffolding）"]


@pytest.mark.parametrize(
    ("first_line", "expected"),
    [("P20", (20, 20)), ("p.20", (20, 20)), ("P20-22", (20, 22)), ("P20〜22", (20, 22)), ("Ｐ２０", (20, 20))],
)
def test_parse_page_formats(first_line, expected):
    e = mark_pdf.parse_comment(f"{first_line}\n> 引用", 1)
    assert e is not None
    assert (e.first_page, e.last_page) == expected


def test_parse_quote_without_brackets_uses_whole_quote():
    e = mark_pdf.parse_comment("P3\n> 一行目\n> 二行目", 1)
    assert e is not None
    assert e.terms == ["一行目\n二行目"]


@pytest.mark.parametrize("body", ["メモです\n> 「引用」", "", "20\n> 引用", "Page 20\n> 引用"])
def test_parse_ignores_comments_without_page_line(body):
    assert mark_pdf.parse_comment(body) is None


def test_parse_json_stream_concatenated_arrays():
    assert mark_pdf.parse_json_stream('[{"a": 1}]\n[{"b": 2}, {"c": 3}]') == [{"a": 1}, {"b": 2}, {"c": 3}]


# ---------------------------------------------------------------- 検索・ハイライト


@pytest.mark.parametrize(
    ("pdf_text", "quote"),
    [
        ("Agent＝Model＋Harness とは", "「Agent＝Model＋Harness」"),  # 全角 / 全角
        ("Agent=Model+Harness とは", "「Agent＝Model＋Harness」"),  # PDFが半角、コメントが全角
        ("Agent＝Model＋Harness とは", "「Agent=Model+Harness」"),  # PDFが全角、コメントが半角
        ("Agent=Model+Harness とは", "「Agent=Model+Harness」"),  # 半角 / 半角
    ],
)
def test_highlight_fullwidth_and_halfwidth(tmp_path, pdf_text, quote):
    pdf = make_pdf(tmp_path / "book.pdf", [["表紙"], [pdf_text]])
    out, results = run(pdf, [f"P2\n見出し\n> {quote}"], tmp=tmp_path)
    assert [a[0] for a in annots_of(out, 2)] == [HIGHLIGHT]
    assert "見出し" in annots_of(out, 2)[0][1]  # ポップアップにコメント本文が入る
    assert results[0].missing == []
    assert results[0].warnings == []


def test_highlight_quote_wrapped_across_lines(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [["モデルを取り巻くソフト", "ウェアの足場（scaffolding）と定義"]])
    out, results = run(pdf, [COMMENT_WRAPPED.replace("P20", "P1")])
    assert [a[0] for a in annots_of(out, 1)] == [HIGHLIGHT]
    assert results[0].missing == []


def test_page_range_searches_each_page(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [["無関係"], ["前半 Agent＝Model＋Harness"], ["別の話"]])
    out, results = run(pdf, ["P1-3\n> 「Agent＝Model＋Harness」"])
    assert [a[0] for a in annots_of(out, 2)] == [HIGHLIGHT]
    assert annots_of(out, 1) == [] and annots_of(out, 3) == []
    assert results[0].hits[0].pdf_page == 2


def test_offset_shifts_pdf_page(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [["表紙"], ["目次"], ["本文 Agent＝Model＋Harness"]])
    out, _ = run(pdf, [COMMENT_EQ.replace("P20", "P1")], offset=2)
    assert [a[0] for a in annots_of(out, 3)] == [HIGHLIGHT]


# ---------------------------------------------------------------- 見つからない場合


def test_not_found_adds_sticky_note_and_warns(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [["まったく別の文章です"]])
    out, results = run(pdf, [COMMENT_EQ.replace("P20", "P1")])
    kinds = annots_of(out, 1)
    assert [k[0] for k in kinds] == [TEXT]
    assert "サンプルの定義" in kinds[0][1]
    assert "Agent＝Model＋Harness" in kinds[0][1]
    assert results[0].missing == ["Agent＝Model＋Harness"]
    assert any("見つかりません" in w for w in results[0].warnings)


def test_image_only_page_warns_and_adds_note(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [[]])
    out, results = run(pdf, [COMMENT_EQ.replace("P20", "P1")])
    assert [a[0] for a in annots_of(out, 1)] == [TEXT]
    assert any("画像PDF" in w for w in results[0].warnings)


def test_multiple_notes_on_one_page_do_not_overlap(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [["本文"]])
    out, _ = run(pdf, ["P1\n> 「無い１」", "P1\n> 「無い２」"])
    doc = pymupdf.open(out)
    ys = sorted(a.rect.y0 for a in doc[0].annots())
    doc.close()
    assert len(ys) == 2 and ys[1] - ys[0] >= mark_pdf.NOTE_STEP - 1


def test_page_out_of_range_warns(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [["本文"]])
    out, results = run(pdf, ["P5\n> 「本文」"])
    assert annots_of(out, 1) == []
    assert any("範囲外" in w for w in results[0].warnings)


# ---------------------------------------------------------------- 出力・冪等性・dry-run


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_untouched_and_rerun_is_idempotent(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [["Agent＝Model＋Harness"]])
    before = sha(pdf)
    bodies = [COMMENT_EQ.replace("P20", "P1")]
    out, _ = run(pdf, bodies)
    first = annots_of(out, 1)
    out, _ = run(pdf, bodies)  # 同じコメントで再実行
    assert annots_of(out, 1) == first
    assert len(first) == 1
    assert sha(pdf) == before
    assert not list(tmp_path.glob("*.tmp"))


def test_refuses_to_overwrite_source(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", [["本文"]])
    with pytest.raises(ValueError, match="元PDF"):
        mark_pdf.write_marked_pdf(pdf, pdf, [], 0)


def test_default_out_name_and_pdf_autodetect(tmp_path):
    pdf = make_pdf(tmp_path / "雑誌 2026年10月号.pdf", [["本文"]])
    assert mark_pdf.default_out_path(pdf).name == "雑誌 2026年10月号_コメント付き.pdf"
    assert mark_pdf.find_pdf(tmp_path) == pdf
    mark_pdf.default_out_path(pdf).write_bytes(b"x")  # 出力済みの成果物（名前に _ を含む）は候補に数えない
    assert mark_pdf.find_pdf(tmp_path) == pdf
    make_pdf(tmp_path / "other.pdf", [["本文"]])
    with pytest.raises(ValueError, match="複数"):
        mark_pdf.find_pdf(tmp_path)


def test_find_pdf_none(tmp_path):
    with pytest.raises(ValueError, match="見つかりません"):
        mark_pdf.find_pdf(tmp_path)


def test_dry_run_reports_hits_without_writing(tmp_path, monkeypatch, capsys):
    pdf = make_pdf(tmp_path / "book.pdf", [["Agent=Model+Harness"]])
    comments = [{"id": 7, "body": COMMENT_EQ.replace("P20", "P1")}, {"id": 8, "body": "ただの雑談"}]
    monkeypatch.setattr(mark_pdf, "fetch_comments", lambda repo, issue: comments)
    assert mark_pdf.main(["--pdf", str(pdf), "--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "コメント2件中 1件" in text
    assert "OK  p.1" in text and "1箇所" in text
    assert annots_of(pdf, 1) == []
    assert not mark_pdf.default_out_path(pdf).exists()


def test_main_writes_marked_pdf(tmp_path, monkeypatch, capsys):
    pdf = make_pdf(tmp_path / "book.pdf", [["Agent＝Model＋Harness"]])
    comments = [{"id": 7, "body": COMMENT_EQ.replace("P20", "P1")}]
    monkeypatch.setattr(mark_pdf, "fetch_comments", lambda repo, issue: comments)
    assert mark_pdf.main(["--pdf", str(pdf)]) == 0
    assert [a[0] for a in annots_of(tmp_path / "book_コメント付き.pdf", 1)] == [HIGHLIGHT]
    assert "ハイライト 1件" in capsys.readouterr().out


def test_parse_lazy_continuation_stops_at_url_and_blank_line():
    e = mark_pdf.parse_comment("P3\n> 前半\n後半\nhttps://example.com/a\n\n本文メモ", 1)
    assert e is not None
    assert e.terms == ["前半\n後半"]
