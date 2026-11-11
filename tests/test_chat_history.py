import json
import subprocess
import urllib.request

import pytest

from strata import db, server
from strata.chat import ChatError, ChatSupervisor
from strata.chat_claude import ClaudeSession
from strata.chat_history import ChatHistory


def make_repo(path):
    path.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.test"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "a.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=path, check=True)
    return path


class FakeClaude:
    """Stands in for ClaudeSession: forwards events to the listener like the real one."""
    def __init__(self, cwd, provider="claude", model=None, effort=None, permission="auto", resume=None, listener=None):
        self.cwd, self.model, self.effort, self.permission = cwd, model, effort, permission
        self.thread_id, self.listener, self.closed, self._events = resume, listener, False, []

    settings = property(lambda self: {"model": self.model or "", "effort": self.effort or "", "permission": self.permission})
    def start(self): return self.thread_id
    def emit(self, kind, data):
        event = {"seq": len(self._events) + 1, "type": kind, "data": data, "time": 1.0}
        self._events.append(event)
        self.listener and self.listener(event)
    def turn(self, message):
        self.listener({"type": "user_message", "data": {"text": message, "turn_id": "t"}, "time": 1.0})
        self.emit("turn_started", {"turn_id": "t"})
        self.thread_id = self.thread_id or "claude-session-1"
        self.emit("text_delta", {"text": "Hel", "item_id": "m1"})
        self.emit("text_delta", {"text": "lo", "item_id": "m1"})
        self.emit("turn_completed", {"turn": {"status": "completed"}})
        return "t"
    def events(self, after=0): return [e for e in self._events if e["seq"] > after]
    def close(self): self.closed = True


def test_history_coalesces_text_and_titles_from_first_message(tmp_path):
    h = ChatHistory(tmp_path)
    h.begin("p", "c1", worktree="/w")
    h.record("p", "c1", {"type": "user_message", "data": {"text": "  fix\nthe bug  "}, "time": 1})
    h.record("p", "c1", {"type": "turn_started", "data": {}})
    for part in ("a", "b"):
        h.record("p", "c1", {"type": "text_delta", "data": {"text": part, "item_id": "m"}})
    h.record("p", "c1", {"type": "turn_completed", "data": {"turn": {"status": "completed"}}})
    assert [e["type"] for e in h.events("p", "c1")] == ["user_message", "text", "turn_completed"]
    assert h.events("p", "c1")[1]["data"]["text"] == "ab"
    [chat] = h.list("p")
    assert chat["title"] == "fix the bug" and chat["turns"] == 1
    assert h.delete("p", "c1") and h.list("p") == []


@pytest.mark.parametrize("project,chat", [("../x", "c"), ("p", "../c"), ("p", "a/b"), (".p", "c")])
def test_history_rejects_paths(tmp_path, project, chat):
    with pytest.raises(ValueError):
        ChatHistory(tmp_path).meta(project, chat)


def test_claude_chat_is_saved_and_resumed_in_its_worktree(tmp_path):
    root = make_repo(tmp_path / "repo")
    made = []
    def factory(cwd, **kw):
        made.append(FakeClaude(cwd, **kw)); return made[-1]
    sup = ChatSupervisor({"p": root}, session_factory=factory, history=ChatHistory(tmp_path / "hist"))
    first = sup.start("p", root, provider="claude")
    assert first["chat_id"] == first["session_id"]
    sup.turn("p", first["session_id"], "hello there")
    chats = sup.history_list("p")
    assert chats[0]["id"] == first["chat_id"] and chats[0]["live"] and chats[0]["title"] == "hello there"
    events = sup.history_events("p", first["chat_id"])["events"]
    assert [e["type"] for e in events] == ["user_message", "text", "turn_completed"]
    with pytest.raises(ChatError):  # live chats are not deleted from under the user
        sup.history_forget("p", first["chat_id"])

    # A live chat is handed back as is, positioned after its current events.
    again = sup.start("p", root, provider="claude", resume=first["chat_id"])
    assert again["session_id"] == first["session_id"] and again["seq"] == 4

    sup.close("p", first["session_id"])
    resumed = sup.start("p", root, provider="claude", resume=first["chat_id"])
    assert resumed["session_id"] != first["session_id"] and resumed["chat_id"] == first["chat_id"]
    assert made[-1].thread_id == "claude-session-1" and str(made[-1].cwd) == first["worktree"]
    sup.turn("p", resumed["session_id"], "and more")
    assert sup.history_list("p")[0]["turns"] == 2

    # Without the worktree there is nothing to resume in.
    sup.close("p", resumed["session_id"])
    subprocess.run(["git", "worktree", "remove", "--force", first["worktree"]], cwd=root, check=True)
    with pytest.raises(ChatError):
        sup.start("p", root, provider="claude", resume=first["chat_id"])
    assert sup.history_events("p", first["chat_id"])["events"]  # still readable
    assert sup.history_forget("p", first["chat_id"]) and sup.history_list("p") == []


def test_unknown_chat_cannot_be_resumed(tmp_path):
    root = make_repo(tmp_path / "repo")
    sup = ChatSupervisor({"p": root}, session_factory=FakeClaude, history=ChatHistory(tmp_path / "hist"))
    with pytest.raises(ChatError):
        sup.start("p", root, provider="claude", resume="nope")


def test_claude_session_resumes_and_reports_user_messages(tmp_path):
    seen = []
    session = ClaudeSession(tmp_path, resume="abc-123", listener=seen.append, popen=None)
    assert session.thread_id == "abc-123"
    session._emit("error", {"message": "x"})
    assert seen[-1]["type"] == "error"
    with pytest.raises(ValueError):
        ClaudeSession(tmp_path, resume="../bad")


def test_history_routes(tmp_path):
    root = make_repo(tmp_path / "repo")
    db_path = tmp_path / "s.db"
    conn = db.init(db_path); db.add_project(conn, "p", "P", root=str(root)); conn.close()
    httpd = server.make_server(db_path, "p", 0)
    import threading
    t = threading.Thread(target=httpd.serve_forever, daemon=True); t.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        token = json.load(urllib.request.urlopen(base + "/api/session"))["token"]
        hist = ChatHistory(tmp_path / "s.db.chats")
        hist.begin("p", "c1"); hist.record("p", "c1", {"type": "user_message", "data": {"text": "hi"}})
        get = lambda path: json.load(urllib.request.urlopen(urllib.request.Request(base + path, headers={"X-Strata-Token": token})))
        assert [c["id"] for c in get("/api/chat/history?project=p")["chats"]] == ["c1"]
        assert get("/api/chat/history?project=p&chat_id=c1")["events"][0]["data"]["text"] == "hi"
        with pytest.raises(urllib.error.HTTPError) as bad:
            get("/api/chat/history?project=p&chat_id=../x")
        assert bad.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as no_token:
            urllib.request.urlopen(base + "/api/chat/history?project=p")
        assert no_token.value.code == 403
    finally:
        httpd.shutdown(); httpd.server_close()
