import json
import pathlib
import threading
import urllib.error
import urllib.request

import pytest

from strata import db, server
from strata.chat import ChatError


class FakeChatSupervisor:
    def __init__(self, projects):
        self.projects = dict(projects)
        self.refreshes = [dict(projects)]
        self.calls = []
        self.stopped = False
        self.sessions = set()

    def _bound(self, project, session_id):
        if (project, session_id) not in self.sessions:
            raise ChatError("chat session not found for this project")

    def refresh_projects(self, projects):
        self.projects = dict(projects)
        self.refreshes.append(dict(projects))

    def start(self, project, root, provider="codex", model=None):
        self.calls.append(("start", project, root, provider, model))
        self.sessions.add((project, "session-1"))
        return {"project": project, "session_id": "session-1", "thread_id": "thread-1", "worktree": "/tmp/worktree"}

    def turn(self, project, session_id, message):
        self._bound(project, session_id)
        self.calls.append(("turn", project, session_id, message))
        return "turn-1"

    def decide(self, project, session_id, approval_id, allow):
        self._bound(project, session_id)
        self.calls.append(("decide", project, session_id, approval_id, allow))
        return True

    def cancel(self, project, session_id):
        self._bound(project, session_id)
        self.calls.append(("cancel", project, session_id))
        return True

    def close(self, project, session_id):
        self._bound(project, session_id)
        self.calls.append(("close", project, session_id))
        return True

    def login(self, project, session_id):
        self._bound(project, session_id)
        self.calls.append(("login", project, session_id))
        return {"url": "https://auth.openai.com/oauth/authorize?client_id=x", "login_id": "login-1"}

    def cancel_login(self, project, session_id, login_id):
        self._bound(project, session_id)
        self.calls.append(("cancel_login", project, session_id, login_id))
        return True

    def events(self, project, session_id, after=0):
        self._bound(project, session_id)
        self.calls.append(("events", project, session_id, after))
        return [{"seq": 2, "type": "text_delta", "data": {"text": "hello"}}]

    @staticmethod
    def auth_status(provider="codex"):
        return {"provider": provider, "status": "login_required", "inference_verified": False}

    def diff_status(self, project, session_id):
        self._bound(project, session_id)
        self.calls.append(("diff", project, session_id))
        return {"status": " M file.py\n", "diff": "diff --git a/file.py b/file.py\n", "status_truncated": False,
                "diff_truncated": False, "worktree": "/tmp/worktree", "closed": False}

    def shutdown(self):
        self.stopped = True


