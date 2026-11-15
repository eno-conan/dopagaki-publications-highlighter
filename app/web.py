"""ブラウザから PDF をアップロードして、取り込みの状況を見る、小さなローカル Web 画面（`作業開始.bat` から起動する）。

    uv run python web.py              # http://127.0.0.1:8765 を開く
    uv run python web.py --no-browser

- PDF を選ぶと `inbox/` に保存して、取り込み（`start.py`: 分割案・質問の Issue・見張り）を始める
- 本・号ごとの状況（分割案を作成中 / 回答待ち / 作業中 / 完了）と、Issue へのリンクを表示する
- 答えるのは、これまでどおり GitHub の Issue（リンクから開く）。結果の PDF は、エクスプローラーで開く

外部には公開しない（127.0.0.1 だけで待ち受け。Host ヘッダが違うリクエストは断る）。標準ライブラリだけで動く。
"""

# ruff: noqa: E501  （埋め込みの HTML / JS は、行が長くなる）
from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
import threading
import time
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import start
from monitor import Monitor
from web_pages import render_page

HOST, PORT = "127.0.0.1", 8765
DONE_MARK = "完了.txt"  # 作業フォルダに置くと、状況を「完了」にする（以前の流れで作成済みのもの用）
MAX_UPLOAD = 300 * 1024 * 1024  # 書籍のPDFは数十MB。大きすぎるものは断る
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
_run_lock = threading.Lock()
_runner: subprocess.Popen | None = None
MONITOR = Monitor()  # 画面が開いている間、質問の Issue を見張る（回答が揃ったら、反映して Claude を起動する）


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


def save_upload(name: str, data: bytes, inbox: Path | None = None, output: Path | None = None) -> Path:
    inbox, output = inbox or start.INBOX, output or start.OUTPUT
    if not data.startswith(b"%PDF"):
        raise ValueError("PDF ではないようです")
    safe = safe_pdf_name(name)
    stem = Path(safe).stem
    if (inbox / safe).exists() or (output / stem).exists():
        raise ValueError(f"「{stem}」は、すでに取り込み済みか、取り込み待ちです（上書きしません）")
    inbox.mkdir(exist_ok=True)
    dest = inbox / safe
    dest.write_bytes(data)
    return dest


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
        return "回答待ち", "Issue に答えて、最後の「作業開始OK」をチェックしてください"
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
    waiting = [p.stem for p in start.inbox_pdfs(inbox)]
    for name in waiting:
        books.append(
            {"name": name, "label": "取り込み待ち", "detail": "inbox にあります。取り込みを始めると処理します"}
        )
    for folder in sorted(p for p in output.iterdir() if p.is_dir()) if output.is_dir() else []:
        if not any(folder.glob("*.pdf")) or folder.name in waiting:
            continue
        label, detail = book_status(folder, folder.name in issues)
        item: dict = {"name": folder.name, "label": label, "detail": detail}
        if folder.name in issues and repo_url:
            item.update(issue=issues[folder.name], issue_url=f"{repo_url}/issues/{issues[folder.name]}")
        books.append(item)
    order = {
        "取り込み待ち": 0,
        "分割案を作成中": 1,
        "回答待ち": 2,
        "作業中": 3,
        "PDF作成待ち": 4,
        "完了": 5,
        "未着手": 6,
    }
    return {
        "books": sorted(books, key=lambda b: (order.get(b["label"], 9), b["name"])),
        "repo_url": repo_url,
        "monitor": MONITOR.info(),
    }


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
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _host_ok(self) -> bool:
        # DNS リバインディング対策: 自分宛て以外の Host は断る
        if self.headers.get("Host", "") not in ALLOWED_HOSTS:
            self._json(403, {"ok": False, "error": "forbidden"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        page = render_page(self.path)
        if page is not None:
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._json(200, status_payload())
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        try:
            if self.path == "/upload":
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_UPLOAD:
                    raise ValueError(f"サイズが大きすぎます（{MAX_UPLOAD // 1024 // 1024}MBまで）")
                name, data = parse_multipart(self.rfile.read(length), self.headers.get("Content-Type", ""))
                dest = save_upload(name, data)
                start_import()
                self._json(200, {"ok": True, "name": dest.name})
            elif self.path == "/run":
                self._json(200, {"ok": True, "message": start_import()})
            else:
                self._json(404, {"ok": False, "error": "not found"})
        except (ValueError, OSError) as e:
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
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
