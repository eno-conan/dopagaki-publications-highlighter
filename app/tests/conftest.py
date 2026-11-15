import pytest

import repo_guard


@pytest.fixture(autouse=True)
def _repo_is_private(monkeypatch):
    """テストでは、書き込み先を非公開として扱う（gh を呼ばない）。ガード自体のテストは test_repo_guard.py"""
    monkeypatch.delenv(repo_guard.ENV_ALLOW, raising=False)
    monkeypatch.setattr(repo_guard, "repo_info", lambda: ("me/private-repo", "PRIVATE"))
