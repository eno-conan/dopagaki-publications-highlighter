"""ask_issue（質問の Issue）と read_answers（答えの読み取り）のテスト。ネットワークは使わない。"""

from __future__ import annotations

import json

import ask_issue as ask
import read_answers as ra

PLAN = {
    "pdf": "b.pdf",
    "split": {"unit": "book"},
    "articles": [
        {"id": "p1-2", "title": "表紙", "first": 1, "last": 2, "readable": "ok", "target": None},
        {"id": "p3-9", "title": "第1章　基礎", "first": 3, "last": 9, "readable": "ok", "target": None},
        {"id": "p10-19", "title": "第2章　応用", "first": 10, "last": 19, "readable": "ok", "target": None},
        {"id": "p20", "title": "索引", "first": 20, "last": 20, "readable": "ok", "target": None},
    ],
}
TITLES = {a["id"]: a["title"].replace("　", " ") for a in PLAN["articles"]}


def body(emphasis=()):
    return ask.render_body(
        PLAN, "テスト本", purpose="実務に使う", recommend=ask.recommended_ids(PLAN["articles"]), emphasis=list(emphasis)
    )


def check(text: str, *labels: str) -> str:
    """本文のうち、labels を含むチェックボックス行にチェックを付ける。"""
    out = []
    for line in text.splitlines():
        if line.startswith("- [ ] ") and any(lb in line for lb in labels):
            line = "- [x] " + line[6:]
        out.append(line)
    return "\n".join(out)


def test_recommends_skip_front_and_back_matter():
    assert ask.recommended_ids(PLAN["articles"]) == ["p3-9", "p10-19"]


def test_fresh_issue_is_incomplete_and_nothing_prechecked():
    b = body()
    checked = [ln for ln in b.splitlines() if ln.startswith("- [x]")]
    assert len(checked) == 2 and all("★" in ln for ln in checked)  # 対象の★だけチェック済み。ほかは人が決める
    r = ra.resolve(ra.parse_body(b), TITLES)
    assert r.status == "incomplete" and len(r.problems) == 3  # 作業開始・目的・色が未回答


def test_checked_stars_are_targets_and_reading_comes_from_choices():
    b = check(body(emphasis=["p10-19"]), ask.START, "実務に使う", "3色（注意を積極的に）", "（`p10-19` p.10-19）")
    r = ra.resolve(ra.parse_body(b), TITLES, note="2章は読み飛ばす", today="2026-11-16")
    assert r.status == "ready" and r.targets == ["p3-9", "p10-19"]
    assert r.reading == {
        "answered": "2026-11-16",
        "purpose": "実務に使う",
        "emphasis": ["第2章 応用"],
        "colors": ["know", "do", "warn"],
        "warning": "積極的に拾う",
        "note": "2章は読み飛ばす",
    }


def test_individual_answers():
    b = check(body(), ask.START, "概要をつかむ", "2色（知る・方針・実践", "第1章 基礎（`p3-9` p.3-9）")
    b = b.replace("- [x] ★ 第2章 応用", "- [ ] ★ 第2章 応用")  # 対象から外す
    # 個別: 対象は p3-9 のみ、目的=概要、色=2色、重点=第1章
    r = ra.resolve(ra.parse_body(b), TITLES, today="d")
    assert r.status == "ready" and r.targets == ["p3-9"]
    assert r.reading["purpose"] == "概要をつかむ" and r.reading["colors"] == ["know", "do"]
    assert "warning" not in r.reading and r.reading["emphasis"] == ["第1章 基礎"]


def test_conflicts_and_gaps_are_reported():
    unanswered = check(body(), ask.START)  # 目的と色が未選択
    assert len([p for p in ra.resolve(ra.parse_body(unanswered), TITLES).problems if p.startswith("2.")]) == 2
    none = body().replace("- [x]", "- [ ]")
    assert any("1." in p for p in ra.resolve(ra.parse_body(check(none, ask.START)), TITLES).problems)  # 対象が空
    two_purposes = check(body(), ask.START, "概要をつかむ", "実務に使う", "3色（注意を積極的に）")
    r = ra.resolve(ra.parse_body(two_purposes), TITLES)
    assert r.status == "incomplete" and any("目的は1つ" in p for p in r.problems)


