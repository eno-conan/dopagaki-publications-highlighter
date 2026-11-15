"""check_links / post_references のテスト（ネットワークは使わない）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import check_links as cl
import post_references as pr


@pytest.mark.parametrize(
    ("http", "url", "body", "status"),
    [
        (200, "https://example.com/doc", "<p>本文</p>", "ok"),
        (404, "https://example.com/x", "", "not_found"),
        (410, "https://example.com/x", "", "not_found"),
        (401, "https://example.com/x", "", "login"),
        (403, "https://example.com/x", "", "blocked"),
        (429, "https://example.com/x", "", "blocked"),
        (500, "https://example.com/x", "", "error"),
        (200, "https://example.com/login?next=/doc", "<p>x</p>", "login"),  # ログイン画面へのリダイレクト
        (200, "https://example.com/users/sign_in", "", "login"),
        (200, "https://example.com/blog/catalog", "<p>x</p>", "ok"),  # blog / catalog に反応しない
        (200, "https://example.com/a", "<p>この記事の続きを読むには会員登録が必要です</p>", "login"),
        (200, "https://example.com/a", '<form><input type="password"></form>', "login"),
    ],
)
def test_classify(http, url, body, status):
    assert cl.classify(http, url, body).status == status


def test_long_page_with_password_input_is_not_login():
    body = "<p>" + "本文" * 3000 + '</p><input type="password">'
    assert cl.classify(200, "https://example.com/doc", body).status == "ok"


def write_refs(tmp_path: Path, refs: list[dict]) -> Path:
    path = tmp_path / "p1-9.json"
    path.write_text(json.dumps({"title": "第1章", "references": refs}, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_rejects_bad_input(tmp_path):
    with pytest.raises(ValueError, match="title"):
        cl.load_refs(write_refs(tmp_path, [{"url": "https://a.example/"}]))
    with pytest.raises(ValueError, match="http"):
        cl.load_refs(write_refs(tmp_path, [{"url": "ftp://a.example/", "title": "a"}]))
    with pytest.raises(ValueError, match="重複"):
        cl.load_refs(write_refs(tmp_path, [{"url": "https://a.example/", "title": "a"}] * 2))
    with pytest.raises(ValueError, match="status"):
        cl.load_refs(write_refs(tmp_path, [{"url": "https://a.example/", "title": "a", "status": "fine"}]))


def test_check_all_writes_status_and_skips_browser_verified(tmp_path):
    path = write_refs(
        tmp_path,
        [
            {"url": "https://a.example/", "title": "a"},
            {"url": "https://b.example/", "title": "b", "status": "ok", "verified_by": "browser"},
            {"url": "https://c.example/", "title": "c"},
        ],
    )
    data = cl.load_refs(path)
    fetched = []

    def fake(url):
        fetched.append(url)
        return cl.LinkResult("ok" if "a." in url else "not_found", 200 if "a." in url else 404, url + "x")

    cl.check_all(data, fetcher=fake)
    assert fetched == ["https://a.example/", "https://c.example/"]  # ブラウザ確認済みは取得しない
    assert [r["status"] for r in data["references"]] == ["ok", "ok", "not_found"]
    assert data["references"][0]["final_url"] == "https://a.example/x"
    cl.check_all(data, force=True, fetcher=fake)
    assert "https://b.example/" in fetched  # --force なら取る


def test_post_renders_only_ok_links(tmp_path):
    data = {
        "title": "第1章 ログの基礎",
        "references": [
            {
                "url": "https://a.example/",
                "title": "公式",
                "kind": "official",
                "summary": "仕様",
                "status": "ok",
                "checked": "2026-11-15",
            },
            {"url": "https://b.example/", "title": "壊れ", "status": "not_found"},
            {"url": "https://c.example/", "title": "会員", "status": "login"},
            {"url": "https://d.example/", "title": "未確認"},
        ],
    }
    body, skipped = pr.render_comment("p11-64", data)
    assert body.startswith("<!-- references:p11-64 -->")
    assert "[公式](https://a.example/)（公式） — 仕様" in body
    assert "確認済み" not in body  # 注記は付けない
    assert "b.example" not in body and "c.example" not in body and "d.example" not in body
    assert [r["title"] for r in skipped] == ["壊れ", "会員", "未確認"]


def test_post_refuses_when_nothing_ok(tmp_path, capsys):
    path = write_refs(tmp_path, [{"url": "https://a.example/", "title": "a", "status": "not_found"}])
    assert pr.main(["--refs", str(path)]) == 1
    assert "status が ok" in capsys.readouterr().err


def test_post_keeps_json_order():
    data = {
        "references": [
            {"url": "https://z.example/", "title": "後で", "status": "ok"},
            {"url": "https://a.example/", "title": "先に", "status": "ok"},
        ]
    }
    body, _ = pr.render_comment("x", data)
    assert body.index("z.example") < body.index("a.example")  # 並べ替えず、JSON の順（先頭ほど有益）


def test_pipeline_closes_issue_only_when_everything_went_well(tmp_path, monkeypatch):
    import pipeline

    plan = tmp_path / "articles.json"
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "p1-9.json").write_text("{}", encoding="utf-8")
    closed = []
    monkeypatch.setattr(pipeline.subprocess, "run", lambda cmd, **k: closed.append(cmd))
    monkeypatch.setattr(
        pipeline.check_links, "main", lambda argv: 1
    )  # 載せられないリンクがあっても、閉じるのは妨げない
    monkeypatch.setattr(pipeline.post_references, "main", lambda argv: 0)
    monkeypatch.setattr(pipeline.build_issue, "main", lambda argv: 0)
    pipeline.main(["--plan", str(plan), "--issue", "7", "--close"])
    assert closed == [["gh", "issue", "close", "7"]]

    closed.clear()
    monkeypatch.setattr(pipeline.build_issue, "main", lambda argv: 1)  # マーカーの未適用
    pipeline.main(["--plan", str(plan), "--issue", "7", "--close"])
    assert closed == []

    monkeypatch.setattr(pipeline.build_issue, "main", lambda argv: 0)
    pipeline.main(["--plan", str(plan), "--issue", "7"])  # --close が無ければ閉じない
    assert closed == []


def test_ascii_url_encodes_japanese_but_keeps_existing_encoding():
    assert cl.ascii_url("https://ja.wikipedia.org/wiki/要件定義?a=1&b=2#x") == (
        "https://ja.wikipedia.org/wiki/%E8%A6%81%E4%BB%B6%E5%AE%9A%E7%BE%A9?a=1&b=2#x"
    )
    assert cl.ascii_url("https://example.com/a%20b") == "https://example.com/a%20b"  # すでにエンコード済みは、そのまま
