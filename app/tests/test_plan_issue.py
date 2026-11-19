"""plan_issue（号の記事を一覧にして、対象かどうかを記録する）と split_pdf --plan のテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

import plan_issue
import split_pdf

# しおりの形は実際の号に合わせる（子を持つ階層1は区分の見出し、■第N特集は章を含めて1記事、子なしの階層1は1記事）
TOC = [
    [1, "SD2026年10月号", 1],
    [2, "表紙", 1],
    [1, "■第1特集 設計入門", 3],
    [2, "第1章：はじめに", 3],
    [2, "第2章：部品", 4],
    [1, "■連載：Development", 6],
    [2, "サンプル連載【2】ロード戦略 ......山田 太郎", 6],
    [2, "サンプル連載B【8】テーマ ......鈴木 花子", 8],
    [1, "電子版奥付", 10],
]
BODY = "本文です。" * 20  # 100文字


def make_issue(path: Path, garbled_pages: tuple[int, ...] = (), blank_pages: tuple[int, ...] = (1, 2, 10)) -> Path:
    doc = pymupdf.open()
    font = pymupdf.Font("cjk")
    for n in range(1, 11):
        page = doc.new_page()
        if n in blank_pages:
            continue
        page.insert_font(fontname="cjk", fontbuffer=font.buffer)
        text = "ΘΕΔͷ͔ͳͥ" * 20 if n in garbled_pages else BODY
        page.insert_textbox(pymupdf.Rect(30, 30, 560, 800), text, fontname="cjk", fontsize=9)
    doc.set_toc(TOC)
    doc.save(path)
    doc.close()
    return path


def build(tmp_path: Path, **kw) -> list[plan_issue.Article]:
    pdf = make_issue(tmp_path / "号.pdf", **kw)
    doc = pymupdf.open(pdf)
    try:
        return plan_issue.build_articles(doc)
    finally:
        doc.close()


def test_toc_articles_follow_section_rules(tmp_path):
    articles = build(tmp_path)
    assert [(a.id, a.section) for a in articles] == [
        ("p1-2", "SD2026年10月号"),
        ("p3-5", "特集"),
        ("p6-7", "■連載：Development"),
        ("p8-9", "■連載：Development"),
        ("p10", "電子版奥付"),
    ]
    assert [a.pages for a in articles] == [2, 3, 2, 2, 1]


def test_names_are_japanese_series_names(tmp_path):
    names = {a.id: a.name for a in build(tmp_path)}
    assert names["p3-5"] == "第1特集"
    assert names["p6-7"] == "サンプル連載"
    assert names["p8-9"] == "サンプル連載B"


def test_readability_detection(tmp_path):
    ok = {a.id: a.readable for a in build(tmp_path)}
    assert ok["p3-5"] == "ok" and ok["p1-2"] == "none" and ok["p10"] == "none"
    assert {a.id: a.readable for a in build(tmp_path, garbled_pages=(3,))}["p3-5"] == "partial"  # 3ページ中1ページ
    assert {a.id: a.readable for a in build(tmp_path, garbled_pages=(3, 4))}["p3-5"] == "garbled"  # 半分以上


def test_unreadable_articles_are_excluded_automatically(tmp_path):
    articles = plan_issue.merge_decisions(build(tmp_path, garbled_pages=(8, 9)), [])
    by_id = {a.id: a for a in articles}
    assert by_id["p1-2"].target is False and "文字なし" in by_id["p1-2"].note
    assert by_id["p8-9"].target is False and "文字化け" in by_id["p8-9"].note
    assert by_id["p3-5"].target is None  # 読める記事は、人が判断するまで未判断


def test_decisions_survive_rerun(tmp_path):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p6-7", "--exclude", "p3-5"]) == 0
    assert plan_issue.main(["--pdf", str(pdf)]) == 0  # 再実行しても判断は消えない
    plan = json.loads((tmp_path / "articles.json").read_text(encoding="utf-8"))
    targets = {a["id"]: a["target"] for a in plan["articles"]}
    assert targets["p6-7"] is True and targets["p3-5"] is False and targets["p8-9"] is None


def test_split_approval_survives_rerun(tmp_path):
    """分割単位の承認（人の判断）は、一覧を作り直しても、--include/--exclude をしても消えない。"""
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf)]) == 0
    plan_path = tmp_path / "articles.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["split"] = {"unit": "book", "approved": ["p3-5", "p6-7"]}
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    assert plan_issue.main(["--pdf", str(pdf)]) == 0
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5"]) == 0
    after = json.loads(plan_path.read_text(encoding="utf-8"))
    assert after["split"] == {"unit": "book", "approved": ["p3-5", "p6-7"]}


def test_plan_without_split_stays_without_it(tmp_path):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf)]) == 0
    assert "split" not in json.loads((tmp_path / "articles.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 書籍（章単位・合体・手でページ範囲）

BOOK_TOC = [
    [1, "第1章 はじめに", 2],
    [2, "1.1 概要", 2],
    [2, "1.2 詳細", 3],
    [1, "第2章 データモデル", 5],
    [1, "第3章 設計", 8],
    [1, "第4章 運用", 11],
]


def make_book(path: Path, toc: list[list] | None = None) -> Path:
    doc = pymupdf.open()
    font = pymupdf.Font("cjk")
    for n in range(1, 13):
        page = doc.new_page()
        if n == 1:  # 表紙
            continue
        page.insert_font(fontname="cjk", fontbuffer=font.buffer)
        page.insert_textbox(pymupdf.Rect(30, 30, 560, 800), BODY, fontname="cjk", fontsize=9)
    doc.set_toc(BOOK_TOC if toc is None else toc)
    doc.save(path)
    doc.close()
    return path


def read_plan(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "articles.json").read_text(encoding="utf-8"))


def test_book_chapters_come_from_toc_level(tmp_path, capsys):
    pdf = make_book(tmp_path / "本.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book"]) == 0
    plan = read_plan(tmp_path)
    assert [(a["id"], a["name"]) for a in plan["articles"]] == [
        ("p2-4", "第1章はじめに"),
        ("p5-7", "第2章データモデル"),
        ("p8-10", "第3章設計"),
        ("p11-12", "第4章運用"),
    ]
    assert plan["split"] == {"approved": [], "unit": "book"}
    assert all("merged" not in a for a in plan["articles"])  # 合体していなければ項目を出さない
    assert "未承認" in capsys.readouterr().out
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book", "--chapter-level", "2", "--rebuild"]) == 0
    assert [a["name"] for a in read_plan(tmp_path)["articles"]] == ["1.1概要", "1.2詳細"]


def test_book_without_toc_asks_for_ranges(tmp_path, capsys):
    pdf = make_book(tmp_path / "本.pdf", toc=[])
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book"]) == 1
    assert "--ranges" in capsys.readouterr().err


def test_manual_ranges_make_a_book_plan(tmp_path):
    pdf = make_book(tmp_path / "本.pdf", toc=[])
    assert plan_issue.main(["--pdf", str(pdf), "--ranges", "2-6:第1章 データ", "7-12:第2章"]) == 0
    plan = read_plan(tmp_path)
    assert [(a["id"], a["first"], a["last"], a["name"]) for a in plan["articles"]] == [
        ("p2-6", 2, 6, "第1章データ"),
        ("p7-12", 7, 12, "第2章"),
    ]
    assert plan["split"]["unit"] == "book"
    assert plan_issue.main(["--pdf", str(pdf)]) == 0  # 再実行しても、手で指定した範囲を保つ
    assert [a["id"] for a in read_plan(tmp_path)["articles"]] == ["p2-6", "p7-12"]


@pytest.mark.parametrize("spec", ["2-6", "a-b:章", "2-99:章", "6-2:章"])
def test_manual_ranges_reject_bad_specs(tmp_path, capsys, spec):
    pdf = make_book(tmp_path / "本.pdf", toc=[])
    assert plan_issue.main(["--pdf", str(pdf), "--ranges", spec]) == 1
    assert "エラー" in capsys.readouterr().err
    assert not (tmp_path / "articles.json").exists()


def test_manual_ranges_reject_overlap(tmp_path, capsys):
    pdf = make_book(tmp_path / "本.pdf", toc=[])
    assert plan_issue.main(["--pdf", str(pdf), "--ranges", "2-6:A", "6-8:B"]) == 1
    assert "重なって" in capsys.readouterr().err


def test_merge_two_adjacent_chapters_is_kept_on_rerun(tmp_path, capsys):
    pdf = make_book(tmp_path / "本.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book", "--include", "p8-10"]) == 0
    capsys.readouterr()
    assert plan_issue.main(["--pdf", str(pdf), "--merge", "p2-4", "p5-7"]) == 0
    out = capsys.readouterr().out
    assert "警告" not in out  # 2章までは警告にしない
    articles = {a["id"]: a for a in read_plan(tmp_path)["articles"]}
    merged = articles["p2-7"]
    assert (merged["first"], merged["last"], merged["name"]) == (2, 7, "第1章はじめに+第2章データモデル")
    assert merged["merged"] == ["p2-4", "p5-7"] and "合体" in merged["note"]
    assert merged["target"] is None and "p2-4" not in articles
    assert plan_issue.main(["--pdf", str(pdf)]) == 0  # 再実行しても合体と、他の章の判断を保つ
    again = {a["id"]: a for a in read_plan(tmp_path)["articles"]}
    assert "p2-7" in again and again["p8-10"]["target"] is True


def test_merge_over_max_pages_warns_but_is_allowed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(plan_issue, "MAX_PAGES", 8)
    pdf = make_book(tmp_path / "本.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book", "--merge", "p2-4", "p5-7", "p8-10"]) == 0
    out = capsys.readouterr().out
    assert "警告" in out and "p2-10" in out and "3章" in out
    assert read_plan(tmp_path)["articles"][0]["merged"] == ["p2-4", "p5-7", "p8-10"]


def test_merge_chaining_counts_original_chapters(tmp_path, capsys):
    pdf = make_book(tmp_path / "本.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book", "--merge", "p2-4", "p5-7"]) == 0
    assert plan_issue.main(["--pdf", str(pdf), "--merge", "p2-7", "p8-10"]) == 0
    assert "3章" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("ids", "message"),
    [(["p2-4", "p8-10"], "隣接"), (["p5-7", "p2-4"], "隣接"), (["p2-4"], "2つ以上"), (["p2-4", "p999"], "p999")],
)
def test_merge_errors(tmp_path, capsys, ids, message):
    pdf = make_book(tmp_path / "本.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book"]) == 0
    before = (tmp_path / "articles.json").read_text(encoding="utf-8")
    capsys.readouterr()
    assert plan_issue.main(["--pdf", str(pdf), "--merge", *ids]) == 1
    assert message in capsys.readouterr().err
    assert (tmp_path / "articles.json").read_text(encoding="utf-8") == before


def test_merge_works_for_magazines_and_is_kept_on_rerun(tmp_path):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p8-9"]) == 0
    assert plan_issue.main(["--pdf", str(pdf), "--merge", "p3-5", "p6-7"]) == 0
    articles = {a["id"]: a for a in read_plan(tmp_path)["articles"]}
    assert (articles["p3-7"]["first"], articles["p3-7"]["last"]) == (3, 7)
    assert articles["p3-7"]["merged"] == ["p3-5", "p6-7"] and "ranges" not in articles["p3-7"]
    assert plan_issue.main(["--pdf", str(pdf)]) == 0  # 再実行しても、合体と他の判断を保つ
    again = {a["id"]: a for a in read_plan(tmp_path)["articles"]}
    assert "p3-7" in again and "p3-5" not in again and again["p8-9"]["target"] is True


def test_join_makes_one_article_from_separate_ranges(tmp_path, capsys):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--join", "p3-5", "p8-9"]) == 0
    assert "3-5, 8-9（5p）" in capsys.readouterr().out
    articles = read_plan(tmp_path)["articles"]
    joined = next(a for a in articles if a.get("ranges"))
    assert joined["id"] == "p3-9j" and joined["ranges"] == [[3, 5], [8, 9]]
    assert joined["merged"] == ["p3-5", "p8-9"] and joined["highlights"] == "highlights/p3-9j.json"
    assert "p6-7" in [a["id"] for a in articles]  # 間の記事は含めず、そのまま残る
    assert plan_issue.main(["--pdf", str(pdf)]) == 0
    assert any(a.get("ranges") for a in read_plan(tmp_path)["articles"])  # 再実行しても保つ


def test_join_then_merge_neighbour_keeps_gap(tmp_path):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--join", "p3-5", "p8-9"]) == 0
    assert plan_issue.main(["--pdf", str(pdf), "--join", "p3-9j", "p10"]) == 0
    joined = next(a for a in read_plan(tmp_path)["articles"] if a.get("ranges"))
    assert joined["ranges"] == [[3, 5], [8, 9], [10, 10]]


def test_join_errors(tmp_path, capsys):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--join", "p8-9", "p3-5"]) == 1
    assert "順" in capsys.readouterr().err
    assert plan_issue.main(["--pdf", str(pdf), "--join", "p3-5"]) == 1
    assert "2つ以上" in capsys.readouterr().err


def test_joined_article_is_split_with_only_its_pages(tmp_path):
    import split_pdf

    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--join", "p3-5", "p8-9", "--include", "p3-9j"]) == 0
    assert split_pdf.main(["--plan", str(tmp_path / "articles.json")]) == 0
    out = next((tmp_path / "分割").glob("*.pdf"))
    doc = pymupdf.open(out)
    try:
        assert doc.page_count == 5
    finally:
        doc.close()


def test_approval_status_is_reported_but_never_written_by_plan_issue(tmp_path, capsys):
    pdf = make_book(tmp_path / "本.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book"]) == 0
    assert "未承認" in capsys.readouterr().out

    plan_path = tmp_path / "articles.json"
    plan = read_plan(tmp_path)
    plan["split"]["approved"] = [a["id"] for a in plan["articles"]]  # 人がチャットで承認したあと、Claude が書く想定
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    assert plan_issue.main(["--pdf", str(pdf)]) == 0
    assert "承認済み" in capsys.readouterr().out

    assert plan_issue.main(["--pdf", str(pdf), "--merge", "p2-4", "p5-7"]) == 0  # 分け方を変えた
    out = capsys.readouterr().out
    assert "再承認" in out and "p2-7" in out
    after = read_plan(tmp_path)["split"]["approved"]
    assert after == ["p2-4", "p5-7", "p8-10", "p11-12"]  # 承認の記録は書き換えない


def test_magazine_plan_without_split_has_no_approval_line(tmp_path, capsys):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf)]) == 0
    assert "分け方" not in capsys.readouterr().out
    assert "split" not in read_plan(tmp_path)


def test_include_overrides_automatic_exclusion_and_notes_it(tmp_path):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p1-2"]) == 0
    plan = json.loads((tmp_path / "articles.json").read_text(encoding="utf-8"))
    first = plan["articles"][0]
    assert first["target"] is True and "手動で対象" in first["note"]


def test_unknown_id_is_an_error(tmp_path, capsys):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p999"]) == 1
    assert "p999" in capsys.readouterr().err


def test_split_plan_extracts_only_targets(tmp_path):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5", "p8-9"]) == 0
    assert split_pdf.main(["--plan", str(tmp_path / "articles.json")]) == 0
    assert (tmp_path / "分割" / "第1特集.pdf").exists()
    assert (tmp_path / "分割" / "サンプル連載B.pdf").exists()
    assert not (tmp_path / "分割" / "サンプル連載.pdf").exists()
    doc = pymupdf.open(tmp_path / "分割" / "第1特集.pdf")
    assert doc.page_count == 3
    doc.close()


def test_split_plan_only_and_errors(tmp_path, capsys):
    pdf = make_issue(tmp_path / "号.pdf")
    plan = tmp_path / "articles.json"
    assert split_pdf.main(["--plan", str(plan)]) == 1  # 計画がまだ無い
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5", "p6-7"]) == 0
    assert split_pdf.main(["--plan", str(plan), "--only", "p6-7"]) == 0
    assert (tmp_path / "分割" / "サンプル連載.pdf").exists()
    assert not (tmp_path / "分割" / "第1特集.pdf").exists()
    capsys.readouterr()
    assert split_pdf.main(["--plan", str(plan), "--only", "p123"]) == 1
    assert "p123" in capsys.readouterr().err


def test_split_without_range_is_an_error(tmp_path, capsys):
    pdf = make_issue(tmp_path / "号.pdf")
    assert split_pdf.main(["--pdf", str(pdf)]) == 1
    assert "--first" in capsys.readouterr().err


@pytest.mark.parametrize(("text", "expected"), [("本文です", 0.0), ("ΘΕΔ本文", 0.6), ("", 0.0)])
def test_weird_ratio(text, expected):
    assert plan_issue.weird_ratio(text) == pytest.approx(expected)


# ---------------------------------------------------------------- build_issue（まとめて仕上げる）


def write_highlights(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"highlights": items}, ensure_ascii=False), encoding="utf-8")


def test_build_issue_builds_targets_and_skips_unselected(tmp_path, capsys):
    import build_issue

    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5", "p6-7"]) == 0
    write_highlights(tmp_path / "highlights" / "p3-5.json", [{"page": 1, "text": "本文です", "category": "definition"}])
    capsys.readouterr()

    assert build_issue.main(["--plan", str(tmp_path / "articles.json")]) == 0
    out = capsys.readouterr().out
    assert "ハイライト 1/1件" in out and "重要箇所が未選定" in out

    assert (tmp_path / "マーカー付き" / "第1特集.pdf").exists()
    assert (tmp_path / "分割" / "第1特集.pdf").exists()  # 切り出しただけのPDFも残す
    assert not (tmp_path / "highlights" / "p3-5.html").exists()  # HTMLレポートは作らない
    orm = tmp_path / "マーカー付き" / "サンプル連載.pdf"
    assert not orm.exists()  # 未選定の記事は何も作らない
    # 再実行しても注釈は重複しない
    assert build_issue.main(["--plan", str(tmp_path / "articles.json")]) == 0
    doc = pymupdf.open(tmp_path / "マーカー付き" / "第1特集.pdf")
    assert sum(len(list(p.annots())) for p in doc) == 1
    doc.close()


def test_build_issue_fails_when_a_highlight_does_not_match(tmp_path, capsys):
    import build_issue

    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5"]) == 0
    write_highlights(
        tmp_path / "highlights" / "p3-5.json", [{"page": 1, "text": "存在しない文", "category": "definition"}]
    )
    assert build_issue.main(["--plan", str(tmp_path / "articles.json")]) == 1
    assert "未適用 1件" in capsys.readouterr().out


def test_build_issue_errors(tmp_path, capsys):
    import build_issue

    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf)]) == 0
    assert build_issue.main(["--plan", str(tmp_path / "articles.json")]) == 1  # 対象が無い
    assert "対象の記事がありません" in capsys.readouterr().err
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5"]) == 0
    assert build_issue.main(["--plan", str(tmp_path / "articles.json"), "--only", "p999"]) == 1
    assert "p999" in capsys.readouterr().err


def test_article_outputs_go_to_kind_folders_and_do_not_confuse_find_pdf(tmp_path):
    import build_issue
    from mark_pdf import find_pdf

    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5"]) == 0
    article = {"id": "p3-5", "name": "第1特集", "first": 3, "last": 5}
    assert split_pdf.markers_path(tmp_path, article) == tmp_path / "マーカー付き" / "第1特集.pdf"
    assert split_pdf.excerpt_path(tmp_path, article) == tmp_path / "分割" / "第1特集.pdf"
    assert build_issue.main(["--plan", str(tmp_path / "articles.json")]) == 0
    assert not list(tmp_path.glob("号_*.pdf"))  # 直下には元PDF以外を出さない
    assert find_pdf(tmp_path) == pdf


def test_build_issue_whole_pdf_as_one_article_with_original_in_subfolder(tmp_path):
    import build_issue

    folder = tmp_path / "全文"
    folder.mkdir()
    pdf = make_issue(folder / "original.pdf")
    plan = tmp_path / "articles.json"
    assert plan_issue.main(["--pdf", str(pdf), "--out", str(plan), "--ranges", "1-10:全文"]) == 0
    assert json.loads(plan.read_text(encoding="utf-8"))["pdf"] == "全文/original.pdf"
    assert plan_issue.main(["--pdf", str(pdf), "--out", str(plan), "--include", "p1-10"]) == 0
    item = {"page": 3, "text": "本文です", "category": "definition"}
    write_highlights(tmp_path / "highlights" / "p1-10.json", [item])
    assert build_issue.main(["--plan", str(plan)]) == 0
    assert (tmp_path / "マーカー付き" / "全文.pdf").exists()
    assert (tmp_path / "分割" / "全文.pdf").exists()
    assert sorted(p.name for p in folder.iterdir()) == ["original.pdf"]


def test_build_issue_rejects_duplicate_article_names(tmp_path, capsys):
    import build_issue

    pdf = make_issue(tmp_path / "号.pdf")
    plan = tmp_path / "articles.json"
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5", "p6-7"]) == 0
    data = json.loads(plan.read_text(encoding="utf-8"))
    for a in data["articles"]:
        a["name"] = "同じ名前"
    plan.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert build_issue.main(["--plan", str(plan)]) == 1
    assert "重複" in capsys.readouterr().err


def test_safe_filename_replaces_unusable_characters_and_spaces_with_hyphens():
    assert split_pdf.safe_filename("Redesigning source control") == "Redesigning-source-control"
    assert split_pdf.safe_filename('a/b:c*d?e"f<g>h|i\\j') == "a-b-c-d-e-f-g-h-i-j"
    assert split_pdf.safe_filename("  前  後  ") == "前-後"  # 続くスペースは1つのハイフン、両端は落とす
    assert split_pdf.safe_filename("a - b") == "a-b"
    assert split_pdf.safe_filename("..名前.") == "名前"
    assert split_pdf.safe_filename("1章 +AI：生成AI？") == "1章-+AI：生成AI？"  # 全角はそのまま
    assert split_pdf.safe_filename("???") == "article"


def test_build_issue_rejects_names_that_become_the_same_filename(tmp_path, capsys):
    import build_issue

    pdf = make_issue(tmp_path / "号.pdf")
    plan = tmp_path / "articles.json"
    assert plan_issue.main(["--pdf", str(pdf), "--include", "p3-5", "p6-7"]) == 0
    data = json.loads(plan.read_text(encoding="utf-8"))
    names = iter(["A B", "A-B"])
    for a in data["articles"]:
        if a["target"]:
            a["name"] = next(names)
    plan.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert build_issue.main(["--plan", str(plan)]) == 1
    assert "重複" in capsys.readouterr().err


def make_chapter_book(path: Path, sizes: list[tuple[str, int]]) -> Path:
    """sizes = [(しおりの題, ページ数)]。各ページに十分な文字を入れた書籍PDF。"""
    doc = pymupdf.open()
    font = pymupdf.Font("cjk")
    toc, page = [], 1
    for title, n in sizes:
        toc.append([1, title, page])
        for _ in range(n):
            p = doc.new_page()
            p.insert_font(fontname="cjk", fontbuffer=font.buffer)
            p.insert_textbox(pymupdf.Rect(30, 30, 560, 800), BODY, fontname="cjk", fontsize=9)
        page += n
    doc.set_toc(toc)
    doc.save(path)
    return path


def test_auto_merge_groups_short_chapters_until_30_pages(tmp_path, capsys):
    sizes = [
        ("目次", 3),
        ("第1章　A", 12),
        ("第2章　B", 12),
        ("第3章　C", 12),
        ("第4章　D", 40),
        ("第5章　E", 5),  # 最後で短い → 直前の単位にまとめる
        ("索引", 4),
    ]
    pdf = make_chapter_book(tmp_path / "本.pdf", sizes)
    assert plan_issue.main(["--pdf", str(pdf), "--unit", "book", "--auto-merge"]) == 0
    arts = read_plan(tmp_path)["articles"]
    assert [(a["first"], a["last"]) for a in arts] == [(1, 3), (4, 39), (40, 84), (85, 88)]
    names = [a["name"] for a in arts]
    assert names == [
        "目次",
        "第1章〜第3章",
        "第4章〜第5章",
        "索引",
    ]  # 40+5ページは直前にまとめる / 索引・目次は足さない
    assert arts[1]["merged"] and arts[2]["merged"] and not arts[0].get("merged")


def test_auto_merge_is_only_for_books(tmp_path, capsys):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf), "--auto-merge"]) == 1


def test_matter_words_and_blank_pages():
    a = plan_issue.Article("p1", "Appendix　付録", "章", 1, 5, 1000, "ok")
    assert plan_issue.is_matter(a)
    assert not plan_issue.is_matter(
        plan_issue.Article("p6", "第1章　はじめに", "章", 6, 9, 1000, "ok", merged=["p6", "p7"])
    )
    assert plan_issue.is_blank(plan_issue.Article("p9", "第1部", "章", 9, 9, 40, "ok"))


def test_short_article_notice_is_only_for_books(tmp_path, capsys):
    pdf = make_issue(tmp_path / "号.pdf")
    assert plan_issue.main(["--pdf", str(pdf)]) == 0  # 雑誌: 短い記事ばかりでも、30ページ未満の注意は出ない
    assert "30ページ未満" not in capsys.readouterr().out


def test_dedupe_ids_for_bookmarks_on_the_same_page():
    mk = lambda t, f, last: plan_issue.Article(plan_issue.article_id(f, last), t, "章", f, last, 500, "ok")  # noqa: E731
    arts = plan_issue.dedupe_ids([mk("参考Web情報", 353, 353), mk("著者プロフィール", 353, 353), mk("索引", 354, 359)])
    assert [a.id for a in arts] == ["p353", "p353b", "p354-359"]
    assert arts[1].highlights == "highlights/p353b.json"  # 重要箇所のファイルも、IDに合わせる


def test_front_and_back_matter_words_cover_about_the_book_and_profile():
    for title in ("本書について", "参考Web情報", "著者プロフィール"):
        assert plan_issue.is_matter(plan_issue.Article("p1", title, "章", 1, 1, 500, "ok"))
