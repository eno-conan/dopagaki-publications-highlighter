"""開いている質問の Issue を、一定の間隔で見張り、回答が揃ったら、反映して Claude を起動する（`web.py` の中で動く）。

`作業開始.bat` のウィンドウ（= `web.py`）が開いている間、ずっと続く。毎回、Issue と articles.json を読み直すので、
分け方を変えたあとでも、古い状態のまま止まることはない。

- 回答が揃った（目的・色・最後の「作業開始OK」）→ 反映して Issue にコメントし、Claude を起動する
- 「分け方を変えたい」が選ばれた → チェックとコメントをあわせて意図を読み取るよう、Claude に渡す
  （Issue の内容が変わるまで、1回だけ）
- 回答が足りない・矛盾している → 何もしない（画面の状況は「回答待ち」のまま）
- Claude を同時に動かすのは1本だけ。ほかが動いている間は「順番待ち」にして（反映もしない）、終わったあとの確認で始める
- すでに反映済み（split.approved が空でない）の本・号は、対象外
- 画面の「中断」で止めた本・号（作業フォルダに claude-stopped.json がある）は、「再開」されるまで触らない
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import read_answers
import start
import watch

STOP_MARK = "claude-stopped.json"  # 中断した印（どの段階で止めたか）。再開するまで、見張りはこの本・号を触らない


def kill_tree(proc: subprocess.Popen) -> None:
    """プロセスを、子プロセス（Claude が起動したコマンドなど）ごと止める。"""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        proc.kill()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def stopped_stage(folder: Path) -> str:
    """中断した段階（work / change / queued / plan）。中断していなければ空。"""
    try:
        return str(json.loads((folder / STOP_MARK).read_text(encoding="utf-8")).get("stage", "")) or "work"
    except (OSError, ValueError):
        return ""


def mark_stopped(folder: Path, stage: str) -> None:
    data = {"stage": stage, "at": datetime.now().isoformat(timespec="seconds")}
    (folder / STOP_MARK).write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


class Monitor:
    def __init__(
        self,
        interval: int = 120,
        open_issues: Callable[[], dict[str, int]] = start.open_issues,
        evaluate: Callable[[dict, int], read_answers.Result] = read_answers.evaluate,
        apply: Callable[[Path, dict, read_answers.Result, int], None] = read_answers.apply_and_comment,
        launch: Callable[[Path, int], subprocess.Popen] = watch.launch_claude,
        launch_change: Callable[[Path, int], subprocess.Popen] = watch.launch_change_review,
        fetch: Callable[[int], tuple[str, str]] = read_answers.fetch_issue,
        output: Path | None = None,
    ) -> None:
        self.interval = interval
        self._open_issues, self._evaluate, self._apply, self._launch = open_issues, evaluate, apply, launch
        self._launch_change, self._fetch = launch_change, fetch
        self._kind: dict[Path, str] = {}  # 動いている Claude の種類: "change"（意図の読み取り）/ "work"（作業）
        self._waiting: set[Path] = set()  # 意図を読み取って Issue に聞いたので、人の返事を待っているもの
        self._queued: set[Path] = set()  # 回答は揃ったが、ほかの本・号の Claude が動いているので、順番を待っているもの
        self._output = output
        self.running: dict[Path, subprocess.Popen] = {}
        self.last_check: datetime | None = None
        self.error = ""
        self.started: list[str] = []  # 起動した本・号の名前
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @staticmethod
    def _digest(content: tuple[str, str]) -> str:
        return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode("utf-8")).hexdigest()

    @staticmethod
    def _handed_digest(plan_path: Path) -> str:
        """Claude に渡したときの Issue の内容。起動し直しても二度渡さないよう、ファイルに残す。"""
        try:
            return (plan_path.parent / "claude-change.hash").read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _busy(self) -> bool:
        """どれかの Claude が動いているか。同時に動かすのは1本だけ（コミット・プッシュや work-gai/ の衝突を避ける）。"""
        return any(proc.poll() is None for proc in self.running.values())

    def _process(self, plan_path: Path, number: int) -> read_answers.Result | None:
        """1つの本・号を確認し、揃っていれば反映して Claude を起動する。すでに動いていれば None。"""
        with self._lock:  # 定期の確認と画面のボタンが重なっても、二重に起動しない
            proc = self.running.get(plan_path)
            if proc is not None and proc.poll() is None:
                return None  # すでに Claude が動いている
            if stopped_stage(plan_path.parent):
                return None  # 画面で中断した（「再開」されるまで触らない）
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan.get("split", {}).get("approved"):
                return None  # すでに反映済み
            result = self._evaluate(plan, number)
            if result.status == "change":
                content = self._fetch(number)
                digest = self._digest(content)
                if self._handed_digest(plan_path) == digest:  # 同じ内容で、何度も起動しない
                    self._waiting.add(plan_path)
                elif self._busy():
                    self._queued.add(plan_path)  # 順番待ち（次の確認で、空いていれば渡す）
                else:
                    self._queued.discard(plan_path)
                    self._waiting.discard(plan_path)
                    (plan_path.parent / "claude-change.hash").write_text(digest, encoding="utf-8")
                    self.running[plan_path] = self._launch_change(plan_path, number)
                    self._kind[plan_path] = "change"
                    print(
                        f"[{datetime.now():%H:%M:%S}] Issue #{number} に「分け方を変えたい」が付いています。"
                        "チェックとコメントから意図を読み取っています。",
                        flush=True,
                    )
            if result.status != "change":
                self._waiting.discard(plan_path)
            if result.status not in ("ready", "change"):
                self._queued.discard(plan_path)
            if result.status == "ready" and self._busy():
                self._queued.add(plan_path)  # 順番待ち。反映もまだしない（次の確認で、空いていれば始める）
            elif result.status == "ready":
                self._queued.discard(plan_path)
                self._apply(plan_path, plan, result, number)
                self.running[plan_path] = self._launch(plan_path, number)
                self._kind[plan_path] = "work"
                # 作業開始.bat のウィンドウに出る
                print(
                    f"[{datetime.now():%H:%M:%S}] Issue #{number} の入力が完了しました。"
                    f"「{plan_path.parent.name}」の分割・ハイライト作業を開始しています。",
                    flush=True,
                )
            return result

    def answer(self, name: str) -> dict:
        """画面の「GitHub の回答を読み込む」と、返事・確定のあとの確認。

        次の確認を待たずに、いま Issue を読む。足りないところは problems で返す。
        """
        try:
            number = self._open_issues().get(name)
            plan_path = (self._output or start.OUTPUT) / name / "articles.json"
            if number is None or not plan_path.is_file():
                return {"ok": False, "problems": ["質問の Issue が見つかりません（すでに閉じていませんか）"]}
            result = self._process(plan_path, number)
        except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
            return {"ok": False, "problems": [f"Issue を確認できませんでした: {e}"]}
        if result is None and stopped_stage(plan_path.parent):
            return {"ok": False, "problems": ["中断しています。続けるときは「再開」を押してください"]}
        if result is None:
            if self._kind.get(plan_path) == "change":
                return {
                    "ok": True,
                    "message": "Claude が意図を読み取っています。終わると、このカードが「返事待ち」に変わります",
                }
            return {"ok": True, "message": "すでに作業を始めています"}
        if result.status == "ready" and plan_path in self._queued:
            return {"ok": True, "message": "回答を確認しました。ほかの作業が終わり次第、自動で始めます（順番待ち）"}
        if result.status == "ready":
            self.started.append(name)
            return {"ok": True, "message": "回答を確認しました。作業を始めます"}
        if result.status == "change" and plan_path in self._waiting:
            return {
                "ok": True,
                "message": "Claude は意図を読み取り済みで、あなたの返事を待っています。"
                "画面の「Claude からの質問」（または Issue のコメント）で返事を送るか、"
                "「分け方を変えたい」のチェックを外してから、もう一度押してください",
            }
        if result.status == "change" and plan_path in self._queued:
            return {
                "ok": True,
                "message": "「分け方を変えたい」が付いています。ほかの作業が終わり次第、意図を読み取ります",
            }
        if result.status == "change":
            return {
                "ok": True,
                "message": "意図の読み取りを始めました。終わると、このカードが「返事待ち」に変わります（数分）。"
                "それまで Issue を見る必要はありません",
            }
        return {"ok": False, "problems": result.problems or ["回答が揃っていません"]}

    def interrupt(self, plan_path: Path) -> str:
        """画面の「中断」。動いている Claude を止めるか、順番待ちから外して、中断の印を置く。止めた段階を返す。"""
        with self._lock:
            proc = self.running.get(plan_path)
            if proc is not None and proc.poll() is None:
                stage = self._kind.get(plan_path, "work")
                kill_tree(proc)
            elif plan_path in self._queued:
                stage = "queued"
            else:
                raise ValueError("止める作業がありません（すでに終わっていませんか）")
            self._queued.discard(plan_path)
            self._waiting.discard(plan_path)
            mark_stopped(plan_path.parent, stage)
            return stage

    def resume(self, plan_path: Path, number: int) -> dict:
        """画面の「再開」。作業の途中なら Claude を起動し直し、それ以外は印を外して、すぐ Issue を確かめる。"""
        folder = plan_path.parent
        with self._lock:
            proc = self.running.get(plan_path)
            if proc is not None and proc.poll() is None:
                raise ValueError("すでに動いています")
            approved = json.loads(plan_path.read_text(encoding="utf-8")).get("split", {}).get("approved")
            if not stopped_stage(folder) and not approved:
                raise ValueError("中断していません")  # 反映済みなら、印が無くても（途中で止まったものを）再開できる
            if approved and self._busy():  # 同時に動かすのは1本だけ。印は外さない
                raise ValueError("ほかの本・号の作業が動いています。終わってから、もう一度「再開」を押してください")
            (folder / STOP_MARK).unlink(missing_ok=True)
            # 意図の読み取りを途中で止めたときは、同じ内容でも、もう一度渡す（返事待ちと見なさない）
            (folder / "claude-change.hash").unlink(missing_ok=True)
            if approved:  # 反映済み = 重要箇所の選定〜仕上げの途中。続きを起動する
                self.running[plan_path] = self._launch(plan_path, number)
                self._kind[plan_path] = "work"
                return {"ok": True, "message": "作業を再開しました（途中まで選んだ重要箇所は、そのまま使います）"}
        result = self.answer(folder.name)
        return {**result, "ok": True, "message": result.get("message") or "再開しました。Issue の回答を確かめます"}

    def forget(self, plan_path: Path) -> None:
        """差し替えた本・号の、覚えている状態を捨てる（古い「返事待ち」「順番待ち」が残らないように）。"""
        with self._lock:
            self._waiting.discard(plan_path)
            self._queued.discard(plan_path)
            self._kind.pop(plan_path, None)
            proc = self.running.get(plan_path)
            if proc is not None and proc.poll() is not None:
                del self.running[plan_path]

    def tick(self) -> list[str]:
        """1回確認する。反映して Claude を起動した本・号の名前を返す。"""
        started = []
        try:
            for plan_path, number in start.pending_books(self._open_issues(), self._output or start.OUTPUT):
                result = self._process(plan_path, number)
                if result is not None and result.status == "ready" and plan_path not in self._queued:
                    started.append(plan_path.parent.name)
            self.error = ""
        except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
            self.error = str(e)  # 一時的な失敗（ネットワークなど）。次の回で、もう一度試す
        self.last_check = datetime.now()
        self.started += started
        return started

    def loop(self) -> None:
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval)

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.loop, daemon=True, name="monitor")
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    def info(self) -> dict:
        return {
            "interval": self.interval,
            "last_check": self.last_check.strftime("%H:%M:%S") if self.last_check else "",
            "error": self.error,
            "started": self.started,
            "working": [p.parent.name for p, proc in self.running.items() if proc.poll() is None],
            "kinds": {
                p.parent.name: self._kind.get(p, "work") for p, proc in self.running.items() if proc.poll() is None
            },
            "queued": [p.parent.name for p in self._queued],
            "waiting": [p.parent.name for p in self._waiting],
        }
