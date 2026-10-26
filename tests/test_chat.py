import pathlib
import subprocess
import threading
import time

import pytest

from strata.chat import (MAX_DIFF_BYTES, MAX_STATUS_BYTES, ChatError,
                         ChatSupervisor)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE).stdout.decode().strip()


def make_repo(path):
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.email", "test@example.test")
    git(path, "config", "user.name", "Test")
    (path / "tracked.txt").write_text("base\n")
    git(path, "add", "tracked.txt")
    git(path, "commit", "-qm", "base")
    return path


class FakeSession:
    def __init__(self, cwd, provider="codex", model=None):
        self.cwd, self.provider, self.model = pathlib.Path(cwd), provider, model
        self.closed = False
        self.calls = []
        self._events = []

    def start(self): return "thread-fake"
    def turn(self, message): self.calls.append(("turn", message)); return "turn-fake"
    def events(self, after=0): return [event for event in self._events if event["seq"] > after]
    def decide(self, approval_id, allow): self.calls.append(("decide", approval_id, allow)); return True
    def cancel(self): self.calls.append(("cancel",)); return True
    def close(self): self.closed = True
    def login(self): return {"authUrl": "https://auth.openai.com/oauth/authorize?client_id=test", "loginId": "login"}
    def cancel_login(self, login_id): return login_id == "login"


def setup_supervisor(tmp_path, *, max_sessions=4):
    root = make_repo(tmp_path / "repo")
    made = []
    def factory(cwd, **kwargs):
        session = FakeSession(cwd, **kwargs); made.append(session); return session
    supervisor = ChatSupervisor({"project": root}, session_factory=factory, max_sessions=max_sessions)
    return root, supervisor, made


def test_worktree_is_detached_and_source_checkout_is_unchanged(tmp_path):
    root, supervisor, made = setup_supervisor(tmp_path)
    (root / "tracked.txt").write_text("dirty source\n")
    (root / "source-only.txt").write_text("untracked source\n")
    before = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    started = supervisor.start("project", root)
    worktree = pathlib.Path(started["worktree"])
    assert worktree.parent == root.parent / ".strata-worktrees" / "project"
    assert worktree.name.startswith("chat-")
    assert (worktree / "tracked.txt").read_text() == "base\n"
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == before
    assert git(worktree, "rev-parse", "--show-toplevel") == str(worktree)
    assert made[0].cwd == worktree
    supervisor.shutdown()
    assert worktree.exists()


def test_rejects_unregistered_nonrepo_nested_root_and_symlink(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path)
    with pytest.raises(ChatError, match="registered"):
        supervisor.start("other", root)
    nonrepo = tmp_path / "nonrepo"; nonrepo.mkdir()
    bad = ChatSupervisor({"bad": nonrepo}, session_factory=FakeSession)
    with pytest.raises(ChatError): bad.start("bad", nonrepo)
    nested = root / "subdir"; nested.mkdir()
    nested_supervisor = ChatSupervisor({"nested": nested}, session_factory=FakeSession)
    with pytest.raises(ChatError): nested_supervisor.start("nested", nested)
    link = tmp_path / "repo-link"; link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ChatError, match="symlink"):
        ChatSupervisor({"linked": link}, session_factory=FakeSession)


def test_operations_are_project_bound_and_delegated(tmp_path):
    _, supervisor, made = setup_supervisor(tmp_path)
    started = supervisor.start("project", tmp_path / "repo")
    sid = started["session_id"]
    assert supervisor.turn("project", sid, "hello") == "turn-fake"
    assert supervisor.decide("project", sid, "approval", True) is True
    assert supervisor.cancel("project", sid) is True
    with pytest.raises(ChatError, match="not found"):
        supervisor.turn("other", sid, "wrong project")
    assert supervisor.close("project", sid) is True
    assert supervisor.close("project", sid) is False
    assert made[0].closed


def test_session_limit_and_shutdown_retain_worktrees(tmp_path):
    root, supervisor, made = setup_supervisor(tmp_path, max_sessions=1)
    first = supervisor.start("project", root)
    with pytest.raises(ChatError, match="maximum"):
        supervisor.start("project", root)
    worktree = pathlib.Path(first["worktree"])
    supervisor.shutdown()
    assert made[0].closed and worktree.exists()
    with pytest.raises(ChatError, match="shutting down"):
        supervisor.start("project", root)


