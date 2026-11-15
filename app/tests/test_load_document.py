"""構造化した JSON（meta / references / verification）の読み込みのテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import apply_highlights as ah

META = {
    "title": "テスト用レポート",
    "source_pdf": "book.pdf",
    "page_offset": 30,
    "references": [
        {
            "id": "lc",
            "name": "LangChain記事",
            "url": "https://example.com/lc?a=1&b=2",
            "checked": "定義を確認",
            "result": "verified",
        },
        {
            "id": "nolima",
            "name": "NoLiMa",
            "url": "https://example.com/nolima",
            "checked": "要旨のみ確認",
            "result": "partial",
        },
    ],
}
ITEMS = [
    {
        "page": 4,
        "text": "Agent＝Model＋Harness",
        "category": "definition",
        "reason": "定義",
        "verification": "verified",
        "refs": ["lc"],
        "check": "一致を確認",
    },
    {"page": 4, "text": "<script>alert(1)</script>", "category": "warning", "reason": "XSS & escape"},
    {
        "page": 9,
        "text": "13個のモデルを測った",
        "category": "evidence",
        "verification": "partial",
        "refs": ["nolima"],
    },
]


def write_doc(tmp_path: Path, meta: dict | None = META, items: list[dict] = ITEMS) -> Path:
    path = tmp_path / "h.json"
    path.write_text(
        json.dumps(
            {"meta": meta, "highlights": items} if meta is not None else {"highlights": items}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return path


def test_load_document_reads_meta_references_and_verification(tmp_path):
    doc = ah.load_document(write_doc(tmp_path))
    assert (doc.title, doc.page_offset) == ("テスト用レポート", 30)
    assert [r.id for r in doc.references] == ["lc", "nolima"]
    assert [h.verification for h in doc.highlights] == ["verified", "", "partial"]
    assert doc.highlights[0].refs == ["lc"]


def test_meta_is_optional(tmp_path):
    doc = ah.load_document(write_doc(tmp_path, meta=None, items=[{"page": 1, "text": "x", "category": "definition"}]))
    assert doc.page_offset is None and doc.references == []


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"verification": "maybe"}, "verification"),
        ({"verification": "unverified"}, "verification"),  # 未照合・照合なしの印は廃止
        ({"refs": ["missing"]}, "meta.references"),
    ],
)
def test_load_rejects_bad_verification_and_unknown_refs(tmp_path, patch, message):
    items = [{"page": 1, "text": "x", "category": "definition", **patch}]
    with pytest.raises(ValueError, match=message):
        ah.load_document(write_doc(tmp_path, items=items))
