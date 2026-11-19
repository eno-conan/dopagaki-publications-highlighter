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
    headers = {"Content-Type": ctype, "Content-Length": str(len(body)), "X-Token": web.TOKEN}
    status, resp = request(srv, "POST", "/upload", body, headers)
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


def test_page_scripts_have_valid_javascript(tmp_path):
    """埋め込みの JS に構文エラーがあると、メニューなど画面全体が動かなくなる（node があるときだけ確かめる）。"""
    import re
    import shutil
    import subprocess

    import pytest

    import web_pages

    node = shutil.which("node")
    if node is None:
        pytest.skip("node がありません")
    for path in web_pages.PAGES:
        js = re.search(r"<script>(.*)</script>", web_pages.render_page(path), re.S).group(1)
        f = tmp_path / "page.js"
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"{path}: {r.stderr}"


def post_json(srv, path, obj, *, token=None, origin=None, ctype="application/json"):
    body = json.dumps(obj).encode()
    token = web.TOKEN if token is None else token
    headers = {"Content-Type": ctype, "Content-Length": str(len(body)), "X-Token": token}
    if origin:
        headers["Origin"] = origin
    status, resp = request(srv, "POST", path, body, headers)
    return status, json.loads(resp)


def test_posts_need_the_token_our_origin_and_json(server):
    srv, started = server
    own = f"http://127.0.0.1:{srv.server_port}"
    assert post_json(srv, "/run", {}, token="")[0] == 403  # 合言葉が無い
    assert post_json(srv, "/run", {}, token="wrong")[0] == 403
    assert post_json(srv, "/run", {}, origin="http://evil.example")[0] == 403  # 他のサイトから
    assert post_json(srv, "/run", {}, ctype="text/plain")[0] == 415  # 他のサイトのフォームから送れる形
    assert started == []
    assert post_json(srv, "/run", {}, origin=own)[0] == 200 and started == [1]


def test_pages_embed_the_token(server):
    srv, _ = server
    assert f'const TOKEN="{web.TOKEN}"' in get_page(srv, "/progress")[1]


@pytest.fixture
def issue_server(server, monkeypatch):
    srv, _ = server
    calls = []
    monkeypatch.setattr(web, "issue_number", lambda name: 7)
    monkeypatch.setattr(web, "_guard_ok", True)
    monkeypatch.setattr(web.issue_io, "post_comment", lambda n, text: calls.append(("comment", n, text)))
    answer = lambda name: calls.append(("answer", name)) or {"ok": True, "message": "m"}  # noqa: E731
    monkeypatch.setattr(web.MONITOR, "answer", answer)
    return srv, calls


def test_reply_is_posted_to_the_issue_and_then_checked(issue_server):
    srv, calls = issue_server
    status, j = post_json(srv, "/api/comment", {"name": "本", "body": " 1で "})
    assert status == 200 and j["ok"] and j["posted"]
    assert calls == [("comment", 7, "1で"), ("answer", "本")]  # 返事のあと、すぐ確認する（「回答完了」と同じ）
    status, j = post_json(srv, "/api/comment", {"name": "本", "body": "<!-- claude --> x"})
    assert status == 400 and len(calls) == 2  # 自動投稿や Claude のふりはできない
    assert post_json(srv, "/api/comment", {"name": "../x", "body": "a"})[0] == 400


def test_public_repo_blocks_writing_from_the_screen(issue_server, monkeypatch):
    srv, calls = issue_server
    monkeypatch.setattr(web, "_guard_ok", False)

    def refuse(allow_public=False):
        raise web.repo_guard.PublicRepoError("公開リポジトリです")

    monkeypatch.setattr(web.repo_guard, "require_private", refuse)
    status, j = post_json(srv, "/api/comment", {"name": "本", "body": "1で"})
    assert status == 400 and "公開" in j["error"] and calls == []