def test_diff_and_status_retain_tracked_diff_and_untracked_status(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path)
    started = supervisor.start("project", root)
    worktree = pathlib.Path(started["worktree"])
    (worktree / "tracked.txt").write_text("changed in worktree\n")
    (worktree / "new.txt").write_text("untracked\n")
    report = supervisor.diff_status("project", started["session_id"])
    assert "changed in worktree" in report["diff"]
    assert "untracked" in report["diff"]
    assert "tracked.txt" in report["status"] and "new.txt" in report["status"]
    supervisor.close("project", started["session_id"])
    assert "changed in worktree" in supervisor.diff("project", started["session_id"])["diff"]
    assert worktree.exists()


def test_login_url_is_validated_and_never_auto_opened(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path)
    started = supervisor.start("project", root)
    response = supervisor.login("project", started["session_id"])
    assert response["url"].startswith("https://auth.openai.com/")
    assert response["login_id"] == "login"
    assert supervisor.cancel_login("project", started["session_id"], "login") is True

    session = supervisor._get("project", started["session_id"])["session"]
    for url in (
        "https://chatgpt.com/oauth/authorize?client_id=test",
        "https://auth.openai.com/oauth/authorize?client_id=test",
        "https://chatgpt.com:443/oauth/authorize",
    ):
        session.login = lambda url=url: {"authUrl": url}
        assert supervisor.login("project", started["session_id"])["url"] == url

    for url in (
        "https://evil.example/oauth",
        "http://chatgpt.com/oauth",
        "https://user:pass@auth.openai.com/path",
        "https://chatgpt.com:444/oauth",
        "https://chatgpt.com/oauth#fragment",
        "https://chatgpt.com/#",
        "https://chatgpt.com:/login",
        "https://chatgpt.com/log\nin",
        "https://chatgpt.com/oauth\n",
        "https://chatgpt.com:bad/oauth",
    ):
        session.login = lambda url=url: {"authUrl": url}
        with pytest.raises(ChatError, match="unsupported login URL"):
            supervisor.login("project", started["session_id"])


def test_global_login_needs_no_project_worktree_and_restarts_attempts(tmp_path):
    made = []
    def factory(cwd, **kwargs):
        attempt = len(made) + 1
        class LoginSession(FakeSession):
            def login(self):
                self.calls.append(("login",))
                return {"authUrl": f"https://auth.openai.com/oauth/authorize?attempt={attempt}",
                        "loginId": f"login-{attempt}"}
            def cancel_login(self, login_id):
                self.calls.append(("cancel_login", login_id))
                return True
        session = LoginSession(cwd, **kwargs)
        made.append(session)
        return session
    supervisor = ChatSupervisor({}, session_factory=factory)

    first = supervisor.login_global()
    second = supervisor.login_global()
    assert first == {"url": "https://auth.openai.com/oauth/authorize?attempt=1", "login_id": "login-1"}
    assert second == {"url": "https://auth.openai.com/oauth/authorize?attempt=2", "login_id": "login-2"}
    assert len(made) == 2
    assert made[0].cwd == pathlib.Path.cwd()
    assert made[0].calls == [("login",), ("cancel_login", "login-1")]
    assert made[0].closed
    assert made[1].calls == [("login",)]  # no coding-thread start or turn
    supervisor.shutdown()
    assert made[1].closed


def test_global_login_failure_closes_session_and_allows_retry():
    made = []
    class InvalidLoginSession(FakeSession):
        def login(self): return {"authUrl": "https://evil.example/", "loginId": "bad"}
    def factory(cwd, **kwargs):
        session = InvalidLoginSession(cwd, **kwargs)
        made.append(session)
        return session
    supervisor = ChatSupervisor({}, session_factory=factory)

    with pytest.raises(ChatError, match="unsupported login URL"):
        supervisor.login_global()
    assert made[0].closed
    supervisor._session_factory = lambda cwd, **kwargs: FakeSession(cwd, **kwargs)
    assert supervisor.login_global()["url"].startswith("https://auth.openai.com/")
    supervisor.shutdown()


def test_login_events_filter_untrusted_urls(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path)
    started = supervisor.start("project", root)
    session = supervisor._get("project", started["session_id"])["session"]
    session._events = [
        {"seq": 1, "type": "login_started", "data": {"authUrl": "https://evil.example/"}},
        {"seq": 2, "type": "login_started", "data": {"authUrl": "https://chatgpt.com/login"}},
        {"seq": 3, "type": "login_status", "data": {"url": "https://auth.openai.com/login"}},
        {"seq": 4, "type": "text_delta", "data": {"text": "ok"}},
    ]
    assert [event["seq"] for event in supervisor.events("project", started["session_id"])] == [2, 3, 4]


def test_closed_session_frees_live_slot_but_keeps_review_record(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path, max_sessions=1)
    first = supervisor.start("project", root)
    supervisor.close("project", first["session_id"])
    second = supervisor.start("project", root)
    assert second["session_id"] != first["session_id"]
    assert pathlib.Path(first["worktree"]).exists()


