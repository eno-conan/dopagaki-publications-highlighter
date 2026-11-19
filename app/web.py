"""ブラウザから PDF をアップロードして、取り込みの状況を見る、小さなローカル Web 画面（`作業開始.bat` から起動する）。

    uv run python web.py              # http://127.0.0.1:8765 を開く
    uv run python web.py --no-browser

- PDF を選ぶと `inbox/` に保存して、取り込み（`start.py`: 分割案・質問の Issue・見張り）を始める
- 同じ名前の PDF は、警告を出して、承認されたときだけ取り込み直す（古い作業フォルダは `work-gai/replaced/` に移し、
  開いている質問の Issue は閉じる。作業中の本・号は差し替えない）
- Claude の作業は、画面の「中断」で止められる（「再開」で続きから。分割案の作成中に止めたときは、最初から作り直す）
- 本・号ごとの状況（分割案を作成中 / 回答待ち / 作業中 / 完了）と、Issue へのリンクを表示する
- 質問の Issue に、画面の中で答えられる（回答フォームと、Claude とのやりとり）。正は Issue で、画面は Issue を読み書きするだけ
  （GitHub で直接答えてもよい）。結果の PDF は、エクスプローラーで開く
- 状況が「回答待ち」「返事待ち」「完了」に変わったら知らせる（画面が開いていればブラウザの通知、閉じていれば Windows の通知）

外部には公開しない（127.0.0.1 だけで待ち受け。Host ヘッダが違うリクエストは断る）。POST は、Origin・Content-Type と、
起動ごとの合言葉（ページに埋め込む token）も確かめる。Issue に書く前に、公開リポジトリでないことを確かめる。標準ライブラリだけで動く。
"""

# ruff: noqa: E501  （埋め込みの HTML / JS は、行が長くなる）
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import issue_io
import read_answers
import repo_guard
import start
from activity import latest_activity
from ask_issue import START
from monitor import STOP_MARK, Monitor, kill_tree, mark_stopped, stopped_stage
from web_pages import render_page

HOST, PORT = "127.0.0.1", 8765
DONE_MARK = "完了.txt"  # 作業フォルダに置くと、状況を「完了」にする（以前の流れで作成済みのもの用）
MAX_UPLOAD = 300 * 1024 * 1024  # 書籍のPDFは数十MB。大きすぎるものは断る
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
_run_lock = threading.Lock()
_runner: subprocess.Popen | None = None
MONITOR = Monitor()  # 画面が開いている間、質問の Issue を見張る（回答が揃ったら、反映して Claude を起動する）
TOKEN = secrets.token_urlsafe(24)  # 起動ごとの合言葉。ページに埋め込み、POST のヘッダ X-Token で照合する
NOTIFY_LABELS = ("回答待ち", "返事待ち", "完了")  # この状況に変わったら知らせる
TAB_IDLE = 30  # 画面からの状況の取得が、この秒数途絶えたら「タブが閉じている」と見なす
_last_poll = 0.0
_guard_ok = False


def safe_pdf_name(name: str) -> str:
    """アップロードされたファイル名を、安全な PDF 名にする。パスの部分は捨てる。使えない名前は ValueError。"""
    base = re.split(r"[\\/]", name.strip())[-1]
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "-", base).strip(" .")
    if not base.lower().endswith(".pdf") or len(base) <= 4:
        raise ValueError("PDF（.pdf）だけアップロードできます")
    return base


def parse_multipart(body: bytes, content_type: str) -> tuple[str, bytes]:
    """フォームの `file` の（ファイル名, 中身）を取り出す。"""
    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        raise ValueError("アップロードの形式が正しくありません")
    marker = b"--" + m.group(1).encode()
    for part in body.split(marker):
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        fn = re.search(rb'filename="([^"]*)"', head)
        if fn and b'name="file"' in head:
            return fn.group(1).decode("utf-8", "replace"), data.removesuffix(b"\r\n")
    raise ValueError("ファイルが見つかりません")