def test_change_request_stops():
    b = check(body(), ask.START, ask.CHANGE, "実務に使う", "3色（注意を積極的に）")
    assert ra.resolve(ra.parse_body(b), TITLES).status == "change"


def test_apply_writes_plan_and_reading(tmp_path):
    plan_path = tmp_path / "articles.json"
    plan = json.loads(json.dumps(PLAN))
    ra.write_plan(plan_path, plan)
    r = ra.resolve(ra.parse_body(check(body(), ask.START, "実務に使う", "3色（注意を積極的に）")), TITLES, today="d")
    ra.apply_answers(plan_path, plan, r)
    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    assert saved["split"]["approved"] == ["p1-2", "p3-9", "p10-19", "p20"]
    assert [a["target"] for a in saved["articles"]] == [False, True, True, False]
    assert json.loads((tmp_path / "reading.json").read_text(encoding="utf-8"))["purpose"] == "実務に使う"


def test_stale_issue_is_rejected(monkeypatch):
    changed = json.loads(json.dumps(PLAN))
    changed["articles"].pop()
    monkeypatch.setattr(ra, "fetch_issue", lambda n: (body(), ""))
    r = ra.evaluate(changed, 1)
    assert r.status == "incomplete" and "違います" in r.problems[0]


def test_nothing_happens_until_start_is_checked():
    b = check(body(), "実務に使う", "3色（注意を積極的に）")  # 答えは揃っているが「作業開始OK」が無い
    r = ra.resolve(ra.parse_body(b), TITLES)
    assert r.status == "incomplete" and r.problems == [
        "4. 最後の「作業開始OK」が未チェックです（チェックが付くまで、作業は始めません）"
    ]
    assert ra.resolve(ra.parse_body(check(b, ask.START)), TITLES).status == "ready"


def test_apply_comments_but_does_not_close_the_issue(tmp_path, monkeypatch):
    plan_path = tmp_path / "articles.json"
    ra.write_plan(plan_path, json.loads(json.dumps(PLAN)))
    ready = check(body(), ask.START, "実務に使う", "3色（注意を積極的に）")
    calls = []
    monkeypatch.setattr(ra, "fetch_issue", lambda n: (ready, ""))
    monkeypatch.setattr(ra.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    assert ra.main(["--plan", str(plan_path), "--issue", "5", "--apply"]) == 0
    assert [c[2] for c in calls] == ["comment"]  # コメントだけ。閉じるのは、作業が終わってから
    assert calls[0][-1].startswith("<!-- applied -->")  # 次に読むとき、人のコメントとして扱わない目印


def test_merged_articles_list_the_chapters_they_contain():
    plan = {
        "articles": [
            {
                "id": "p3-9",
                "title": "第3章　状態管理+第4章　通信",
                "name": "第3章〜第4章",
                "first": 3,
                "last": 9,
                "merged": ["p3-5", "p6-9"],
            },
            {"id": "p10-19", "title": "第5章　テーマ", "name": "第5章", "first": 10, "last": 19},
        ]
    }
    text = ask.render_body(plan, "本", purpose="実務に使う", recommend=["p3-9", "p10-19"], emphasis=[])
    assert "- [x] ★ 第3章〜第4章（`p3-9` p.3-9・7ページ）\n  - 第3章 状態管理\n  - 第4章 通信\n" in text
    assert text.count("  - 第3章 状態管理") == 2  # 重点の欄にも、含まれる章を出す（短い名前だけでは、中身が分からない）
    assert "  - 第5章" not in text  # 合体していない記事は、題がそのまま出ているので、足さない
    answers = ra.parse_body(check(text, ask.START, "実務に使う", "3色（注意を積極的に）"))
    assert answers.target_ids == ["p3-9", "p10-19"]  # 下の見出しの行は、チェックボックスとして読まない


def test_ids_with_a_letter_suffix_are_read(tmp_path):
    plan = {
        "articles": [
            {"id": "p353", "title": "A", "first": 353, "last": 353},
            {"id": "p353b", "title": "B", "first": 353, "last": 353},
        ]
    }
    text = ask.render_body(plan, "本", purpose="実務に使う", recommend=["p353", "p353b"], emphasis=[])
    assert ra.parse_body(text).target_ids == ["p353", "p353b"]
