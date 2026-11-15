"""参考文献・関連リンクの JSON（`references/<ID>.json`）を取得して、載せてよいリンクだけを選ぶ。

    uv run python check_links.py --refs ../output/<書名>/references/p11-64.json

各リンクを実際に取得し、結果を `status` に書き戻す。

| status | 意味 | 投稿 |
|---|---|---|
| `ok` | 200 で本文が取れた（リダイレクト先は `final_url` に残す） | する |
| `not_found` | 404・410、または接続できない | しない |
| `login` | ログインや会員登録が要るページ（401、ログイン画面へのリダイレクト、会員限定の文言） | しない |
| `blocked` | 403・429・503 など。ボット扱いの可能性 | しない（実ブラウザで確認できたら `ok` に） |
| `error` | 上のどれでもない失敗（タイムアウトなど） | しない |

ボット対策（CAPTCHA・チャレンジ）を回避する処理は入れない。ふつうのブラウザ相当の User-Agent で取りに行き、
それでも断られたものは `blocked` のまま載せない。
`verified_by` が `browser` の `ok` は、人（または実ブラウザ）が確認済みなので、`--force` を付けない限り再取得しない。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlparse

STATUSES = ("ok", "not_found", "login", "blocked", "error")
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 20
MAX_BODY = 512 * 1024

# ログイン画面らしい URL（パスの区切りで見る。`blog` や `catalog` には反応しない）
LOGIN_PATH = re.compile(r"(?:^|[/_.-])(?:log[-_]?in|sign[-_]?in|sign[-_]?up|register|sso|auth)(?:$|[/_.?-])", re.I)
# 会員限定の文言（本文にあれば、ログインが要るページとみなす）
LOGIN_WORDS = (
    "ログインしてください",
    "ログインが必要",
    "会員登録が必要",
    "会員限定",
    "有料会員",
    "続きを読むには",
    "sign in to continue",
    "log in to continue",
    "login required",
    "members only",
    "subscribe to read",
)
PASSWORD_INPUT = re.compile(r"<input[^>]+type=[\"']?password", re.I)
TAG = re.compile(r"<[^>]+>")


@dataclass
class LinkResult:
    status: str
    http: int | None = None
    final_url: str = ""
    note: str = ""


def looks_like_login(final_url: str, body: str) -> str:
    """ログインが要るページらしければ、その根拠を返す。違えば空文字。"""
    path = urlparse(final_url).path
    if LOGIN_PATH.search(path):
        return f"ログイン画面のURL（{path}）"
    lowered = body.lower()
    for word in LOGIN_WORDS:
        if word.lower() in lowered:
            return f"会員限定の文言（{word}）"
    # パスワード欄があり、本文の文字がほとんど無いページはログインフォーム
    if PASSWORD_INPUT.search(body) and len(TAG.sub("", body).strip()) < 2000:
        return "パスワード入力欄だけのページ"
    return ""


def classify(http: int | None, final_url: str, body: str) -> LinkResult:
    """HTTP の結果から status を決める（通信しない部分。テストしやすいように分けてある）。"""
    if http in (401, 407):
        return LinkResult("login", http, final_url, "認証が必要（401）")
    if http in (404, 410):
        return LinkResult("not_found", http, final_url, f"{http}")
    if http in (403, 429, 503):
        return LinkResult("blocked", http, final_url, f"{http}（ボット扱いで断られた可能性。ブラウザで確認する）")
    if http is None or not 200 <= http < 300:
        return LinkResult("error", http, final_url, f"HTTP {http}")
    reason = looks_like_login(final_url, body)
    if reason:
        return LinkResult("login", http, final_url, reason)
    return LinkResult("ok", http, final_url)


def ascii_url(url: str) -> str:
    """日本語などを含む URL を、パーセントエンコードする（取得時に 'ascii' codec で止まらないように）。"""
    return quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def fetch(url: str) -> LinkResult:
    req = urllib.request.Request(
        ascii_url(url),
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            ctype = res.headers.get("Content-Type", "")
            body = ""
            if "html" in ctype or not ctype:
                body = res.read(MAX_BODY).decode(res.headers.get_content_charset() or "utf-8", errors="replace")
            return classify(res.status, res.url, body)
    except urllib.error.HTTPError as e:
        return classify(e.code, e.geturl() or url, "")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        # 名前解決の失敗・接続拒否は、存在しないURLとして扱う。タイムアウトは一時的かもしれないので error
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            return LinkResult("error", None, url, f"タイムアウト（{TIMEOUT}秒）")
        return LinkResult("not_found", None, url, f"接続できない（{reason}）")


def load_refs(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    refs = data.get("references")
    if not isinstance(refs, list):
        raise ValueError(f"{path.name}: `references` が配列ではありません")
    for i, r in enumerate(refs, 1):
        if not r.get("url") or not r.get("title"):
            raise ValueError(f"{path.name}: {i}件目に `url` と `title` が要ります")
        if not urlparse(r["url"]).scheme.startswith("http"):
            raise ValueError(f"{path.name}: {i}件目の url が http(s) ではありません: {r['url']}")
        if "status" in r and r["status"] not in STATUSES:
            raise ValueError(f"{path.name}: {i}件目の status が不正です: {r['status']}（{', '.join(STATUSES)}）")
    urls = [r["url"] for r in refs]
    dup = sorted({u for u in urls if urls.count(u) > 1})
    if dup:
        raise ValueError(f"{path.name}: url が重複しています: {', '.join(dup)}")
    return data


def check_all(data: dict, *, force: bool = False, fetcher=fetch) -> list[tuple[dict, LinkResult | None]]:
    """各リンクを確認して、`status` などを書き込む。再取得しなかったものの結果は None。"""
    today = date.today().isoformat()
    out: list[tuple[dict, LinkResult | None]] = []
    for r in data["references"]:
        if not force and r.get("status") == "ok" and r.get("verified_by") == "browser":
            out.append((r, None))
            continue
        res = fetcher(r["url"])
        r["status"], r["http"], r["final_url"], r["note_check"], r["checked"] = (
            res.status,
            res.http,
            res.final_url,
            res.note,
            today,
        )
        out.append((r, res))
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="参考文献JSONのリンクを取得して、status を書き戻す")
    p.add_argument("--refs", type=Path, required=True, help="references/<ID>.json")
    p.add_argument("--force", action="store_true", help="ブラウザで確認済みのものも取得し直す")
    args = p.parse_args(argv)
    try:
        data = load_refs(args.refs)
        results = check_all(data, force=args.force)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    args.refs.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    for r, res in results:
        note = f"  {res.note}" if res and res.note else ("  （ブラウザで確認済み）" if res is None else "")
        print(f"{r['status']:<10} {r['title']}  {r['url']}{note}")
    bad = [r for r, _ in results if r["status"] != "ok"]
    print(f"{len(results) - len(bad)}/{len(results)}件が投稿できます")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