def save_upload(
    name: str, data: bytes, inbox: Path | None = None, output: Path | None = None, replace: bool = False
) -> Path:
    """inbox に保存する。同じ名前があれば断る（replace=True は、prepare_replace で古いものを片付けたあと）。"""
    inbox, output = inbox or start.INBOX, output or start.OUTPUT
    if not data.startswith(b"%PDF"):
        raise ValueError("PDF ではないようです")
    safe = safe_pdf_name(name)
    stem = Path(safe).stem
    if not replace and ((inbox / safe).exists() or (output / stem).exists()):
        raise ValueError(f"「{stem}」は、すでに取り込み済みか、取り込み待ちです（上書きしません）")
    if replace and (output / stem).exists():
        raise ValueError(f"「{stem}」の作業フォルダが残っています（差し替えの準備が終わっていません）")
    inbox.mkdir(exist_ok=True)
    dest = inbox / safe
    dest.write_bytes(data)
    return dest


REPLACED = start.ROOT / "work-gai" / "replaced"  # 差し替えた古い作業フォルダの置き場所（コミットしない）


def replace_warning(name: str, inbox: Path | None = None, output: Path | None = None) -> str | None:
    """同じ名前の PDF があれば、差し替えると何が起きるかの説明。無ければ None。"""
    inbox, output = inbox or start.INBOX, output or start.OUTPUT
    safe = safe_pdf_name(name)
    stem = Path(safe).stem
    folder = output / stem
    if folder.is_dir():
        number = issues_info()[0].get(stem)
        label = book_status(folder, number is not None)[0]
        lines = [
            f"「{stem}」は、すでに取り込んであります（いまの状況: {label}）。",
            "取り込み直すと、分割案・読み方の回答・重要箇所・参考文献・切り出しとマーカー付きの PDF を、"
            "新しい PDF で最初から作り直します（いまのものは使いません）。",
            "古い作業フォルダは work-gai/replaced/ に移します（元の PDF も含めて残ります）。",
        ]
        if number is not None:
            lines.append(f"開いている質問の Issue #{number} は閉じます（新しい Issue を作り直します）。")
        return "\n".join(lines)
    if (inbox / safe).exists():
        return f"「{stem}」は、まだ取り込み前で inbox にあります。新しい PDF で置き換えます。"
    return None


def prepare_replace(name: str, inbox: Path | None = None, output: Path | None = None) -> None:
    """差し替えの準備: 作業中なら断る。開いている質問の Issue を閉じ、古い作業フォルダを work-gai/replaced/ に移す。"""
    global _issue_cache
    inbox, output = inbox or start.INBOX, output or start.OUTPUT
    safe = safe_pdf_name(name)
    stem = Path(safe).stem
    info = MONITOR.info()
    if stem in info["working"] or stem in info["queued"]:
        raise ValueError(
            f"「{stem}」は Claude が作業中（または順番待ち）なので、差し替えられません。終わってから、もう一度"
        )
    if _runner is not None and _runner.poll() is None:
        raise ValueError(
            "取り込み（分割案と質問の Issue の作成）が動いている間は、差し替えられません。終わってから、もう一度"
        )
    folder = output / stem
    if folder.is_dir():
        number = start.open_issues().get(stem)
        if number is not None:
            require_private()
            issue_io.close_issue(
                number,
                "<!-- replaced -->\nPDF が差し替えられたので、この Issue は閉じます。新しい PDF で、質問の Issue を作り直します。",
            )
            _issue_cache = (0.0, {}, "")  # 閉じた Issue を、使い回しの一覧に残さない
        MONITOR.forget(folder / "articles.json")
        REPLACED.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder), str(REPLACED / f"{stem}-{datetime.now():%Y%m%d-%H%M%S}"))
    (inbox / safe).unlink(missing_ok=True)