def test_repo_configured_helpers_and_filters_never_execute(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path)
    marker = tmp_path / "helper-ran"
    script = tmp_path / "helper.py"
    script.write_text(f"#!/usr/bin/env python3\nfrom pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n")
    script.chmod(0o755)
    (root / ".gitattributes").write_text("*.txt diff=hostile filter=hostile\n")
    git(root, "add", ".gitattributes")
    git(root, "commit", "-qm", "attributes")
    for key in ("core.fsmonitor", "diff.hostile.textconv", "diff.external",
                "filter.hostile.clean", "filter.hostile.smudge", "filter.hostile.process"):
        git(root, "config", key, str(script))

    started = supervisor.start("project", root)
    worktree = pathlib.Path(started["worktree"])
    (worktree / "tracked.txt").write_text("changed\n")
    report = supervisor.diff_status("project", started["session_id"])
    assert "changed" in report["diff"]
    assert not marker.exists()


def test_large_status_and_diff_capture_are_bounded_and_report_truncation(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path)
    started = supervisor.start("project", root)
    worktree = pathlib.Path(started["worktree"])
    for number in range(5000):
        (worktree / f"untracked-{number:04}.txt").write_text(f"line {number} " + "x" * 60 + "\n")
    report = supervisor.diff_status("project", started["session_id"])
    assert len(report["status"].encode()) <= MAX_STATUS_BYTES
    assert len(report["diff"].encode()) <= MAX_DIFF_BYTES
    assert report["status_truncated"] is True
    assert report["diff_truncated"] is True
    assert "truncated" in report["status"] and "truncated" in report["diff"]


def test_untracked_symlink_binary_and_large_files_are_described_safely(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path)
    started = supervisor.start("project", root)
    worktree = pathlib.Path(started["worktree"])
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("outside secret content")
    (worktree / "outside-link").symlink_to(outside)
    (worktree / "binary.dat").write_bytes(b"\0hidden binary payload")
    (worktree / "large.txt").write_text("x" * (MAX_DIFF_BYTES + 1))
    report = supervisor.diff_status("project", started["session_id"])
    assert "symlink target omitted" in report["diff"]
    assert "binary file content omitted" in report["diff"]
    assert "large file content omitted" in report["diff"]
    assert "outside secret content" not in report["diff"]


def test_symlinked_ancestor_is_rejected(tmp_path):
    root, _, _ = setup_supervisor(tmp_path)
    alias = tmp_path / "repo-parent-link"
    alias.symlink_to(root.parent, target_is_directory=True)
    supervisor = ChatSupervisor({"project": root}, session_factory=FakeSession)
    with pytest.raises(ChatError, match="ancestor"):
        supervisor.start("project", alias / root.name)


def test_failed_start_keeps_discoverable_worktree_and_closes_agent(tmp_path):
    root = make_repo(tmp_path / "repo")
    sessions = []
    class FailingSession(FakeSession):
        def start(self): raise RuntimeError("simulated startup failure")
    def factory(cwd, **kwargs):
        session = FailingSession(cwd, **kwargs); sessions.append(session); return session
    supervisor = ChatSupervisor({"project": root}, session_factory=factory)
    with pytest.raises(ChatError, match="retained") as caught:
        supervisor.start("project", root)
    assert caught.value.session_id
    worktree = pathlib.Path(caught.value.worktree)
    assert worktree.exists() and sessions[0].closed
    report = supervisor.diff_status("project", caught.value.session_id)
    assert report["startup_error"] == "simulated startup failure"
    assert report["worktree"] == str(worktree)


def test_login_required_retains_session_and_defers_thread_until_first_turn(tmp_path, monkeypatch):
    from strata.chat import CodexSession

    root = make_repo(tmp_path / "repo")
    sessions = {}
    monkeypatch.setattr(CodexSession, "auth_status", classmethod(
        lambda cls, provider="codex", **kwargs: {"provider": provider, "status": "login_required"}))
    def fake_init(self, cwd, provider="codex", model=None, **kwargs):
        self.cwd, self.provider, self.model = pathlib.Path(cwd), provider, model
        self.closed = False
        self.calls = []
        self.started = False
        self._events = []
        sessions["session"] = self
    def fake_start(self):
        self.started = True
        self.calls.append(("start",))
        return "thread-after-login"
    def fake_login(self):
        return {"authUrl": "https://auth.openai.com/oauth/authorize?client_id=test", "loginId": "login"}
    def fake_turn(self, message):
        if not self.started:
            self.start()
        self.calls.append(("turn", message))
        return "turn-fake"
    monkeypatch.setattr(CodexSession, "__init__", fake_init)
    monkeypatch.setattr(CodexSession, "start", fake_start)
    monkeypatch.setattr(CodexSession, "login", fake_login)
    monkeypatch.setattr(CodexSession, "turn", fake_turn)
    supervisor = ChatSupervisor({"project": root})
    started = supervisor.start("project", root)
    assert started["thread_id"] is None
    assert pathlib.Path(started["worktree"]).is_dir()
    session = sessions["session"]
    assert not session.started

    assert supervisor.login("project", started["session_id"])["url"].startswith("https://auth.openai.com/")
    assert not session.closed
    assert supervisor.turn("project", started["session_id"], "hello") == "turn-fake"
    assert session.calls == [("start",), ("turn", "hello")]


