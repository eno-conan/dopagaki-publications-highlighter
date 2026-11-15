"""Issue への書き込み先が公開リポジトリのとき、止める（誤って公開しないためのガードレール）。

質問の Issue やコメントには、章の見出し・参考リンクなど、読んだ本の内容がわかる文字が載る。
`gh` は git の `origin` のリポジトリに書き込むので、公開リポジトリで動かすと、誰でも読める場所に載ってしまう。
そこで、書き込む前に `origin` の公開状態を調べ、PUBLIC なら、エラーにする。
意図して公開リポジトリに書くときは、`--allow-public`（または環境変数 BOOK_MARKER_ALLOW_PUBLIC=1）で外せる。
"""

from __future__ import annotations

import json
import os
import subprocess

ENV_ALLOW = "BOOK_MARKER_ALLOW_PUBLIC"


class PublicRepoError(ValueError):
    """書き込み先が公開リポジトリ（呼び出し側の `except ValueError` で、エラー表示になる）"""


def repo_info() -> tuple[str, str] | None:
    """(`owner/name`, 公開状態 PUBLIC / PRIVATE / INTERNAL)。調べられなければ None（gh が無い・未ログインなど）"""
    try:
        out = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner,visibility"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=30,
        ).stdout
        data = json.loads(out)
        return data["nameWithOwner"], str(data["visibility"]).upper()
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return None


def require_private(allow_public: bool = False) -> None:
    """書き込み先が公開リポジトリなら PublicRepoError。調べられないときは止めない（gh が失敗して、そちらで分かる）"""
    if allow_public:
        os.environ[ENV_ALLOW] = "1"  # 呼び出し先（子プロセスを含む）にも引き継ぐ
    if os.environ.get(ENV_ALLOW) == "1":
        return
    info = repo_info()
    if info is None or info[1] != "PUBLIC":
        return
    raise PublicRepoError(
        f"Issue の書き込み先 {info[0]} は公開（PUBLIC）リポジトリです。"
        "章の見出しや参考リンクが、誰でも読める場所に載ってしまうため、止めました。"
        "自分用の private リポジトリを git の origin にして実行してください。"
        f"意図して公開リポジトリに書くときだけ、--allow-public（または環境変数 {ENV_ALLOW}=1）を付けます"
    )