@pytest.fixture
def fake_issue(issue_server, tmp_path, monkeypatch):
    """質問の Issue（本物の本文）と、その articles.json。書き込みは手元に残す。"""
    import ask_issue

    plan = {
        "pdf": "本.pdf",
        "articles": [
            {"id": "p1-9", "title": "第1章", "first": 1, "last": 9},
            {"id": "p10-19", "title": "第2章", "first": 10, "last": 19},
        ],
    }
    folder = tmp_path / "output" / "本"
    folder.mkdir(parents=True)
    (folder / "articles.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    state = {"body": ask_issue.render_body(plan, "本", purpose="実務に使う", recommend=["p1-9"], emphasis=[])}
    monkeypatch.setattr(web.issue_io, "view", lambda n: {"body": state["body"], "comments": [], "url": "u"})
    monkeypatch.setattr(web.issue_io, "edit_body", lambda n, body: state.update(body=body))
    return issue_server, state


def check(state, *texts):
    """画面のフォームで、指定した項目にチェックを付けたときの changes。"""
    items = web.issue_io.form(state["body"])
    return [{**i, "checked": True} for i in items if i["kind"] == "check" and i["text"].startswith(texts)]


def test_draft_save_writes_the_checks_but_never_starts_work(fake_issue):
    (srv, calls), state = fake_issue
    ver = web.issue_io.version(state["body"])
    changes = check(state, "実務に使う", "3色（注意を積極的に）", web.START)  # 作業開始OK は、下書きでは書かない
    status, j = post_json(srv, "/api/answers", {"name": "本", "version": ver, "changes": changes})
    assert status == 200 and j["ok"] and "作業はまだ始まりません" in j["message"] and calls == []
    a = web.read_answers.parse_body(state["body"])
    assert a.purposes == ["実務に使う"] and not a.start


def test_confirm_without_enough_answers_saves_the_checks_but_does_not_start(fake_issue):
    (srv, calls), state = fake_issue
    ver = web.issue_io.version(state["body"])
    status, j = post_json(
        srv, "/api/answers", {"name": "本", "version": ver, "changes": check(state, "実務に使う"), "start": True}
    )
    assert not j["ok"] and "作業はまだ始めていません" in j["problems"][0] and calls == []
    assert any("使う色" in p for p in j["problems"]) and not any("作業開始OK" in p for p in j["problems"])
    a = web.read_answers.parse_body(state["body"])
    assert a.purposes == ["実務に使う"] and not a.start  # 足りないので、作業開始OK は付けない


def test_confirm_with_enough_answers_checks_start_and_starts_work(fake_issue):
    (srv, calls), state = fake_issue
    ver = web.issue_io.version(state["body"])
    changes = check(state, "実務に使う", "3色（注意を積極的に）")
    status, j = post_json(srv, "/api/answers", {"name": "本", "version": ver, "changes": changes, "start": True})
    assert j == {"ok": True, "message": "m"} and calls == [("answer", "本")]
    assert web.read_answers.parse_body(state["body"]).start


def test_saving_reports_a_conflict_instead_of_overwriting(fake_issue):
    (srv, calls), state = fake_issue
    before = state["body"]
    status, j = post_json(srv, "/api/answers", {"name": "本", "version": "古い版", "changes": [], "start": True})
    assert status == 200 and not j["ok"] and j["conflict"] and calls == [] and state["body"] == before
    assert post_json(srv, "/api/answers", {"name": "本", "version": "v", "changes": "x"})[0] == 400


def test_issue_api_returns_form_without_the_start_checkbox(issue_server, monkeypatch):
    srv, _ = issue_server
    body = "## 1. 分け方と対象\n\n- [x] 第1章\n\n## 4. 作業開始\n\n- [x] 作業開始OK（上の回答を終えました）\n"
    comments = [{"body": "<!-- claude -->\nどうしますか", "createdAt": "t"}, {"body": "<!-- applied -->\nx"}]
    monkeypatch.setattr(web.issue_io, "view", lambda n: {"body": body, "comments": comments, "url": "u"})
    status, raw = request(srv, "GET", "/api/issue?name=" + "%E6%9C%AC")
    j = json.loads(raw)
    assert status == 200 and j["number"] == 7 and j["version"] == web.issue_io.version(body)
    assert [i["text"] for i in j["form"]] == ["1. 分け方と対象", "第1章"]  # 作業開始は、画面ではボタンにする
    assert j["started"] is True  # GitHub で作業開始OK が付いている
    assert j["thread"] == [{"who": "claude", "created_at": "t", "body": "どうしますか"}]


def test_transitions_notify_only_on_changes_into_the_states_to_know():
    books = [
        {"name": "a", "label": "返事待ち"},
        {"name": "b", "label": "完了"},
        {"name": "c", "label": "完了"},
        {"name": "d", "label": "回答待ち"},
        {"name": "e", "label": "作業中"},
    ]
    prev = {"a": "意図を読み取り中", "b": "作業中", "d": "回答待ち", "e": "回答待ち"}
    # c は初めて見る「完了」（起動したときから完了していた）なので知らせない。d は変わっていない
    assert web.transitions(prev, books) == [("a", "返事待ち"), ("b", "完了")]
    assert web.transitions({}, [{"name": "n", "label": "回答待ち"}]) == [("n", "回答待ち")]


@pytest.fixture
def replace_env(tmp_path, monkeypatch):
    inbox, output = tmp_path / "inbox", tmp_path / "output"
    folder = output / "号"
    (folder / "highlights").mkdir(parents=True)
    (folder / "号.pdf").write_bytes(b"%PDF-old")
    (folder / "articles.json").write_text(json.dumps({"articles": [{"id": "p1-9", "target": True}]}), "utf-8")
    (folder / "highlights" / "p1-9.json").write_text("{}", "utf-8")
    closed = []
    monkeypatch.setattr(web.start, "INBOX", inbox)
    monkeypatch.setattr(web.start, "OUTPUT", output)
    monkeypatch.setattr(web, "REPLACED", tmp_path / "replaced")
    monkeypatch.setattr(web, "_guard_ok", True)
    monkeypatch.setattr(web, "_runner", None)
    monkeypatch.setattr(web, "issues_info", lambda: ({"号": 12}, ""))
    monkeypatch.setattr(web.start, "open_issues", lambda: {"号": 12})
    monkeypatch.setattr(web.issue_io, "close_issue", lambda n, c: closed.append((n, c)))
    monkeypatch.setattr(web.MONITOR, "info", lambda: {"working": [], "queued": []})
    return tmp_path, folder, closed


def test_reupload_warns_and_replaces_only_after_approval(replace_env):
    tmp_path, folder, closed = replace_env
    warning = web.replace_warning("号.pdf")
    assert (
        "すでに取り込んであります" in warning and "Issue #12 は閉じます" in warning and "work-gai/replaced/" in warning
    )
    assert web.replace_warning("別の号.pdf") is None
    with pytest.raises(ValueError, match="上書きしません"):
        web.save_upload("号.pdf", b"%PDF-new")  # 承認が無ければ、今までどおり断る
    web.prepare_replace("号.pdf")
    assert not folder.exists() and closed and closed[0][0] == 12 and closed[0][1].startswith("<!-- replaced -->")
    [backup] = (tmp_path / "replaced").iterdir()
    assert backup.name.startswith("号-") and (backup / "号.pdf").read_bytes() == b"%PDF-old"  # 古いものは残す
    assert (backup / "highlights" / "p1-9.json").is_file()
    dest = web.save_upload("号.pdf", b"%PDF-new", replace=True)
    assert dest.read_bytes() == b"%PDF-new"


def test_reupload_is_refused_while_claude_is_working(replace_env, monkeypatch):
    _, folder, closed = replace_env
    monkeypatch.setattr(web.MONITOR, "info", lambda: {"working": ["号"], "queued": []})
    with pytest.raises(ValueError, match="作業中"):
        web.prepare_replace("号.pdf")
    assert folder.exists() and closed == []


def test_reupload_of_a_pdf_still_in_the_inbox_just_replaces_it(replace_env):
    tmp_path, _, closed = replace_env
    web.save_upload("待ち.pdf", b"%PDF-1")
    assert "inbox" in web.replace_warning("待ち.pdf")
    web.prepare_replace("待ち.pdf")
    assert web.save_upload("待ち.pdf", b"%PDF-2", replace=True).read_bytes() == b"%PDF-2" and closed == []


def test_upload_check_api(server, monkeypatch):
    srv, _ = server
    monkeypatch.setattr(web, "replace_warning", lambda name: "警告" if name == "号.pdf" else None)
    j = json.loads(request(srv, "GET", "/api/upload-check?name=%E5%8F%B7.pdf")[1])
    assert j == {"ok": True, "exists": True, "warning": "警告"}
    j = json.loads(request(srv, "GET", "/api/upload-check?name=new.pdf")[1])
    assert j["exists"] is False


def test_book_that_stopped_halfway_is_shown_as_interrupted(tmp_path, monkeypatch):
    output = tmp_path / "output"
    folder = output / "号"
    folder.mkdir(parents=True)
    (folder / "号.pdf").write_bytes(b"%PDF")
    articles = [{"id": "p1-9", "target": True}]
    (folder / "articles.json").write_text(json.dumps({"split": {"approved": ["p1-9"]}, "articles": articles}), "utf-8")
    monkeypatch.setattr(web, "issues_info", lambda: ({"号": 3}, ""))
    info = {"working": [], "queued": [], "waiting": [], "kinds": {}, "started": [], "interval": 120}
    monkeypatch.setattr(web.MONITOR, "info", lambda: info)
    [book] = web.status_payload(output, tmp_path / "inbox")["books"]
    assert book["label"] == "中断" and "動いていません" in book["detail"] and not book["stoppable"]
    info["working"] = ["号"]
    [book] = web.status_payload(output, tmp_path / "inbox")["books"]
    assert book["label"] == "作業中" and book["stoppable"]  # 本当に動いているときは、中断できる


def test_stop_without_running_work_is_refused(tmp_path, monkeypatch):
    (tmp_path / "号").mkdir()
    monkeypatch.setattr(web, "_runner", None)
    monkeypatch.setattr(web.MONITOR, "info", lambda: {"working": [], "queued": []})
    with pytest.raises(ValueError, match="止める作業がありません"):
        web.stop_book("号", tmp_path)


def test_menu_page_introduces_the_product_and_the_marker_colors(server):
    from apply_highlights import GROUPS

    srv, _ = server
    page = get_page(srv, "/")[1]
    assert "dopagaki-<wbr>publications-<wbr>highlighter" in page and "どぱがき とは" in page and "なぜ作ったか" in page
    for g in GROUPS.values():  # 凡例は、マーカーの色の定義から作る
        assert g.label in page and "#{:02X}{:02X}{:02X}".format(*(round(c * 255) for c in g.color)) in page
    assert "<title>メニュー - dopagaki-publications-highlighter</title>" in page
    assert "どぱがき とは" not in get_page(srv, "/progress")[1]  # 説明は、トップだけ