def test_registry_refresh_add_change_remove_invalidates_stale_sessions(tmp_path):
    root_a = make_repo(tmp_path / "repo-a")
    root_b = make_repo(tmp_path / "repo-b")
    root_c = make_repo(tmp_path / "repo-c")
    made = []
    def factory(cwd, **kwargs):
        session = FakeSession(cwd, **kwargs); made.append(session); return session
    supervisor = ChatSupervisor({"project": root_a, "other": root_c}, session_factory=factory)
    original = supervisor.start("project", root_a)
    removed = supervisor.start("other", root_c)
    original_worktree = pathlib.Path(original["worktree"])
    removed_worktree = pathlib.Path(removed["worktree"])

    # Adding a project keeps existing sessions valid and makes the new
    # registration available immediately.
    supervisor.refresh_projects({"project": root_a, "other": root_c, "added": root_b})
    assert supervisor.turn("project", original["session_id"], "still valid") == "turn-fake"
    added = supervisor.start("added", root_b)
    assert pathlib.Path(added["worktree"]).exists()

    # A changed root closes the old agent, leaves its worktree for inspection,
    # and lets subsequent sessions use only the new root.
    supervisor.update_projects({"project": root_b, "added": root_b})
    assert made[0].closed
    assert original_worktree.exists()
    with pytest.raises(ChatError, match="invalidated"):
        supervisor.turn("project", original["session_id"], "stale")
    replacement = supervisor.start("project", root_b)
    assert pathlib.Path(replacement["worktree"]).parent == root_b.parent / ".strata-worktrees" / "project"

    # Removing a project invalidates its sessions in the same refresh.
    supervisor.refresh_projects({"project": root_b})
    assert made[1].closed
    assert removed_worktree.exists()
    with pytest.raises(ChatError, match="invalidated"):
        supervisor.diff_status("other", removed["session_id"])
    with pytest.raises(ChatError, match="not registered"):
        supervisor.start("other", root_c)
    supervisor.shutdown()


def test_registry_refresh_waits_for_inflight_operation(tmp_path):
    root, _, _ = setup_supervisor(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    made = []
    class BlockingSession(FakeSession):
        def turn(self, message):
            entered.set()
            assert release.wait(2)
            return super().turn(message)
    def factory(cwd, **kwargs):
        session = BlockingSession(cwd, **kwargs); made.append(session); return session
    supervisor = ChatSupervisor({"project": root}, session_factory=factory)
    started = supervisor.start("project", root)
    operation_result = []
    operation = threading.Thread(target=lambda: operation_result.append(
        supervisor.turn("project", started["session_id"], "in flight")))
    operation.start()
    assert entered.wait(1)
    refreshed = threading.Event()
    refresh = threading.Thread(target=lambda: (supervisor.refresh_projects({}), refreshed.set()))
    refresh.start()
    time.sleep(.05)
    assert not refreshed.is_set() and not made[0].closed
    release.set()
    operation.join(2); refresh.join(2)
    assert operation_result == ["turn-fake"] and refreshed.is_set() and made[0].closed
    with pytest.raises(ChatError, match="invalidated"):
        supervisor.events("project", started["session_id"])


def test_registry_refresh_rejects_symlink_alias_to_same_root(tmp_path):
    root, supervisor, _ = setup_supervisor(tmp_path)
    started = supervisor.start("project", root)
    alias = tmp_path / "repo-alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ChatError, match="symlink"):
        supervisor.refresh_projects({"project": alias})
    # Failed refresh is atomic: the prior valid registry remains active and
    # the alias cannot be used to start a new session.
    assert supervisor.turn("project", started["session_id"], "still registered") == "turn-fake"
    with pytest.raises(ChatError, match="symlink"):
        supervisor.start("project", alias)
