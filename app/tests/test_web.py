"""web（ローカルのアップロード画面）のテスト。Claude も gh も起動しない。"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

import web


def multipart(name: str, data: bytes) -> tuple[bytes, str]:
    b = "XBOUNDARYX"
    body = (
        (
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{b}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={b}"


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ("本.pdf", "本.pdf"),
        (r"C:\Users\x\..\本.PDF", "本.PDF"),
        ("../../etc/本.pdf", "本.pdf"),
        ('a:b?"c.pdf', "a-b--c.pdf"),
    ],
)
def test_safe_pdf_name_drops_paths_and_bad_characters(raw, safe):
    assert web.safe_pdf_name(raw) == safe


@pytest.mark.parametrize("raw", ["本.txt", ".pdf", "", "本.pdf.exe"])
def test_safe_pdf_name_rejects_non_pdf(raw):
    with pytest.raises(ValueError, match="PDF"):
        web.safe_pdf_name(raw)


def test_parse_multipart_keeps_japanese_name_and_binary_content():
    data = b"%PDF-1.7\r\n\x00\xff binary \r\n"
    body, ctype = multipart("サンプルの本.pdf", data)
    assert web.parse_multipart(body, ctype) == ("サンプルの本.pdf", data)
    with pytest.raises(ValueError):
        web.parse_multipart(b"x", "text/plain")


def test_save_upload_checks_content_and_never_overwrites(tmp_path):
    inbox, output = tmp_path / "inbox", tmp_path / "output"
    (output / "既存").mkdir(parents=True)
    with pytest.raises(ValueError, match="PDF ではない"):
        web.save_upload("本.pdf", b"not pdf", inbox, output)
    dest = web.save_upload("本.pdf", b"%PDF-x", inbox, output)
    assert dest == inbox / "本.pdf" and dest.read_bytes() == b"%PDF-x"
    with pytest.raises(ValueError, match="取り込み待ち"):
        web.save_upload("本.pdf", b"%PDF-y", inbox, output)  # inbox に同名
    with pytest.raises(ValueError, match="取り込み済み"):
        web.save_upload("既存.pdf", b"%PDF-y", inbox, output)  # output に同名の作業フォルダ
    assert dest.read_bytes() == b"%PDF-x"


def test_done_mark_overrides_the_status_for_books_made_by_the_old_flow(tmp_path):
    folder = tmp_path / "旧"
    folder.mkdir()
    (folder / "articles.json").write_text(json.dumps({"articles": [{"id": "p1-9", "target": True}]}), encoding="utf-8")
    assert web.book_status(folder)[0] == "作業中"
    (folder / web.DONE_MARK).write_text("以前の流れで作成済み。\n2行目は無視する", encoding="utf-8")
    assert web.book_status(folder) == ("完了", "以前の流れで作成済み。")


def test_book_status_follows_the_phases(tmp_path):
    folder = tmp_path / "本"
    folder.mkdir()
    assert web.book_status(folder)[0] == "分割案を作成中"
    plan = folder / "articles.json"
    articles = [{"id": "p1-9", "target": True}]
    plan.write_text(json.dumps({"split": {"approved": []}, "articles": articles}), encoding="utf-8")
    assert web.book_status(folder, has_open_issue=True)[0] == "回答待ち"
    assert web.book_status(folder)[0] == "作業中"  # Issue が無い（以前の流れ）なら、回答待ちとは言わない
    plan.write_text(json.dumps({"articles": [{"id": "p1-9", "target": None}]}), encoding="utf-8")
    assert web.book_status(folder)[0] == "未着手"  # 対象がまだ決まっていない
    plan.write_text(json.dumps({"split": {"approved": []}, "articles": articles}), encoding="utf-8")
    plan.write_text(json.dumps({"split": {"approved": ["p1-9"]}, "articles": articles}), encoding="utf-8")
    assert web.book_status(folder) == ("作業中", "重要箇所の選定: 0/1件（Claude が進めています）")
    (folder / "highlights").mkdir()
    (folder / "highlights" / "p1-9.json").write_text("{}", encoding="utf-8")
    assert web.book_status(folder)[0] == "PDF作成待ち"
    (folder / "マーカー付き").mkdir()
    (folder / "マーカー付き" / "a.pdf").write_bytes(b"x")
    (folder / "references").mkdir()
    assert web.book_status(folder)[0] == "完了"


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(web.start, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(web.start, "OUTPUT", tmp_path / "output")
    started = []
    monkeypatch.setattr(web, "start_import", lambda: started.append(1) or "ok")
    monkeypatch.setattr(web, "issues_info", lambda: ({}, ""))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    monkeypatch.setattr(web, "ALLOWED_HOSTS", {f"127.0.0.1:{srv.server_port}"})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, started
    srv.shutdown()


def request(srv, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{srv.server_port}", **(headers or {})}
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    return r.status, r.read()


def test_other_host_headers_are_refused(server):
    srv, _ = server
    assert request(srv, "GET", "/", host="evil.example")[0] == 403
    assert request(srv, "POST", "/run", host="evil.example")[0] == 403
    assert request(srv, "GET", "/")[0] == 200


def test_status_page_and_api(server):
    srv, _ = server
    status, body = request(srv, "GET", "/api/status")
    payload = json.loads(body)
    assert status == 200 and payload["books"] == [] and payload["repo_url"] == ""
    assert "last_check" in payload["monitor"] and "working" in payload["monitor"]  # 見張りの状況も返す


def test_upload_rejects_non_pdf_over_http(server):
    srv, started = server
    body, ctype = multipart("本.pdf", b"not pdf")
    status, resp = request(srv, "POST", "/upload", body, {"Content-Type": ctype, "Content-Length": str(len(body))})
    assert status == 400 and not json.loads(resp)["ok"] and started == []


def get_page(srv, path):
    status, body = request(srv, "GET", path)
    return status, body.decode("utf-8")


def test_every_page_has_the_hamburger_menu_with_links_to_all_pages(server):
    srv, _ = server
    for path in ("/", "/new", "/progress", "/library"):
        status, page = get_page(srv, path)
        assert status == 200 and 'id="burger"' in page and 'id="drawer"' in page
        for href in ('href="/"', 'href="/new"', 'href="/progress"', 'href="/library"'):
            assert href in page
    assert get_page(srv, "/nope")[0] == 404


def test_new_page_has_upload_and_explanation_but_no_finished_work(server):
    srv, _ = server
    _, page = get_page(srv, "/new")
    assert (
        "PDF をドロップ" in page
        and "どこまで自動で進むか" in page
        and "ここで止まります" in page
        and "作業開始OK" in page
    )
    assert (
        "'完了'" not in page.split("const GROUPS")[1].split("new:")[1].split("]")[0]
    )  # 新規の画面に、完成した成果物は出さない


def test_other_pages_have_no_upload_and_keep_groups_apart(server):
    srv, _ = server
    for path in ("/", "/progress", "/library"):
        assert 'id="drop"' not in get_page(srv, path)[1]
    assert "renderList('library'" in get_page(srv, "/library")[1]
    assert "renderList('progress'" in get_page(srv, "/progress")[1]


def test_menu_page_shows_questions_waiting_for_an_answer_only_when_there_are_some(server):
    srv, _ = server
    page = get_page(srv, "/")[1]
    assert (
        'id="ask"' in page and "GROUPS.progress" in page and 'id="issues-link"' not in page
    )  # 常設の Issue 一覧リンクは置かない
