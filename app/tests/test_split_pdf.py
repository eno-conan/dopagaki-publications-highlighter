"""split_pdf のテスト。PDF は pymupdf でその場で生成する。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest

import split_pdf


def make_pdf(path: Path, n_pages: int, toc: list[list] | None = None) -> Path:
    doc = pymupdf.open()
    for i in range(n_pages):
        page = doc.new_page()
        page.insert_text((50, 100), f"page-{i + 1}", fontsize=12)
    if toc:
        doc.set_toc(toc)
    doc.save(path)
    doc.close()
    return path


def test_extract_pages_keeps_range_and_shifts_toc(tmp_path):
    toc = [[1, "前書き", 1], [1, "特集", 3], [2, "第1章", 3], [2, "第2章", 5], [1, "連載", 7]]
    pdf = make_pdf(tmp_path / "book.pdf", 8, toc)
    out = split_pdf.default_out_path(pdf, split_pdf.default_name(3, 6))
    assert out.name == "book_3-6ページ抜粋.pdf"
    assert split_pdf.extract_pages(pdf, 3, 6, out) == 4

    doc = pymupdf.open(out)
    assert [doc[i].get_text().strip() for i in range(4)] == ["page-3", "page-4", "page-5", "page-6"]
    assert [(lvl, title, page) for lvl, title, page in doc.get_toc()] == [
        (1, "特集", 1),
        (2, "第1章", 1),
        (2, "第2章", 3),
    ]
    doc.close()


def test_shift_toc_normalizes_levels_when_range_starts_deep():
    toc = [[1, "A", 1], [3, "深い見出し", 4], [3, "同階層", 5]]
    assert split_pdf.shift_toc(toc, 4, 5) == [[1, "深い見出し", 1], [1, "同階層", 2]]


def test_source_is_not_modified(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", 3)
    before = hashlib.sha256(pdf.read_bytes()).hexdigest()
    split_pdf.extract_pages(pdf, 1, 2, tmp_path / "part.pdf")
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(("first", "last"), [(0, 2), (3, 2), (2, 9)])
def test_invalid_range(tmp_path, first, last):
    pdf = make_pdf(tmp_path / "book.pdf", 3)
    with pytest.raises(ValueError, match="不正"):
        split_pdf.extract_pages(pdf, first, last, tmp_path / "part.pdf")


def test_refuses_to_overwrite_source(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", 3)
    with pytest.raises(ValueError, match="元PDF"):
        split_pdf.extract_pages(pdf, 1, 2, pdf)


def test_main_reports_offset(tmp_path, capsys):
    pdf = make_pdf(tmp_path / "book.pdf", 5)
    assert split_pdf.main(["--pdf", str(pdf), "--first", "2", "--last", "4"]) == 0
    assert (tmp_path / "book_2-4ページ抜粋.pdf").exists()
    assert "切り出し後のページ + 1" in capsys.readouterr().out


def test_main_with_name_makes_japanese_suffix(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", 5)
    assert split_pdf.main(["--pdf", str(pdf), "--first", "2", "--last", "4", "--name", "第1特集"]) == 0
    assert (tmp_path / "book_第1特集.pdf").exists()