def book_status(folder: Path, has_open_issue: bool = False) -> tuple[str, str]:
    """作業フォルダの状況を (ラベル, 詳細) で返す。回答待ちになるのは、質問の Issue が開いているものだけ。"""
    done_mark = folder / DONE_MARK
    if done_mark.is_file():  # 以前の流れで作成済み（フォルダ構成が今と違うので、手で印を付けてある）
        lines = done_mark.read_text(encoding="utf-8").strip().splitlines()
        return "完了", lines[0] if lines else "作成済み"
    plan = folder / "articles.json"
    if not plan.is_file():
        return "分割案を作成中", "分割案と質問の Issue を作っています（数分かかります）"
    data = json.loads(plan.read_text(encoding="utf-8"))
    targets = [a for a in data.get("articles", []) if a.get("target")]
    if not data.get("split", {}).get("approved") and has_open_issue:
        return (
            "回答待ち",
            "下で答えて、「回答を確定して作業を始める」を押してください（GitHub の Issue で答えてもかまいません）",
        )
    if not targets:
        return "未着手", "対象の記事がまだ決まっていません"
    done = sum(1 for a in targets if (folder / "highlights" / f"{a['id']}.json").is_file())
    marked = list((folder / "マーカー付き").glob("*.pdf")) if (folder / "マーカー付き").is_dir() else []
    if done == len(targets) and len(marked) >= len(targets):
        return "完了", f"マーカー付きPDF {len(marked)}件: output/{folder.name}/マーカー付き/"
    if done == len(targets):
        return "PDF作成待ち", "重要箇所は選び終わっています。pipeline.py（または build_issue.py）で、PDF を作ります"
    return "作業中", f"重要箇所の選定: {done}/{len(targets)}件（Claude が進めています）"


_issue_cache: tuple[float, dict[str, int], str] = (0.0, {}, "")


