"""apply_highlights のテスト。PDF は pymupdf でその場で生成する。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

import apply_highlights as ah


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


def write_json(path: Path, items: list[dict]) -> Path:
    path.write_text(json.dumps({"highlights": items}, ensure_ascii=False), encoding="utf-8")
    return path


def annots(pdf: Path, page_no: int) -> list[pymupdf.Annot]:
    doc = pymupdf.open(pdf)
    try:
        return [(a.type[0], a.info["content"], a.colors["stroke"]) for a in doc[page_no - 1].annots()]
    finally:
        doc.close()


def run(pdf: Path, items: list[dict]) -> list[ah.HighlightResult]:
    highlights = ah.load_highlights(write_json(pdf.parent / "h.json", items))
    doc = pymupdf.open(pdf)
    try:
        return ah.apply_highlights(doc, highlights, dry_run=True)
    finally:
        doc.close()


@pytest.mark.parametrize(
    ("pdf_lines", "text"),
    [
        (["設計に銀の弾丸はありません"], "設計に銀の弾丸はありません"),
        (["設計に銀の弾", "丸はありません"], "設計に銀の弾丸はありません"),  # 行の途中で折り返し
        (["モデルを取り巻くソフト", "ウェアの足場"], "モデルを取り巻くソフト\nウェアの足場"),  # 改行位置が同じ
        (["Agent＝Model＋Harness"], "Agent=Model+Harness"),  # 全角→半角
        (["Agent=Model+Harness"], "Agent＝Model＋Harness"),  # 半角→全角
        (["Agent ＝ Model"], "Agent＝Model"),  # 空白の有無
    ],
)
def test_text_matches_across_wraps_and_widths(tmp_path, pdf_lines, text):
    pdf = make_pdf(tmp_path / "b.pdf", [pdf_lines])
    [res] = run(pdf, [{"page": 1, "text": text, "category": "definition"}])
    assert res.applied and res.found == 1


def test_wrapped_text_is_highlighted_per_line(tmp_path):
    pdf = make_pdf(tmp_path / "b.pdf", [["前置き 設計に銀の弾", "丸はありません 後ろ"]])
    [res] = run(pdf, [{"page": 1, "text": "設計に銀の弾丸はありません", "category": "warning"}])
    assert res.lines == 2


def test_apply_adds_colored_highlight_without_comment(tmp_path):
    pdf = make_pdf(tmp_path / "b.pdf", [["無関係"], ["定義文です。ここが重要。"]])
    hjson = write_json(
        tmp_path / "h.json",
        [{"page": 2, "text": "ここが重要", "category": "warning", "reason": "限界の指摘", "check": "本文と一致"}],
    )
    out = tmp_path / "out.pdf"
    results = ah.write_annotated_copy(
        pdf, out, lambda doc: ah.apply_highlights(doc, ah.load_highlights(hjson), dry_run=False)
    )
    assert results[0].applied
    [(kind, content, color)] = annots(out, 2)
    assert kind == pymupdf.PDF_ANNOT_HIGHLIGHT
    assert content == ""
    assert tuple(round(c, 2) for c in color) == tuple(round(c, 2) for c in ah.GROUPS["warn"].color)
    assert annots(out, 1) == []


def test_rerun_is_idempotent_and_source_untouched(tmp_path):
    pdf = make_pdf(tmp_path / "b.pdf", [["重要な一文です"]])
    before = hashlib.sha256(pdf.read_bytes()).hexdigest()
    hjson = write_json(tmp_path / "h.json", [{"page": 1, "text": "重要な一文", "category": "definition"}])
    out = ah.default_out_path(pdf)
    assert out.name == "b_重要箇所.pdf"
    for _ in range(2):
        assert ah.main(["--pdf", str(pdf), "--highlights", str(hjson)]) == 0
    assert len(annots(out, 1)) == 1
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == before


def test_not_found_out_of_range_and_no_text_are_reported(tmp_path):
    pdf = make_pdf(tmp_path / "b.pdf", [["本文だけ"], []])
    results = run(
        pdf,
        [
            {"page": 1, "text": "存在しない文", "category": "definition"},
            {"page": 9, "text": "本文", "category": "definition"},
            {"page": 2, "text": "本文", "category": "definition"},
        ],
    )
    assert [r.applied for r in results] == [False, False, False]
    assert "見つかりません" in results[0].warning
    assert "範囲外" in results[1].warning
    assert "テキストがありません" in results[2].warning


def test_occurrence_selects_nth_match(tmp_path):
    pdf = make_pdf(tmp_path / "b.pdf", [["同じ語がある", "ここにも同じ語がある"]])
    first, second, third = run(
        pdf,
        [
            {"page": 1, "text": "同じ語", "category": "definition"},
            {"page": 1, "text": "同じ語", "category": "definition", "occurrence": 2},
            {"page": 1, "text": "同じ語", "category": "definition", "occurrence": 3},
        ],
    )
    assert first.found == 2 and first.applied and first.rects[0].y0 < second.rects[0].y0
    assert second.applied
    assert not third.applied and "occurrence" in third.warning


def test_load_rejects_bad_category_and_empty_text(tmp_path):
    with pytest.raises(ValueError, match="category"):
        ah.load_highlights(write_json(tmp_path / "a.json", [{"page": 1, "text": "x", "category": "nope"}]))
    with pytest.raises(ValueError, match="text が空"):
        ah.load_highlights(write_json(tmp_path / "b.json", [{"page": 1, "text": "  ", "category": "definition"}]))
    with pytest.raises(ValueError, match="不正"):
        ah.load_highlights(write_json(tmp_path / "c.json", [{"text": "x"}]))


def test_dry_run_writes_nothing(tmp_path, capsys):
    pdf = make_pdf(tmp_path / "b.pdf", [["重要な一文です"]])
    hjson = write_json(tmp_path / "h.json", [{"page": 1, "text": "重要な一文", "category": "principle"}])
    assert ah.main(["--pdf", str(pdf), "--highlights", str(hjson), "--dry-run"]) == 0
    assert "ハイライト 1/1件" in capsys.readouterr().out
    assert not ah.default_out_path(pdf).exists()


def test_default_out_name_for_original_and_derived_pdf(tmp_path):
    assert ah.default_out_path(tmp_path / "雑誌.pdf").name == "雑誌_重要箇所.pdf"
    assert ah.default_out_path(tmp_path / "雑誌_第1特集.pdf").name == "雑誌_第1特集の重要箇所.pdf"
