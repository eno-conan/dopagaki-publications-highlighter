"""contents_page（合体した記事の先頭に入れる、自作の目次ページ）のテスト。"""

from __future__ import annotations

import pymupdf

from contents_page import add_contents_page, article_parts, split_title


def make_pdf(path, pages: int):
    doc = pymupdf.open()
    for n in range(pages):
        doc.new_page(width=400, height=600).insert_text((50, 100), f"page {n + 1}")
    doc.save(path)
    doc.close()


ARTICLE = {
    "id": "p10-19",
    "name": "連載2本",
    "title": "Aの記事 ......山田 太郎+Bの記事",
    "merged": ["p10-12", "p13-19"],
}


def test_parts_from_merged_ids_and_titles():
    parts = article_parts(ARTICLE)
    assert [(p.title, p.author, p.first, p.last, p.pages) for p in parts] == [
        ("Aの記事", "山田 太郎", 10, 12, 3),
        ("Bの記事", "", 13, 19, 7),
    ]


def test_parts_field_takes_priority_over_the_title():
    parts = article_parts({**ARTICLE, "parts": [{"id": "p10-12", "title": "x+y", "first": 10, "last": 12}]})
    assert [p.title for p in parts] == ["x+y"]


def test_split_title():
    assert split_title("題名 ......著者 名") == ("題名", "著者 名")
    assert split_title("題名だけ") == ("題名だけ", "")


def test_contents_page_is_added_with_links(tmp_path):
    pdf = tmp_path / "m.pdf"
    make_pdf(pdf, 10)  # 3 + 7ページ
    assert add_contents_page(pdf, ARTICLE) is True
    doc = pymupdf.open(pdf)
    assert doc.page_count == 11
    # 目次の行は、各記事の先頭ページ（0始まり: 目次が0なので、1 と 4）へ飛ぶ
    assert [link["page"] for link in doc[0].get_links()] == [1, 4]
    assert "p.2" in doc[0].get_text() and "p.5" in doc[0].get_text()
    assert "page 1" in doc[1].get_text()  # 本文は、そのまま後ろに続く


def test_single_article_gets_no_contents_page(tmp_path):
    pdf = tmp_path / "s.pdf"
    make_pdf(pdf, 3)
    assert add_contents_page(pdf, {"name": "1本", "title": "A", "merged": ["p1-3"]}) is False
    assert pymupdf.open(pdf).page_count == 3