@pytest.fixture
def chat_server(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db_path = tmp_path / "chat.db"
    conn = db.init(db_path)
    db.add_project(conn, "p", "Project", root=str(root))
    conn.close()
    made = []

    def factory(projects):
        supervisor = FakeChatSupervisor(projects)
        made.append(supervisor)
        return supervisor

    httpd = server.make_server(db_path, "p", 0, chat_supervisor_factory=factory)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    token = json.loads(get(base, "/api/session")[2])["token"]
    yield base, token, httpd, made[0], db_path, root
    httpd.shutdown()
    httpd.server_close()
    thread.join(2)


def get(base, path, *, token=None, host=None):
    headers = {}
    if token is not None:
        headers["X-Strata-Token"] = token
    if host is not None:
        headers["Host"] = host
    request = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def post(base, token, body, *, edit="1", origin=None, host=None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Strata-Token"] = token
    if edit is not None:
        headers["X-Strata-Edit"] = edit
    if origin is not None:
        headers["Origin"] = origin
    if host is not None:
        headers["Host"] = host
    request = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def decoded(response):
    return json.loads(response[2])


def test_chat_route_requires_all_edit_guards_and_get_token(chat_server):
    base, token, _, supervisor, *_ = chat_server
    body = {"op": "start", "project": "p"}
    assert post(base, None, body)[0] == 403
    assert post(base, token, body, edit=None)[0] == 403
    assert post(base, token, body, origin="http://evil.invalid")[0] == 403
    assert post(base, token, body, host="evil.invalid")[0] == 403
    assert get(base, "/api/chat/auth?provider=codex")[0] == 403
    assert get(base, "/api/chat/auth?provider=codex", token=token, host="evil.invalid")[0] == 403
    assert supervisor.calls == []


def test_start_rejects_browser_root_and_limits_provider_model(chat_server):
    base, token, _, supervisor, *_ = chat_server
    status, _, raw = post(base, token, {"op": "start", "project": "p", "root": "/attacker"})
    assert status == 400 and "root" not in raw.decode()
    status, _, raw = post(base, token, {"op": "start", "project": "p", "provider": "https://evil.invalid"})
    assert status == 400
    status, _, raw = post(base, token, {"op": "start", "project": "p", "model": "../secret"})
    assert status == 400
    status, _, raw = post(base, token, {"op": "start", "project": "p", "provider": "openrouter", "model": "vendor/model"})
    assert status == 200
    assert decoded((status, None, raw))["worktree"] == "/tmp/worktree"
    call = supervisor.calls[-1]
    assert call[:1] == ("start",) and pathlib.Path(call[2]).name == "repo"
    assert call[3:] == ("openrouter", "vendor/model")


def test_chat_operations_events_auth_diff_and_no_store(chat_server):
    base, token, _, supervisor, *_ = chat_server
    origin = base
    start = post(base, token, {"op": "start", "project": "p"}, origin=origin)
    assert start[0] == 200
    for body, expected in (
        ({"op": "turn", "project": "p", "session_id": "session-1", "message": "hello"}, "turn_id"),
        ({"op": "decide", "project": "p", "session_id": "session-1", "approval_id": "a1", "allow": False}, "accepted"),
        ({"op": "cancel", "project": "p", "session_id": "session-1"}, "cancelled"),
        ({"op": "close", "project": "p", "session_id": "session-1"}, "closed"),
        ({"op": "login", "project": "p", "session_id": "session-1"}, "url"),
        ({"op": "cancel_login", "project": "p", "session_id": "session-1", "login_id": "login-1"}, "cancelled"),
    ):
        result = post(base, token, body, origin=origin)
        assert result[0] == 200 and expected in decoded(result)
    url = "/api/chat/events?project=p&session_id=session-1&after=1"
    events = get(base, url, token=token)
    assert events[0] == 200 and events[1]["Cache-Control"] == "no-store"
    assert decoded(events)["events"][0]["seq"] == 2
    auth = get(base, "/api/chat/auth?provider=codex", token=token)
    assert decoded(auth)["inference_verified"] is False
    diff = get(base, "/api/chat/diff?project=p&session_id=session-1", token=token)
    assert "diff --git" in decoded(diff)["diff"] and diff[1]["Cache-Control"] == "no-store"
    login = next(call for call in supervisor.calls if call[0] == "login")
    assert login[1:] == ("p", "session-1")


def test_chat_project_registry_refreshes_from_database_each_operation(chat_server):
    base, token, _, supervisor, db_path, root = chat_server
    original = dict(supervisor.projects)
    changed = root.parent / "new-root"
    changed.mkdir()
    conn = db.connect(db_path)
    conn.execute("UPDATE project SET root=? WHERE id='p'", (str(changed),))
    conn.commit(); conn.close()
    response = post(base, token, {"op": "start", "project": "p"})
    assert response[0] == 200
    assert supervisor.refreshes[-1] == {"p": str(changed)}
    assert supervisor.refreshes[-1] != original
    assert pathlib.Path(supervisor.calls[-1][2]) == changed


def test_chat_binding_errors_are_safe_and_unknown_project_is_not_started(chat_server):
    base, token, _, supervisor, *_ = chat_server
    response = post(base, token, {"op": "start", "project": "missing"})
    assert response[0] == 404
    assert decoded(response) == {"error": "project is not registered for chat"}
    response = post(base, token, {"op": "turn", "project": "p", "session_id": "other", "message": "x"})
    assert response[0] == 409 and decoded(response) == {"error": "chat request could not be completed"}
    assert not any("secret" in json.dumps(call) for call in supervisor.calls)


def test_server_shutdown_stops_chat_supervisor(chat_server):
    _, _, httpd, supervisor, *_ = chat_server
    httpd.shutdown()
    assert supervisor.stopped


def test_server_starts_with_symlink_project_and_keeps_safe_project_available(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    good_root = tmp_path / "good"
    good_root.mkdir()
    alias = tmp_path / "linked"
    alias.symlink_to(real_root, target_is_directory=True)
    db_path = tmp_path / "projects.db"
    conn = db.init(db_path)
    db.add_project(conn, "linked", "Linked", root=str(alias))
    db.add_project(conn, "good", "Good", root=str(good_root))
    conn.close()
    httpd = server.make_server(db_path, "good", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        projects = get(base, "/api/projects")
        assert projects[0] == 200
        assert {p["id"] for p in json.loads(projects[2])} >= {"linked", "good"}
        token = json.loads(get(base, "/api/session")[2])["token"]
        rejected = post(base, token, {"op": "start", "project": "linked"})
        assert rejected[0] == 404
        assert decoded(rejected) == {"error": "project is not registered for chat"}
        assert get(base, "/api/version")[0] == 200
    finally:
        httpd.shutdown(); httpd.server_close(); thread.join(2)