def issues_info() -> tuple[dict[str, int], str]:
    """開いている質問の Issue と、リポジトリの URL。gh を呼ぶので、20秒は使い回す。"""
    global _issue_cache
    now = time.monotonic()
    if now - _issue_cache[0] > 20:
        try:
            url = subprocess.run(
                ["gh", "repo", "view", "--json", "url", "-q", ".url"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            ).stdout.strip()
            _issue_cache = (now, start.open_issues(), url)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            _issue_cache = (now, {}, "")
    return _issue_cache[1], _issue_cache[2]


def status_payload(output: Path | None = None, inbox: Path | None = None) -> dict:
    output, inbox = output or start.OUTPUT, inbox or start.INBOX
    issues, repo_url = issues_info()
    books = []
    info = MONITOR.info()
    working, queued = info["working"], info["queued"]
    waiting = [p.stem for p in start.inbox_pdfs(inbox)]
    for name in waiting:
        books.append(
            {"name": name, "label": "取り込み待ち", "detail": "inbox にあります。取り込みを始めると処理します"}
        )
    for folder in sorted(p for p in output.iterdir() if p.is_dir()) if output.is_dir() else []:
        if not any(folder.glob("*.pdf")) or folder.name in waiting:
            continue
        label, detail = book_status(folder, folder.name in issues)
        activity = notice = ""
        stage = stopped_stage(folder)
        if stage and folder.name not in working:
            label, detail = "中断", STOPPED_TEXT.get(stage, STOPPED_TEXT["work"])
        elif label == "作業中" and folder.name not in working and folder.name not in queued:
            # 反映済みで重要箇所が揃っていないのに、Claude が動いていない（途中で止まった・画面を開き直した）
            label, detail = "中断", STOPPED_TEXT["halted"]
        elif folder.name in info["waiting"]:
            label, detail = "返事待ち", "Claude が、確認したいことを Issue にコメントしました"
        elif folder.name in queued:
            label, detail = "順番待ち", "ほかの本・号の作業が終わり次第、自動で始めます（同時に進めるのは1本だけ）"
        elif info["kinds"].get(folder.name) == "change":
            label, detail = "意図を読み取り中", "Claude が「分け方を変えたい」のチェックとコメントを読んでいます"
            activity = latest_activity(folder / "claude-change.log")
        elif folder.name in working:
            activity = latest_activity(folder / "claude-run.log")
        item: dict = {
            "name": folder.name,
            "label": label,
            "detail": detail,
            "working": folder.name in working or folder.name in queued,
            "stoppable": label != "中断" and (folder.name in working or folder.name in queued or planning(folder)),
            "activity": activity,
            "notice": notice,
        }
        if folder.name in issues and repo_url:
            item.update(issue=issues[folder.name], issue_url=f"{repo_url}/issues/{issues[folder.name]}")
        books.append(item)
    order = {
        "取り込み待ち": 0,
        "分割案を作成中": 1,
        "回答待ち": 2,
        "順番待ち": 2,
        "返事待ち": 2,
        "意図を読み取り中": 3,
        "作業中": 3,
        "PDF作成待ち": 4,
        "完了": 5,
        "中断": 4,
        "未着手": 6,
    }
    return {
        "books": sorted(books, key=lambda b: (order.get(b["label"], 9), b["name"])),
        "repo_url": repo_url,
        "monitor": MONITOR.info(),
    }


STOPPED_TEXT = {
    "work": "作業を中断しました。「再開」で、続きから進めます（途中まで選んだ重要箇所は残っています）",
    "halted": "Claude は動いていません（途中で止まりました）。「再開」で、続きから進めます（途中まで選んだ重要箇所は残っています）",
    "change": "意図の読み取りを中断しました。「再開」で、もう一度 Issue を読みます",
    "queued": "順番待ちを中断しました。「再開」で、もう一度 Issue を確かめます",
    "plan": "分割案の作成を中断しました。「再開」で、最初から作り直します（質問の Issue ができていれば閉じます）",
}


def planning(folder: Path) -> bool:
    """取り込み（start.py）が、この本・号の分割案を作っている途中か。"""
    return (
        _runner is not None
        and _runner.poll() is None
        and not (folder / "articles.json").is_file()
        and not stopped_stage(folder)
    )


def stop_book(name: str, output: Path | None = None) -> dict:
    """画面の「中断」。作業中・順番待ちなら Claude を止め、分割案の作成中なら取り込みごと止める。"""
    folder = (output or start.OUTPUT) / name
    if not folder.is_dir():
        raise ValueError("本・号が見つかりません")
    info = MONITOR.info()
    if name in info["working"] or name in info["queued"]:
        MONITOR.interrupt(folder / "articles.json")
        return {"ok": True, "message": "中断しました。続けるときは「再開」を押してください"}
    if planning(folder):
        kill_tree(_runner)  # inbox に残っているほかの PDF は、取り込み待ちのまま残る
        mark_stopped(folder, "plan")
        return {"ok": True, "message": "分割案の作成を中断しました。「再開」で、最初から作り直します"}
    raise ValueError("止める作業がありません（すでに終わっていませんか）")


def resume_book(name: str, output: Path | None = None) -> dict:
    """画面の「再開」。"""
    folder = (output or start.OUTPUT) / name
    stage = stopped_stage(folder)
    if stage == "plan":
        return restart_plan(name, folder)
    number = issue_number(name)
    return MONITOR.resume(folder / "articles.json", number)


def restart_plan(name: str, folder: Path) -> dict:
    """分割案の作成を、最初からやり直す。PDF を inbox に戻し、残りは work-gai/replaced/ に移す（Issue があれば閉じる）。"""
    pdfs = [p for p in folder.glob("*.pdf") if p.stem == name]
    if not pdfs:
        raise ValueError("元の PDF が見つかりません。もう一度アップロードしてください")
    REPLACED.mkdir(parents=True, exist_ok=True)
    hold = REPLACED / f"{name}-{datetime.now():%Y%m%d-%H%M%S}-{pdfs[0].name}"
    shutil.move(str(pdfs[0]), str(hold))
    (folder / STOP_MARK).unlink(missing_ok=True)
    prepare_replace(pdfs[0].name)
    start.INBOX.mkdir(exist_ok=True)
    shutil.move(str(hold), str(start.INBOX / pdfs[0].name))
    return {"ok": True, "message": start_import()}


def check_name(name: str) -> str:
    if not name or re.search(r"[\\/]", name) or name in (".", ".."):
        raise ValueError("本・号の名前が正しくありません")
    return name


def issue_number(name: str) -> int:
    """本・号の質問の Issue の番号。一覧は20秒使い回すので、見つからなければ取り直す。"""
    number = issues_info()[0].get(name) or start.open_issues().get(name)
    if number is None:
        raise ValueError("質問の Issue が見つかりません（すでに閉じていませんか）")
    return number


def require_private() -> None:
    """Issue に書く前に、公開リポジトリでないことを確かめる（一度確かめたら、起動中は使い回す）。"""
    global _guard_ok
    if not _guard_ok:
        repo_guard.require_private()
        _guard_ok = True


def issue_payload(name: str) -> dict:
    """画面の回答フォームと、やりとり（Claude と人のコメント）。"""
    number = issue_number(name)
    data = issue_io.view(number)
    form, start_item = split_start(issue_io.form(data["body"]))
    return {
        "ok": True,
        "number": number,
        "url": data.get("url", ""),
        "version": issue_io.version(data["body"]),
        "form": form,
        "started": bool(start_item and start_item["checked"]),  # GitHub で「作業開始OK」が付いている
        "thread": issue_io.thread(data.get("comments", [])),
    }


def split_start(items: list[dict]) -> tuple[list[dict], dict | None]:
    """回答フォームの項目から、「4. 作業開始」の見出しと「作業開始OK」を外す（画面では「確定して作業を始める」ボタンにする）。"""
    start_item = next((i for i in items if i["kind"] == "check" and i["text"] == START), None)
    rest = [i for i in items if i is not start_item and not (i["kind"] == "h2" and "作業開始" in i["text"])]
    return rest, start_item


def human_note(comments: list[dict]) -> str:
    """人のコメント（reading.json の note になる）。read_answers.fetch_issue と同じまとめ方。"""
    notes = [c["body"].strip() for c in comments if issue_io.who(c.get("body", "")) == "human"]
    return "\n\n".join(n for n in notes if n)


def send_comment(name: str, body: str) -> dict:
    """画面から返事を投稿し、続けて Issue を確認する（Claude の質問への返事なら、Claude が読み直す）。"""
    text = issue_io.check_comment(body)
    number = issue_number(name)
    require_private()
    issue_io.post_comment(number, text)
    result = MONITOR.answer(name)
    message = result.get("message") or "返事を送りました"
    return {**result, "ok": True, "posted": True, "message": message}


def save_answers(
    name: str, base_version: str, changes: list, start_work: bool = False, output: Path | None = None
) -> dict:
    """回答フォームで変えたチェックを Issue に書き戻す。

    - start_work=False（下書き保存）: 書き戻すだけ。作業は始めない
    - start_work=True（確定して作業を始める）: 書き込む前に、回答が揃っているかを判定する。揃っていれば「作業開始OK」も付けて書き、
      作業を始める。揃っていなければ、作業開始OK は付けずに書き戻し、足りない点を返す。「分け方を変えたい」なら、Claude に意図を読ませる
    """
    number = issue_number(name)
    require_private()
    data = issue_io.view(number)
    body = data["body"]
    conflict = {
        "ok": False,
        "conflict": True,
        "problems": [
            "フォームを開いたあとに、Issue 側で回答が変わりました。フォームを読み直したので、もう一度確かめてください"
        ],
    }
    if issue_io.version(body) != base_version:
        return conflict
    try:
        draft = issue_io.toggle(body, [c for c in changes if isinstance(c, dict) and c.get("text") != START])
    except issue_io.Conflict:
        return conflict
    if not start_work:
        if draft != body:
            issue_io.edit_body(number, draft)
        return {"ok": True, "message": "下書きを保存しました（作業はまだ始まりません）"}
    _, start_item = split_start(issue_io.form(draft))
    if start_item is None:
        return {"ok": False, "problems": ["Issue に「作業開始OK」の項目が見つかりません"]}
    candidate = issue_io.toggle(draft, [{**start_item, "checked": True}])
    plan = json.loads(((output or start.OUTPUT) / name / "articles.json").read_text(encoding="utf-8"))
    result = read_answers.evaluate_body(plan, candidate, human_note(data.get("comments", [])))
    if result.status == "incomplete":
        if draft != body:
            issue_io.edit_body(number, draft)
        problems = [p for p in result.problems if "作業開始OK" not in p]
        return {
            "ok": False,
            "problems": ["回答が足りないので、作業はまだ始めていません（チェックは保存しました）", *problems],
        }
    issue_io.edit_body(number, candidate if result.status == "ready" else draft)
    return MONITOR.answer(name)


def transitions(prev: dict[str, str], books: list[dict]) -> list[tuple[str, str]]:
    """前回から、知らせる状況（回答待ち・返事待ち・完了）に変わった本・号。初めて見る本・号の「完了」は知らせない。"""
    out = []
    for b in books:
        old, new = prev.get(b["name"]), b["label"]
        if new != old and new in NOTIFY_LABELS and not (old is None and new == "完了"):
            out.append((b["name"], new))
    return out


NOTIFY_TEXT = {
    "回答待ち": "質問の Issue ができました。画面で答えてください",
    "返事待ち": "Claude が確認したいことを書きました。画面で返事をしてください",
    "完了": "マーカー付きPDFができました",
}

TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:TOAST_TITLE)) > $null
$x.Item(1).AppendChild($t.CreateTextNode($env:TOAST_TEXT)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""


def toast(title: str, text: str) -> None:
    """Windows の通知を出す（Windows 以外では何もしない）。文字は環境変数で渡す（スクリプトに埋め込まない）。"""
    if sys.platform != "win32":
        return
    env = {**os.environ, "TOAST_TITLE": title, "TOAST_TEXT": text}
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", TOAST_PS],
            env=env,
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def notify_loop(interval: int = 20) -> None:
    """状況の変化を見て、画面のタブが閉じていれば Windows の通知を出す（開いていれば、画面がブラウザの通知を出す）。"""
    prev: dict[str, str] | None = None
    while True:
        with contextlib.suppress(OSError, ValueError, KeyError, subprocess.SubprocessError):
            books = status_payload()["books"]
            if prev is not None and time.monotonic() - _last_poll > TAB_IDLE:
                for name, label in transitions(prev, books):
                    toast(f"{name}: {label}", NOTIFY_TEXT[label])
            prev = {b["name"]: b["label"] for b in books}
        time.sleep(interval)


def start_import() -> str:
    """取り込み（start.py）を、裏で始める。すでに動いていれば、何もしない。"""
    global _runner
    with _run_lock:
        if _runner and _runner.poll() is None:
            return "取り込みはすでに動いています"
        if not start.inbox_pdfs():
            return "inbox に PDF がありません"
        log = start.ROOT / "work-gai" / "start.log"
        log.parent.mkdir(exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with log.open("w", encoding="utf-8") as f:
            _runner = subprocess.Popen(
                [sys.executable, "start.py", "--no-watch"],  # 見張りは、この画面の Monitor が行う
                cwd=start.ROOT / "app",
                stdout=f,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        return "取り込みを始めました（経過は画面の状況に出ます）"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            # ブラウザが先に接続を切った（タブを閉じた・再読み込みした）。返す相手がいないので無視する
            pass

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _host_ok(self) -> bool:
        # DNS リバインディング対策: 自分宛て以外の Host は断る
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self._json(403, {"ok": False, "error": "forbidden"})
            return False
        return True

    def _drain(self) -> None:
        """断るときも、送られた本文は読み捨てる（読まずに閉じると、Windows では接続ごと切れて、応答が届かない）"""
        with contextlib.suppress(ValueError, OSError):
            length = int(self.headers.get("Content-Length", "0"))
            if 0 < length <= MAX_UPLOAD:
                self.rfile.read(length)

    def _post_ok(self) -> bool:
        """他のサイトからの書き込みを断る: Origin（あれば）が自分、合言葉が一致。JSON の API は Content-Type も見る"""
        refusal = self._post_refusal()
        if refusal is None:
            return True
        self._drain()
        self._json(refusal[0], {"ok": False, "error": refusal[1]})
        return False

    def _post_refusal(self) -> tuple[int, str] | None:
        origin = self.headers.get("Origin")
        if origin is not None and origin.removeprefix("http://") not in ALLOWED_HOSTS:
            return 403, "forbidden origin"
        if not secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN):
            return 403, "画面を開き直してください（合言葉が違います）"
        if self.path != "/upload" and not self.headers.get("Content-Type", "").startswith("application/json"):
            return 415, "unsupported media type"
        return None

    def _body_json(self, limit: int = 64 * 1024) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > limit:
            raise ValueError("送る内容が大きすぎます")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("送る内容の形式が正しくありません")
        return data

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        try:
            self._get()
        except (ValueError, OSError, subprocess.SubprocessError) as e:
            self._json(400, {"ok": False, "error": escape(str(e))})

    def _get(self) -> None:
        page = render_page(self.path, TOKEN)
        if page is not None:
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            global _last_poll
            _last_poll = time.monotonic()
            self._json(200, status_payload())
        elif urlparse(self.path).path == "/api/upload-check":
            name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
            warning = replace_warning(name)
            self._json(200, {"ok": True, "exists": warning is not None, "warning": warning or ""})
        elif urlparse(self.path).path == "/api/issue":
            name = check_name(parse_qs(urlparse(self.path).query).get("name", [""])[0])
            self._json(200, issue_payload(name))
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok() or not self._post_ok():
            return
        try:
            if self.path == "/upload":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_UPLOAD:
                    raise ValueError(f"サイズが大きすぎます（{MAX_UPLOAD // 1024 // 1024}MBまで）")
                name, data = parse_multipart(self.rfile.read(length), self.headers.get("Content-Type", ""))
                replace = self.headers.get("X-Replace") == "1"  # 画面で警告を読んで、承認したときだけ付く
                if replace and replace_warning(name) is not None:
                    prepare_replace(name)
                dest = save_upload(name, data, replace=replace)
                start_import()
                self._json(200, {"ok": True, "name": dest.name})
            elif self.path == "/answered":
                name = check_name(str(self._body_json(4096).get("name", "")))
                self._json(200, MONITOR.answer(name))
            elif self.path == "/api/stop":
                self._json(200, stop_book(check_name(str(self._body_json(4096).get("name", "")))))
            elif self.path == "/api/resume":
                self._json(200, resume_book(check_name(str(self._body_json(4096).get("name", "")))))
            elif self.path == "/api/comment":
                data = self._body_json()
                self._json(200, send_comment(check_name(str(data.get("name", ""))), str(data.get("body", ""))))
            elif self.path == "/api/answers":
                data = self._body_json()
                changes = data.get("changes")
                if not isinstance(changes, list):
                    raise ValueError("回答の形式が正しくありません")
                name = check_name(str(data.get("name", "")))
                self._json(200, save_answers(name, str(data.get("version", "")), changes, bool(data.get("start"))))
            elif self.path == "/run":
                self._body_json(4096)  # 中身は使わないが、読んでから応答する
                self._json(200, {"ok": True, "message": start_import()})
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except (ValueError, OSError, subprocess.SubprocessError) as e:  # json.JSONDecodeError は ValueError
            self._json(400, {"ok": False, "error": escape(str(e))})

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # 標準のアクセスログは出さない


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="PDF をアップロードして、取り込みの状況を見るローカル Web 画面")
    p.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    p.add_argument("--port", type=int, default=PORT, help=f"待ち受けるポート（既定 {PORT}）")
    args = p.parse_args(argv)
    ALLOWED_HOSTS.clear()
    ALLOWED_HOSTS.update({f"127.0.0.1:{args.port}", f"localhost:{args.port}"})
    try:
        server = ThreadingHTTPServer((HOST, args.port), Handler)
    except OSError as e:
        print(f"エラー: {HOST}:{args.port} を開けません（すでに起動していませんか？）: {e}", file=sys.stderr)
        return 1
    url = f"http://{HOST}:{args.port}"
    minutes = MONITOR.interval // 60
    print(f"画面: {url}")
    print(f"このウィンドウが開いている間、質問の Issue を{minutes}分ごとに見張ります。")
    print("閉じると、画面も見張りも止まります（Ctrl+C でも止まります）。")
    if not args.no_browser:
        webbrowser.open(url)
    MONITOR.start_thread()
    threading.Thread(target=notify_loop, daemon=True, name="notify").start()
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
