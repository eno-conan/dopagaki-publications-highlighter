"""新しい号・書籍を取り込む最初の工程。しおりから記事（書籍は章）を一覧にして、マーカー対象にするかを判断して記録する。

    uv run python plan_issue.py --pdf ../output/<PDF名>/<号のPDF>.pdf                      # 一覧を作る（articles.json）
    uv run python plan_issue.py --pdf ../output/<PDF名>/<号のPDF>.pdf --include p100-105  # 対象にする
    uv run python plan_issue.py --pdf ../output/<PDF名>/<号のPDF>.pdf --exclude p150-155  # 対象外にする

書籍（章単位。30ページ未満の章は、隣の章とまとめる）:

    uv run python plan_issue.py --pdf ../output/<書名>/<書名>.pdf --unit book             # しおりの階層1を章にする
    uv run python plan_issue.py --pdf ... --unit book --chapter-level 2            # 階層2を章にする
    uv run python plan_issue.py --pdf ... --ranges 10-35:第1章データ 36-60:第2章   # しおりがないとき、手で範囲を指定
    uv run python plan_issue.py --pdf ... --merge p10-35 p36-60                    # 隣接する章・記事を合体（雑誌も可）
    uv run python plan_issue.py --pdf ... --join p146-151 p152-158 p166-171        # 離れた記事を、間を含めず1つに

判断は articles.json の `target`（true=対象 / false=対象外 / null=未判断）に残る。再実行しても判断は消えない。
文字が取れない記事（広告・画像・文字化け）は、最初から対象外にする（--include で戻せる）。

分け方（単位・範囲・合体）は、人が承認するまで切り出しも重要箇所の選定も始めない。承認はチャットで行い、
承認した分け方は articles.json の `split.approved`（記事IDの一覧）に人の判断として残る（このスクリプトは書き換えない）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import pymupdf

from mark_pdf import open_pdf

PLAN_NAME = "articles.json"
NO_TEXT_LIMIT = 30  # 記事全体でこれ未満の文字数なら「文字なし」
GARBLED_PAGE_RATIO = 0.3  # ページ内の「ありえない文字」の割合がこれ以上なら文字化けページ

READABLE_LABEL = {"ok": "読める", "partial": "一部文字化け", "garbled": "文字化け", "none": "文字なし"}


@dataclass
class Article:
    id: str
    title: str
    section: str
    first: int
    last: int
    chars: int
    readable: str  # ok / partial / garbled / none
    target: bool | None = None  # None=未判断
    name: str = ""  # 出力ファイル名の日本語部分
    note: str = ""
    highlights: str = ""  # 重要箇所JSONの相対パス
    merged: list[str] = field(default_factory=list)  # 合体した元の章のID（合体していなければ空）

    ranges: list[list[int]] = field(default_factory=list)  # 離れた記事を合体したときの、元のページ範囲の並び
    parts: list[dict] = field(default_factory=list)  # 合体した元の記事（id・title・first・last）。目次ページに使う

    @property
    def pages(self) -> int:
        if self.ranges:
            return sum(last - first + 1 for first, last in self.ranges)
        return self.last - self.first + 1

    @property
    def page_ranges(self) -> list[list[int]]:
        return self.ranges or [[self.first, self.last]]

    @classmethod
    def from_dict(cls, d: dict) -> Article:
        return cls(**{k: v for k, v in d.items() if k in {f.name for f in fields(cls)}})


# --------------------------------------------------------------------------- しおり → 記事


def article_name(title: str, section: str) -> str:
    """出力ファイル名の日本語部分。特集は「第1特集」、連載は連載名（【回数】より前）から空白を除いたもの。"""
    m = re.match(r"■(第\d+特集)", title)
    if m:
        return m.group(1)
    head = title.split("......")[0].split("【")[0]
    return re.sub(r"\s+", "", head).strip() or re.sub(r"\s+", "", section)


def article_id(first: int, last: int) -> str:
    return f"p{first}" if first == last else f"p{first}-{last}"


def toc_articles(toc: list[list]) -> list[tuple[str, str, int]]:
    """しおり（[階層, タイトル, ページ]）から (タイトル, 区分, 開始ページ) を取り出す。

    ■第N特集 は章を含めて1記事。子を持つ階層1は区分の見出しで、その子が記事。子のない階層1は1記事。
    """
    articles: list[tuple[str, str, int]] = []
    section = ""
    for i, (level, title, page, *_) in enumerate(toc):
        title = title.strip()
        if level == 1:
            has_children = i + 1 < len(toc) and toc[i + 1][0] > 1
            if re.match(r"■第\d+特集", title):
                articles.append((title, "特集", page))
                section = ""
            elif has_children:
                section = title
            else:
                articles.append((title, title, page))
                section = ""
        elif section:
            articles.append((title, section, page))
    return articles


def weird_ratio(text: str) -> float:
    """文字のうち、日本語の誌面にまず出てこない文字（ギリシャ文字やアラビア文字など）の割合。文字化けの目安。"""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    weird = sum(1 for c in chars if 0x0100 <= ord(c) <= 0x1FFF)
    return weird / len(chars)


def page_stats(doc: pymupdf.Document, first: int, last: int) -> tuple[int, int]:
    """(文字数, 文字化けページ数)"""
    total = garbled = 0
    for n in range(first, last + 1):
        text = doc[n - 1].get_text("text")
        total += len(text.strip())
        if weird_ratio(text) >= GARBLED_PAGE_RATIO:
            garbled += 1
    return total, garbled


def chapter_name(title: str) -> str:
    """書籍の `name`。章題から空白を除いたもの（例: 第3章データモデル）。"""
    return re.sub(r"\s+", "", title)


def chapter_articles(toc: list[list], level: int) -> list[tuple[str, str, int]]:
    """しおりの指定した階層を章として、(タイトル, 区分, 開始ページ) を取り出す。最初の章より前のページは含めない。"""
    return [(title.strip(), "章", page) for lvl, title, page, *_ in toc if lvl == level]


def readable_of(chars: int, garbled: int, pages: int) -> str:
    if chars < NO_TEXT_LIMIT:
        return "none"
    if garbled * 2 >= pages:
        return "garbled"
    return "partial" if garbled else "ok"


def make_article(doc: pymupdf.Document, title: str, section: str, first: int, last: int, name: str) -> Article:
    chars, garbled = page_stats(doc, first, last)
    return Article(
        id=article_id(first, last),
        title=title,
        section=section,
        first=first,
        last=last,
        chars=chars,
        readable=readable_of(chars, garbled, last - first + 1),
        name=name,
        highlights=f"highlights/{article_id(first, last)}.json",
    )


def dedupe_ids(articles: list[Article]) -> list[Article]:
    """同じページ範囲の記事が2つあるとき（1ページに複数のしおり）、2つ目以降のIDに b, c を付ける（p353 → p353b）。"""
    seen: dict[str, int] = {}
    for a in articles:
        n = seen.get(a.id, 0)
        seen[a.id] = n + 1
        if n:
            a.id = f"{a.id}{chr(ord('a') + n)}"
            a.highlights = f"highlights/{a.id}.json"
    return articles


def build_articles(doc: pymupdf.Document, unit: str = "magazine", chapter_level: int = 1) -> list[Article]:
    """しおりから記事を作る。unit="magazine" は特集・連載、unit="book" は chapter_level の階層の章。"""
    toc = doc.get_toc()
    starts = sorted(
        chapter_articles(toc, chapter_level) if unit == "book" else toc_articles(toc),
        key=lambda a: a[2],
    )
    if not starts:
        raise ValueError(
            "しおりから記事を取り出せませんでした"
            + ("（--chapter-level を変えるか、--ranges でページ範囲を指定してください）" if unit == "book" else "")
        )
    articles = []
    for i, (title, section, first) in enumerate(starts):
        last = starts[i + 1][2] - 1 if i + 1 < len(starts) else doc.page_count
        if last < first:  # 同じページから始まる記事（先頭のものをそのページに限る）
            last = first
        name = chapter_name(title) if unit == "book" else article_name(title, section)
        articles.append(make_article(doc, title, section, first, last, name))
    return dedupe_ids(articles)


def parse_ranges(doc: pymupdf.Document, specs: list[str]) -> list[Article]:
    """手で指定したページ範囲（`10-35:第1章データ` / `40:付録`）から記事を作る。しおりがない書籍用。"""
    articles: list[Article] = []
    prev_last = 0
    for spec in specs:
        m = re.fullmatch(r"(\d+)(?:-(\d+))?:(.+)", spec.strip())
        if not m:
            raise ValueError(f"ページ範囲の形が不正です: {spec}（例: 10-35:第1章データ）")
        first, last, title = int(m[1]), int(m[2] or m[1]), m[3].strip()
        if not 1 <= first <= last <= doc.page_count:
            raise ValueError(f"ページ範囲 {first}-{last} が不正です（全{doc.page_count}ページ）")
        if first <= prev_last:
            raise ValueError(f"ページ範囲 {first}-{last} が前の範囲と重なっているか、順番が逆です")
        prev_last = last
        articles.append(make_article(doc, title, "章", first, last, chapter_name(title)))
    return articles


def merge_articles(
    doc: pymupdf.Document,
    articles: list[Article],
    ids: list[str],
    name: str | None = None,
    *,
    join: bool = False,
) -> list[Article]:
    """記事（章）を1つに合体する。3章以上は警告になる（format_warnings）。

    既定は、隣接する記事だけ（連続したページ範囲の1記事になる）。
    join=True のときは、離れた記事も1つにする（間の記事は含めない）。
    ページ範囲は `ranges` に残り、IDは `p<最初>-<最後>j`。
    """
    index = {a.id: i for i, a in enumerate(articles)}
    unknown = [i for i in ids if i not in index]
    if unknown:
        raise ValueError(f"記事 {', '.join(unknown)} が見つかりません（例: {', '.join(list(index)[:3])}）")
    if len(ids) < 2:
        raise ValueError("--merge / --join には、合体する記事のIDを2つ以上指定してください")
    positions = [index[i] for i in ids]
    if join:
        if positions != sorted(set(positions)):
            raise ValueError(f"{', '.join(ids)} は、一覧の並びの順に、重複なく指定してください")
    elif positions != list(range(positions[0], positions[0] + len(ids))):
        raise ValueError(
            f"{', '.join(ids)} は隣接していません（一覧の並びで連続する記事だけ --merge で合体できます。"
            "離れた記事は --join）"
        )
    parts = [articles[p] for p in positions]
    title = "+".join(a.title for a in parts)
    name = name or "+".join(a.name for a in parts)
    first, last = parts[0].first, parts[-1].last
    merged = make_article(doc, title, parts[0].section, first, last, name)
    gapped = join or any(a.ranges for a in parts)  # 離れた範囲を持つ（間のページは含めない）
    if gapped:
        merged.id = f"{article_id(first, last)}j"
        merged.highlights = f"highlights/{merged.id}.json"
        merged.ranges = [list(r) for a in parts for r in a.page_ranges]
        stats = [page_stats(doc, f, last_) for f, last_ in merged.ranges]
        merged.chars = sum(c for c, _ in stats)
        merged.readable = readable_of(merged.chars, sum(g for _, g in stats), merged.pages)
    merged.merged = [i for a in parts for i in (a.merged or [a.id])]
    merged.parts = [
        p for a in parts for p in (a.parts or [{"id": a.id, "title": a.title, "first": a.first, "last": a.last}])
    ]
    merged.note = "合体: " + "+".join(a.title for a in parts)
    if gapped:
        merged.note += "（離れた記事を、間を含めずに1つにしたもの）"
    used = set(positions)
    rest = [a for i, a in enumerate(articles) if i > positions[0] and i not in used]
    return [*articles[: positions[0]], merged, *rest]


MIN_PAGES = 30  # これ未満の単位は、隣の章と合体する（PDF を何度も開閉しなくて済むように）
MAX_PAGES = 50  # 合体した結果がこれを超えたら警告する（承認で確認してもらう）
MIN_CHARS = 200  # これ未満の記事（部の扉など）は、本文が無いものとして扱う
# 本編ではない部分（対象外を提案する）の目印。章・特集以外の、前書き・後書き・索引・付録など
SKIP_WORDS = (
    "カバー", "表紙", "目次", "INDEX", "索引", "奥付", "あとがき", "おわりに", "おわり", "はじめに", "まえがき",
    "前書き", "著者", "謝辞", "Appendix", "付録", "参考文献", "用語集", "広告",
    "本書について", "プロフィール", "参考Web",
)  # fmt: skip


def is_blank(a: Article) -> bool:
    """部の扉など、文字がほとんど無い記事。"""
    return a.chars < MIN_CHARS


def is_matter(a: Article) -> bool:
    """前書き・後書き・索引・付録など、本編ではない部分。合体した記事（章どうしの合体）は本編。"""
    return not a.merged and any(w.lower() in a.title.lower() for w in SKIP_WORDS)


def short_name(articles: list[Article], ids: list[str]) -> str:
    """自動で合体した記事の名前。最初と最後の章の見出し（空白の前まで）をつなぐ。例: `Rule1〜Rule3`。"""
    parts = [a for a in articles if a.id in ids and not is_blank(a)]
    head = [a.title.split("　")[0].split(" ")[0] for a in (parts[0], parts[-1])]
    return head[0] if head[0] == head[1] else "〜".join(head)


def plan_auto_merge(articles: list[Article]) -> list[list[str]]:
    """30ページ未満の単位を、後ろの章とまとめる案を作る（合体するIDの組。2つ以上のものだけ）。

    - 30ページ以上になるまで、次の章を足す。足してよいのは、本編の章だけ（索引や付録は足さない）
    - 間にある部の扉（文字がほとんど無い記事）は、一緒に含める
    - 最後の単位が30ページ未満のまま残ったときは、直前の単位にまとめる
    """
    content = [a for a in articles if not is_matter(a) and not is_blank(a)]
    pos = {a.id: i for i, a in enumerate(articles)}
    groups: list[list[Article]] = []
    i = 0
    while i < len(content):
        group = [content[i]]
        i += 1
        while i < len(content) and group[-1].last - group[0].first + 1 < MIN_PAGES:
            nxt = content[i]
            between = articles[pos[group[-1].id] + 1 : pos[nxt.id]]
            if any(not is_blank(b) for b in between):  # 間に本編ではない部分（索引・付録など）があれば、そこで切る
                break
            group.append(nxt)
            i += 1
        groups.append(group)
    # 30ページ未満のまま残った単位は、直前の単位にまとめる（間が扉だけのときに限る）
    out: list[list[Article]] = []
    for g in groups:
        if out and g[-1].last - g[0].first + 1 < MIN_PAGES:
            between = articles[pos[out[-1][-1].id] + 1 : pos[g[0].id]]
            if all(is_blank(b) for b in between):
                out[-1].extend(g)
                continue
        out.append(g)
    result = []
    for g in out:
        if len(g) < 2:
            continue
        a, b = pos[g[0].id], pos[g[-1].id]
        result.append([x.id for x in articles[a : b + 1]])
    return result


def format_warnings(articles: list[Article], unit: str = "book") -> list[str]:
    warnings = [
        f"警告: {a.id} は{len(a.merged)}章を合体して{a.pages}ページあります"
        f"（{MAX_PAGES}ページまで）。承認で確認してください"
        for a in articles
        if a.merged and a.pages > MAX_PAGES
    ]
    short = [a.id for a in articles if not is_matter(a) and not is_blank(a) and a.pages < MIN_PAGES]
    if short and unit == "book":  # 雑誌の記事は、短くてよい
        shown = ", ".join(short[:5]) + ("…" if len(short) > 5 else "")
        warnings.append(
            f"注意: {MIN_PAGES}ページ未満の記事が{len(short)}件あります（{shown}）。"
            "書籍は --auto-merge で、隣の章とまとめられます"
        )
    return warnings


# --------------------------------------------------------------------------- 判断の保存


def merge_decisions(new: list[Article], old: list[dict]) -> list[Article]:
    """前回の判断（target / name / note / highlights）を引き継ぐ。無ければ、読めない記事だけ自動で対象外にする。"""
    previous = {o["id"]: o for o in old}
    for a in new:
        if a.id in previous:
            p = previous[a.id]
            a.target, a.name = p.get("target"), p.get("name") or a.name
            a.note, a.highlights = p.get("note", ""), p.get("highlights") or a.highlights
        elif a.readable in ("none", "garbled"):
            a.target = False
            a.note = f"{READABLE_LABEL[a.readable]}のため対象外（自動）"
    return new


def decide(articles: list[Article], include: list[str], exclude: list[str]) -> None:
    by_id = {a.id: a for a in articles}
    for ids, value in ((include, True), (exclude, False)):
        for i in ids:
            if i not in by_id:
                raise ValueError(f"記事 {i} が見つかりません（例: {', '.join(list(by_id)[:3])}）")
            by_id[i].target = value
            if value and by_id[i].readable in ("none", "garbled"):
                by_id[i].note = f"{READABLE_LABEL[by_id[i].readable]}だが、手動で対象にした"
            elif by_id[i].note.endswith("（自動）"):
                by_id[i].note = ""


def load_plan(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("articles", [])


def load_split(path: Path) -> dict | None:
    """分割単位の承認の記録（人の判断）。再実行で消さないよう、そのまま引き継ぐ。無ければ None。"""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("split")


def article_dict(a: Article) -> dict:
    d = asdict(a)
    if not d["merged"]:  # 合体していない記事（雑誌など）の articles.json は、これまでの形のまま
        del d["merged"]
    if not d["ranges"]:  # 離れた記事を合体したときだけ持つ
        del d["ranges"]
    if not d["parts"]:  # 合体した記事だけ持つ
        del d["parts"]
    return d


def save_plan(path: Path, pdf: Path, articles: list[Article], split: dict | None = None) -> None:
    rel = Path(os.path.relpath(pdf, path.parent)).as_posix()  # 元PDFが記事フォルダの中（original.pdf）でも辿れるように
    data: dict = {"pdf": rel}
    head = f'  "pdf": {json.dumps(rel, ensure_ascii=False)},\n'
    if split is not None:
        data["split"] = split
        head += f'  "split": {json.dumps(split, ensure_ascii=False)},\n'
    data["articles"] = [article_dict(a) for a in articles]
    lines = ",\n".join("    " + json.dumps(article_dict(a), ensure_ascii=False) for a in articles)
    text = f'{{\n{head}  "articles": [\n{lines}\n  ]\n}}\n'
    assert json.loads(text) == data
    path.write_text(text, encoding="utf-8", newline="\n")


def approval_status(split: dict | None, articles: list[Article]) -> str | None:
    """分割単位の承認の状況。承認は人の判断（チャット）で、ここでは記録を読んで表示するだけ。split が無ければ None。"""
    if split is None:
        return None
    unit = split.get("unit", "?")
    approved = set(split.get("approved") or [])
    ids = {a.id for a in articles}
    if not approved:
        return f"分け方（{unit}）: 未承認。人の承認をもらうまで、切り出しも重要箇所の選定も始めない"
    if approved == ids:
        return f"分け方（{unit}）: 承認済み"
    diff = [
        f"未承認 {', '.join(sorted(ids - approved))}" if ids - approved else "",
        f"承認後に無くなった {', '.join(sorted(approved - ids))}" if approved - ids else "",
    ]
    return f"分け方（{unit}）: 承認した分け方と違います（{'、'.join(d for d in diff if d)}）。再承認が必要"


def target_mark(a: Article) -> str:
    return {True: "○ 対象", False: "× 対象外", None: "？ 未判断"}[a.target]


def format_table(articles: list[Article]) -> str:
    rows = ["| ID | ページ | 区分 | タイトル | 文字 | 判断 |", "|---|---|---|---|---|---|"]
    for a in articles:
        title = a.title.split("......")[0].strip()
        if a.ranges:
            pages = ", ".join(f"{f}-{last}" for f, last in a.ranges) + f"（{a.pages}p）"
        else:
            pages = f"{a.first}-{a.last}（{a.pages}p）" if a.pages > 1 else f"{a.first}（1p）"
        rows.append(f"| {a.id} | {pages} | {a.section} | {title} | {READABLE_LABEL[a.readable]} | {target_mark(a)} |")
    return "\n".join(rows)


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    p = argparse.ArgumentParser(description="号・書籍の記事（章）を一覧にして、マーカー対象かどうかの判断を記録する")
    p.add_argument("--pdf", type=Path, required=True, help="号・書籍のPDF（元PDF）")
    p.add_argument("--out", type=Path, help=f"保存先。省略時はPDFと同じフォルダの {PLAN_NAME}")
    p.add_argument("--include", nargs="*", default=[], metavar="ID", help="対象にする記事のID（例: p100-105）")
    p.add_argument("--exclude", nargs="*", default=[], metavar="ID", help="対象外にする記事のID")
    p.add_argument(
        "--unit",
        choices=["magazine", "book"],
        help="分割単位。magazine=特集・連載 / book=章。省略時は articles.json の記録、無ければ magazine",
    )
    p.add_argument(
        "--chapter-level", type=int, default=1, metavar="N", help="book のとき、章にするしおりの階層（既定 1）"
    )
    p.add_argument(
        "--ranges",
        nargs="*",
        default=[],
        metavar="FIRST-LAST:章名",
        help="しおりがない書籍用。手でページ範囲を指定する（例: 10-35:第1章データ）。book になる",
    )
    p.add_argument("--merge", nargs="*", default=[], metavar="ID", help="隣接する記事（章）のIDを合体する")
    p.add_argument(
        "--join",
        nargs="*",
        default=[],
        metavar="ID",
        help="離れた記事のIDを、間の記事を含めずに1つにまとめる（一覧の順に指定。IDは p<最初>-<最後>j になる）",
    )
    p.add_argument(
        "--auto-merge",
        action="store_true",
        help=f"book のとき、{MIN_PAGES}ページ未満の単位を、隣の章とまとめる（索引・付録などは足さない）",
    )
    p.add_argument("--rebuild", action="store_true", help="book の一覧を、しおりから作り直す（合体・範囲指定は消える）")
    args = p.parse_args(argv)
    try:
        if not args.pdf.is_file():
            raise ValueError(f"PDF が見つかりません: {args.pdf}")
        out = args.out or args.pdf.with_name(PLAN_NAME)
        old, old_split = load_plan(out), load_split(out)
        unit = args.unit or (old_split or {}).get("unit") or ("book" if args.ranges else "magazine")
        if args.auto_merge and unit != "book":
            raise ValueError("--auto-merge は書籍（--unit book）だけで使えます")
        doc = open_pdf(args.pdf)
        try:
            keep = unit == "book" or any(d.get("merged") for d in old)  # 雑誌は、合体したものがあるときだけ保つ
            if args.ranges:
                articles = parse_ranges(doc, args.ranges)
            elif keep and old and not args.rebuild:
                articles = [Article.from_dict(d) for d in old]  # 合体・範囲指定を保つ
            else:
                articles = build_articles(doc, unit, args.chapter_level)
            articles = merge_decisions(articles, old)
            if args.merge:
                articles = merge_articles(doc, articles, args.merge)
            if args.join:
                articles = merge_articles(doc, articles, args.join, join=True)
            if args.auto_merge:
                for ids in plan_auto_merge(articles):
                    articles = merge_articles(doc, articles, ids, short_name(articles, ids))
        finally:
            doc.close()
        decide(articles, args.include, args.exclude)
        split = None
        if old_split is not None or args.unit or unit != "magazine" or any(a.merged for a in articles):
            split = {"approved": [], **(old_split or {}), "unit": unit}  # approved は人の判断なので書き換えない
        save_plan(out, args.pdf, articles, split)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    print(format_table(articles))
    undecided = sum(1 for a in articles if a.target is None)
    print(
        f"\n{len(articles)}記事（対象 {sum(a.target is True for a in articles)} / "
        f"対象外 {sum(a.target is False for a in articles)} / 未判断 {undecided}）→ {out}"
    )
    for line in [*format_warnings(articles, unit), approval_status(split, articles)]:
        if line:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
