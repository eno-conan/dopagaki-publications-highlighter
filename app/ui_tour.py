"""画面（`web.py`）を Playwright で一通り操作し、各画面のスクリーンショットを1つの PDF にまとめる（見た目の確認用）。

    uv run python ui_tour.py           # ../work-gai/ui-tour/ui-tour.pdf を作る
    uv run python ui_tour.py --open    # 作ったあと、PDF を開く

- GitHub にも Claude にもつながない。一時フォルダ（work-gai/ui-tour/sandbox/）の中で、Issue の読み書きと
  Claude の起動を、手元の偽物に置き換えて動かす。分割案だけは、本物の `plan_issue.py` で作る
- PDF は `examples/sample-book/sample-book.pdf`（架空の内容）を使う
- 流れ: アップロード → 分割案を作成中 → 回答待ち（コメント・チェック）→ 返事待ち → 作業中 → 中断 → 再開 → 完了
  → 同じ名前の再アップロード（警告）。最後に、ダークモードと、スマホの幅（メニューを開いたところ）も撮る
- 初回だけ、ブラウザを入れる: `uv run playwright install chromium`
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pymupdf

import ask_issue
import issue_io
import monitor
import plan_issue
import read_answers
import start
import web

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "sample-book" / "sample-book.pdf"
OUT_DIR = ROOT / "work-gai" / "ui-tour"
REPO_URL = "https://github.com/example/sample"  # 画面のリンクに出るだけ（開かない）
# ページ全体を撮ると、上に固定したヘッダーが途中に写り込むので、撮るときだけ固定をやめる
STATIC_HEADER = (
    "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');"
    "s.textContent='.top{position:static!important}';document.head.appendChild(s);});"
)
# PDF の見出しに使う日本語フォント（無ければ PyMuPDF 内蔵のもの）
JP_FONTS = [Path("C:/Windows/Fonts/YuGothM.ttc"), Path("C:/Windows/Fonts/meiryo.ttc")]


class FakeGitHub:
    """質問の Issue の偽物（本文とコメントを、手元に持つだけ）。"""

    def __init__(self) -> None:
        self.open: dict[str, int] = {}
        self.body: dict[int, str] = {}
        self.comments: dict[int, list[dict]] = {}
        self.next = 101

    def create(self, name: str, body: str) -> int:
        number, self.next = self.next, self.next + 1
        self.open[name], self.body[number], self.comments[number] = number, body, []
        return number

    def comment(self, number: int, text: str) -> None:
        self.comments[number].append({"body": text, "createdAt": "2026-01-01T10:00:00Z"})

    def close(self, number: int, comment: str = "") -> None:
        self.open = {k: v for k, v in self.open.items() if v != number}

    def view(self, number: int) -> dict:
        return {"body": self.body[number], "comments": self.comments[number], "url": f"{REPO_URL}/issues/{number}"}

    def fetch(self, number: int) -> tuple[str, str]:
        notes = [c["body"] for c in self.comments[number] if issue_io.who(c["body"]) == "human"]
        return self.body[number], "\n\n".join(notes)


class FakeClaude:
    """Claude の偽物。止めるまで「動いている」。"""

    pid = 0

    def __init__(self) -> None:
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def stop(self) -> None:
        self.alive = False


def setup_sandbox(sandbox: Path) -> FakeGitHub:
    """画面が読み書きする場所と、外につながる部分を、すべて手元の偽物に置き換える。"""
    shutil.rmtree(sandbox, ignore_errors=True)
    (sandbox / "inbox").mkdir(parents=True)
    (sandbox / "output").mkdir()
    gh = FakeGitHub()
    start.INBOX, start.OUTPUT = sandbox / "inbox", sandbox / "output"
    start.open_issues = lambda: dict(gh.open)
    web.REPLACED = sandbox / "replaced"
    web.issues_info = lambda: (dict(gh.open), REPO_URL)
    web._guard_ok = True  # 公開リポジトリの確認（gh）をしない
    web.start_import = lambda: fake_import() or "取り込みを始めました"
    issue_io.view = gh.view
    issue_io.post_comment = gh.comment
    issue_io.edit_body = lambda number, body: gh.body.__setitem__(number, body)
    issue_io.close_issue = gh.close
    read_answers.fetch_issue = gh.fetch
    stop = lambda proc: proc.stop()  # noqa: E731  実プロセスを止める taskkill は呼ばない
    monitor.kill_tree = stop
    web.kill_tree = stop
    m = web.MONITOR
    m._open_issues = lambda: dict(gh.open)
    m._output = start.OUTPUT
    m._fetch = gh.fetch
    m._apply = lambda path, plan, result, n: read_answers.apply_answers(
        path, plan, result
    )  # Issue へのコメントはしない
    m._launch = lambda path, n: FakeClaude()
    m._launch_change = lambda path, n: FakeClaude()
    return gh


def fake_import() -> None:
    """取り込み（start.py）の代わり: inbox の PDF を作業フォルダに移すだけ（分割案は finish_plan で作る）。"""
    for pdf in start.inbox_pdfs(start.INBOX):
        start.move_to_output(pdf, start.OUTPUT)


def finish_plan(gh: FakeGitHub, name: str) -> Path:
    """分割案（本物の plan_issue.py）と、質問の Issue（偽物）を作る。"""
    pdf = start.OUTPUT / name / f"{name}.pdf"
    plan_issue.main(["--pdf", str(pdf), "--unit", "book"])
    plan_path = pdf.parent / "articles.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rec = ask_issue.recommended_ids(plan["articles"])
    gh.create(name, ask_issue.render_body(plan, name, purpose="実務に使う", recommend=rec, emphasis=rec[:1]))
    return plan_path


def fake_activity(folder: Path) -> None:
    """「Claude がいま」の表示用に、作業ログを1行だけ書く。"""
    event = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "docs/highlight-criteria.md"}}]
        },
    }
    (folder / "claude-run.log").write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")


def finish_work(gh: FakeGitHub, plan_path: Path) -> None:
    """作業の終わりの代わり: 対象の重要箇所とマーカー付きPDFを置き、Claude を止め、Issue を閉じる。"""
    for proc in web.MONITOR.running.values():
        proc.stop()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    folder = plan_path.parent
    (folder / "highlights").mkdir(exist_ok=True)
    (folder / "マーカー付き").mkdir(exist_ok=True)
    for a in plan["articles"]:
        if a.get("target"):
            (folder / "highlights" / f"{a['id']}.json").write_text("{}", encoding="utf-8")
            (folder / "マーカー付き" / f"{a['id']}.pdf").write_bytes(b"%PDF-1.7\n")
    gh.close(gh.open[folder.name])


def serve() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    web.ALLOWED_HOSTS.clear()
    web.ALLOWED_HOSTS.update({f"127.0.0.1:{srv.server_port}", f"localhost:{srv.server_port}"})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def run_tour(base: str, gh: FakeGitHub, shots_dir: Path) -> list[tuple[str, Path]]:
    from playwright.sync_api import sync_playwright

    shots: list[tuple[str, Path]] = []
    name = SAMPLE.stem

    def shot(page, title: str, full: bool = True) -> None:
        path = shots_dir / f"{len(shots) + 1:02d}.png"
        page.wait_for_timeout(300)  # 描き直し・パネルの読み込みを待つ
        page.screenshot(path=str(path), full_page=full)
        shots.append((title, path))

    def card(page):
        return page.locator("article.book", has_text=name)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="light", locale="ja-JP")
        ctx.add_init_script(STATIC_HEADER)
        page = ctx.new_page()

        page.goto(base + "/")
        shot(page, "メニュー（まだ何もない）")

        page.goto(base + "/new")
        page.set_input_files("#file", str(SAMPLE))
        page.wait_for_selector("text=を受け取りました")
        page.reload()
        card(page).wait_for()
        shot(page, "新規取り込み: アップロード直後（分割案を作成中）")

        plan_path = finish_plan(gh, name)
        page.goto(base + "/progress")
        card(page).locator(".fchk").first.wait_for()
        shot(page, "作業状況: 回答待ち（説明・GitHub の行 → 回答 → 補足 → 確定）")

        page.goto(base + "/")
        card(page).locator(".fchk").first.wait_for()
        shot(page, "メニュー: 答えを待っているもの")

        page.goto(base + "/progress")
        c = card(page)
        c.locator(".fchk").first.wait_for()
        c.locator("textarea.note").fill("2章の設定例は読み飛ばす")
        c.locator(".fchk", has_text="実務に使う").locator("input").check()
        c.get_by_role("button", name="回答を確定して作業を始める").click()
        c.locator(".pmsg.err").wait_for()
        shot(page, "確定を押したが、使う色が未回答: 作業は始めず、足りない点を表示")

        number = gh.open[name]
        gh.comment(
            number,
            "<!-- claude -->\n補足を読みました。2章の設定例は、重要箇所から外します。\n"
            "1. それでよい\n2. 設定例も拾う\nどちらにしますか？",
        )
        web.MONITOR._waiting.add(plan_path)
        page.reload()
        card(page).locator(".ask:not([hidden])").wait_for()
        shot(page, "返事待ち: Claude からの質問（パネルの上に出る）")
        c = card(page)
        c.locator("textarea.ans").fill("1で")
        c.get_by_role("button", name="返事を送る（Claude が読み直します）").click()
        c.locator(".pmsg.ok").wait_for()
        shot(page, "返事を送ったところ")
        web.MONITOR._waiting.discard(plan_path)

        page.reload()
        c = card(page)
        c.locator(".fchk").first.wait_for()
        c.locator(".fchk", has_text="3色（注意を積極的に）").locator("input").check()
        c.get_by_role("button", name="回答を確定して作業を始める").click()
        page.wait_for_selector("article.book .tag:has-text('作業中')")
        fake_activity(plan_path.parent)
        page.reload()
        card(page).get_by_text("Claude がいま").wait_for()
        shot(page, "作業中: Claude がいま何をしているか、中断ボタン")

        stop = card(page).get_by_role("button", name="中断")
        stop.click()
        shot(page, "中断: 1回目（確認に変わる）", full=False)
        card(page).get_by_role("button", name="もう一度押すと中断します").click()
        page.wait_for_selector("article.book .tag:has-text('中断')")
        shot(page, "中断したところ（再開ボタン）")

        card(page).get_by_role("button", name="再開").click()
        page.wait_for_selector("article.book .tag:has-text('作業中')")
        finish_work(gh, plan_path)
        page.goto(base + "/library")
        card(page).wait_for()
        shot(page, "成果物: 完了")

        page.goto(base + "/")
        page.wait_for_selector("#n-library:has-text('1')")
        shot(page, "メニュー: 件数")

        page.goto(base + "/new")
        page.set_input_files("#file", str(SAMPLE))
        page.locator("#confirm").wait_for()
        shot(page, "同じ名前の PDF を再アップロード: 警告", full=False)
        page.get_by_role("button", name="やめる").click()

        dark = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark", locale="ja-JP")
        dark.add_init_script(STATIC_HEADER)
        page = dark.new_page()
        for path, title in (
            ("/", "ダークモード: メニュー"),
            ("/library", "ダークモード: 成果物"),
            ("/new", "ダークモード: 新規取り込み"),
        ):
            page.goto(base + path)
            page.wait_for_timeout(500)
            shot(page, title)

        phone = browser.new_context(
            viewport={"width": 390, "height": 844}, color_scheme="light", locale="ja-JP", device_scale_factor=2
        )
        page = phone.new_page()
        page.goto(base + "/")
        page.wait_for_selector("#n-library:has-text('1')")
        shot(page, "スマホの幅: メニュー")
        page.goto(base + "/library")
        card(page).wait_for()
        shot(page, "スマホの幅: 成果物", full=False)
        page.get_by_role("button", name="メニューを開く").click()
        page.wait_for_timeout(400)
        shot(page, "スマホの幅: メニューを開いたところ", full=False)
        browser.close()
    return shots


def make_pdf(shots: list[tuple[str, Path]], out: Path) -> None:
    """スクリーンショットを、1枚1ページの PDF にまとめる（見出しと、しおり付き）。"""
    doc = pymupdf.open()
    width, head = 820.0, 44.0
    toc = []
    font = next((f for f in JP_FONTS if f.is_file()), None)
    text_font = {"fontname": "jp", "fontfile": str(font)} if font else {"fontname": "japan"}
    for i, (title, png) in enumerate(shots, 1):
        pix = pymupdf.Pixmap(str(png))
        scale = width / pix.width
        page = doc.new_page(width=width + 40, height=pix.height * scale + head + 20)
        page.insert_text((20, 30), f"{i:02d}  {title}", fontsize=15, **text_font)
        page.insert_image(pymupdf.Rect(20, head, 20 + width, head + pix.height * scale), filename=str(png))
        toc.append([1, f"{i:02d} {title}", i])
    doc.set_toc(toc)
    doc.save(str(out), garbage=3, deflate=True)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="画面を Playwright で一通り操作し、スクリーンショットを PDF にまとめる")
    p.add_argument("--out", type=Path, default=OUT_DIR / "ui-tour.pdf", help="作る PDF")
    p.add_argument("--open", action="store_true", help="作ったあと、PDF を開く")
    args = p.parse_args(argv)
    gh = setup_sandbox(OUT_DIR / "sandbox")
    shots_dir = OUT_DIR / "shots"
    shutil.rmtree(shots_dir, ignore_errors=True)
    shots_dir.mkdir(parents=True)
    srv = serve()
    try:
        shots = run_tour(f"http://127.0.0.1:{srv.server_port}", gh, shots_dir)
    finally:
        srv.shutdown()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    make_pdf(shots, args.out)
    shutil.rmtree(OUT_DIR / "sandbox", ignore_errors=True)  # 残すのは PDF だけ（作業場所とスクリーンショットは消す）
    shutil.rmtree(shots_dir, ignore_errors=True)
    print(f"{len(shots)}枚の画面を、{args.out} にまとめました")
    if args.open and sys.platform == "win32":
        os.startfile(args.out)  # noqa: S606
    return 0


if __name__ == "__main__":
    sys.exit(main())
