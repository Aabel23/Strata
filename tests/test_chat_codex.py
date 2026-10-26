import json
import queue
import threading
import time

import pytest

from strata.chat_codex import (MAX_EVENT_BYTES, MAX_PENDING_APPROVALS, MAX_REPLAY_BYTES,
                               CodexError, CodexSession, _child_env, _safe_url,
                               _terminate_and_reap)


class FakeStdout:
    def __init__(self): self.lines = queue.Queue()
    def readline(self, size=-1):
        line = self.lines.get()
        return "" if line is None else line
    def put(self, value): self.lines.put(value if isinstance(value, str) else json.dumps(value) + "\n")


class FakeStdin:
    def __init__(self, proc): self.proc = proc; self.messages = []
    def write(self, raw):
        message = json.loads(raw); self.messages.append(message)
        if "result" in message or "error" in message: return len(raw)
        method, request_id = message.get("method"), message.get("id")
        if request_id is None: return len(raw)
        if method == "initialize": result = {"userAgent": "fake"}
        elif method in ("thread/start", "thread/resume"):
            result = {"thread": {"id": "thread-1" if method == "thread/start" else message["params"]["threadId"]}}
            self.proc.stdout.put({"jsonrpc": "2.0", "method": "thread/started", "params": result})
        elif method == "turn/start": result = {"turn": {"id": "turn-1"}}
        elif method == "turn/interrupt": result = {}
        elif method == "account/read": result = {"account": {"type": "chatgpt"}, "requiresOpenaiAuth": False}
        elif method == "account/login/start": result = {"type": "chatgpt", "loginId": "login-1", "authUrl": "https://auth.example.test/start"}
        elif method == "account/login/cancel": result = {"status": "canceled"}
        elif method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            result = {"accepted": True}
        else: result = {}
        self.proc.stdout.put({"jsonrpc": "2.0", "id": request_id, "result": result})
        return len(raw)
    def flush(self): pass


class FakeProc:
    def __init__(self):
        self.stdout = FakeStdout(); self.stdin = FakeStdin(self); self.terminated = False
        self.waited = False; self.killed = False
    def terminate(self):
        self.terminated = True
        self.stdout.put(None)
    def wait(self, timeout=None): self.waited = True; return 0
    def kill(self): self.killed = True; self.terminate()


def factory(children):
    def popen(args, **kwargs):
        child = FakeProc(); children.append((args, kwargs, child)); return child
    return popen


def make_session(tmp_path, **kwargs):
    children = []
    session = CodexSession(tmp_path, popen=factory(children), rpc_timeout=1, **kwargs)
    return session, children


def test_lifecycle_streaming_and_ordered_replay(tmp_path):
    session, children = make_session(tmp_path)
    assert session.start() == "thread-1"
    assert session.turn("hello") == "turn-1"
    child = children[0][2]
    child.stdout.put({"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {"delta": "hi"}})
    child.stdout.put({"jsonrpc": "2.0", "method": "item/started", "params": {"item": {"type": "commandExecution", "command": "ls"}}})
    child.stdout.put({"jsonrpc": "2.0", "method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}}})
    deadline = time.time() + 1
    while time.time() < deadline and len(session.events()) < 5: time.sleep(.01)
    events = session.events()
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    assert [e["type"] for e in events if e["type"] in {"text_delta", "item_started", "turn_completed"}] == ["text_delta", "item_started", "turn_completed"]
    assert session.events(events[1]["seq"]) == events[2:]
    assert session.inference_status["inference_verified"] is True
    thread_start = next(m for m in children[0][2].stdin.messages if m.get("method") == "thread/start")
    assert thread_start["params"]["sandbox"] == "read-only"
    assert thread_start["params"]["approvalPolicy"] == "on-request"
    session.close()
    assert children[0][2].terminated


def test_resume_persisted_thread_and_bound_replay(tmp_path):
    session, children = make_session(tmp_path, replay_limit=10)
    assert session.resume("saved-thread") == "saved-thread"
    child = children[0][2]
    assert next(m for m in child.stdin.messages if m.get("method") == "thread/resume")["params"]["threadId"] == "saved-thread"
    for n in range(15):
        session._emit("test", {"n": n})
    retained = session.events()
    assert len(retained) == 10 and retained[0]["seq"] > 1
    session.close()


def test_launch_and_turn_are_serialized_across_threads(tmp_path):
    session, children = make_session(tmp_path)
    barrier = threading.Barrier(3)
    outcomes = []
    def start():
        barrier.wait(); outcomes.append(session.start())
    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads: thread.start()
    barrier.wait()
    for thread in threads: thread.join()
    assert outcomes == ["thread-1", "thread-1"]
    assert len(children) == 1
    barrier = threading.Barrier(3)
    turn_outcomes = []
    def send_turn(text):
        barrier.wait()
        try: turn_outcomes.append(session.turn(text))
        except CodexError: turn_outcomes.append("busy")
    threads = [threading.Thread(target=send_turn, args=(str(n),)) for n in range(2)]
    for thread in threads: thread.start()
    barrier.wait()
    for thread in threads: thread.join()
    assert sorted(turn_outcomes) == ["busy", "turn-1"]
    assert len([m for m in children[0][2].stdin.messages if m.get("method") == "turn/start"]) == 1
    session.close()


def test_malformed_and_oversized_events_are_normalized(tmp_path):
    session, children = make_session(tmp_path)
    session.start()
    child = children[0][2]
    child.stdout.put("{bad json\n")
    child.stdout.put("x" * 1_000_002 + "\n")
    deadline = time.time() + 1
    while time.time() < deadline and len([e for e in session.events() if e["type"] == "protocol_error"]) < 2: time.sleep(.01)
    errors = [e for e in session.events() if e["type"] == "protocol_error"]
    assert len(errors) == 2
    assert all("bad json" not in json.dumps(e) for e in errors)
    session.close()


def test_approval_is_one_use_and_denial_reaches_codex(tmp_path):
    session, children = make_session(tmp_path)
    session.start(); child = children[0][2]
    child.stdout.put({"jsonrpc": "2.0", "id": 77, "method": "item/fileChange/requestApproval",
                      "params": {"itemId": "i1", "threadId": "thread-1", "turnId": "turn-1",
                                 "reason": "apply edit", "changes": [{"path": "a.py"}]}})
    deadline = time.time() + 1
    while time.time() < deadline and not [e for e in session.events() if e["type"] == "approval_required"]: time.sleep(.01)
    approval = next(e for e in session.events() if e["type"] == "approval_required")["data"]["approval_id"]
    assert session.decide(approval, False) is True
    assert session.decide(approval, True) is False
    response = next(m for m in child.stdin.messages if m.get("id") == 77)
    assert response["result"] == {"decision": "decline"}
    session.close()


def test_unknown_server_request_is_rejected_not_auto_approved(tmp_path):
    session, children = make_session(tmp_path)
    session.start(); child = children[0][2]
    child.stdout.put({"jsonrpc": "2.0", "id": 99, "method": "item/permissions/requestApproval", "params": {"permissions": []}})
    deadline = time.time() + 1
    while time.time() < deadline and not [m for m in child.stdin.messages if m.get("id") == 99]: time.sleep(.01)
    response = next(m for m in child.stdin.messages if m.get("id") == 99)
    assert response["error"]["code"] == -32601
    assert next(e for e in session.events() if e["type"] == "approval_unsupported")
    session.close()


def test_pending_approval_limit_fails_closed(tmp_path):
    session, children = make_session(tmp_path)
    session.start(); child = children[0][2]
    for i in range(MAX_PENDING_APPROVALS + 1):
        child.stdout.put({"jsonrpc": "2.0", "id": 1000 + i,
                          "method": "item/fileChange/requestApproval",
                          "params": {"itemId": f"item-{i}", "threadId": "thread-1", "turnId": "turn-1",
                                     "changes": [{"path": f"file-{i}.txt"}]}})
    deadline = time.time() + 2
    while time.time() < deadline and not [e for e in session.events() if e["type"] == "approval_overflow"]: time.sleep(.01)
    assert len(session._pending) == MAX_PENDING_APPROVALS
    assert any(e["type"] == "approval_overflow" for e in session.events())
    assert next(m for m in child.stdin.messages if m.get("id") == 1000 + MAX_PENDING_APPROVALS)["error"]["code"] == -32000
    session.close()


def test_event_payload_and_aggregate_replay_bytes_are_bounded(tmp_path):
    session, _ = make_session(tmp_path)
    session._emit("large", {"text": "x" * (MAX_EVENT_BYTES + 100)})
    assert session.events()[0]["type"] == "event_truncated"
    for i in range(100): session._emit("large", {"text": "x" * 50_000, "n": i})
    assert session._event_bytes <= MAX_REPLAY_BYTES
    assert len(session.events()) < 100
    session.close()


def test_unknown_response_ids_are_not_retained(tmp_path):
    children = []
    def popen(args, **kwargs):
        child = FakeProc(); children.append(child)
        child.stdout.put({"jsonrpc": "2.0", "id": 98765, "result": {"secret": "do not retain"}})
        return child
    session = CodexSession(tmp_path, popen=popen, rpc_timeout=1)
    session.start()
    deadline = time.time() + 1
    while time.time() < deadline and not [e for e in session.events() if e["type"] == "protocol_error"]: time.sleep(.01)
    assert not session._responses
    assert any("unknown app-server response" in json.dumps(e) for e in session.events())
    session.close()


def test_cancel_interrupts_active_turn_and_denies_pending_approval(tmp_path):
    session, children = make_session(tmp_path)
    session.start(); session.turn("do work")
    child = children[0][2]
    child.stdout.put({"jsonrpc": "2.0", "id": 88, "method": "item/commandExecution/requestApproval",
                      "params": {"itemId": "i2", "threadId": "thread-1", "turnId": "turn-1",
                                 "command": "rm x", "cwd": str(tmp_path), "reason": "write"}})
    deadline = time.time() + 1
    while time.time() < deadline and not [e for e in session.events() if e["type"] == "approval_required"]: time.sleep(.01)
    assert session.cancel() is True
    assert any(m.get("method") == "turn/interrupt" for m in child.stdin.messages)
    assert next(m for m in child.stdin.messages if m.get("id") == 88)["result"] == {"decision": "decline"}
    session.close()


def test_auth_status_is_readiness_only_and_login_url_is_supported(tmp_path):
    children = []
    status = CodexSession.auth_status(popen=factory(children), rpc_timeout=1)
    assert status == {"provider": "codex", "account_present": True, "requires_openai_auth": False,
                      "configured": True, "inference_verified": False, "status": "account_present"}
    session, login_children = make_session(tmp_path)
    login = session.login()
    assert login == {"type": "chatgpt", "loginId": "login-1", "authUrl": "https://auth.example.test/start"}
    assert session.cancel_login(login["loginId"]) is True
    assert next(m for m in login_children[0][2].stdin.messages if m.get("method") == "account/login/start")["params"] == {"type": "chatgpt"}
    assert session.inference_status["inference_verified"] is False
    session.close()


def test_provider_secrets_only_enter_child_environment(tmp_path):
    env = {"PATH": "/bin", "STRATA_OPENROUTER_API_KEY": "secret-key",
           "STRATA_OPENROUTER_BASE_URL": "https://openrouter.example/v1", "AWS_SECRET_ACCESS_KEY": "other-secret",
           "OPENAI_BASE_URL": "https://attacker.invalid", "HOME": "/tmp/user", "LANG": "en_US.UTF-8",
           "HTTPS_PROXY": "http://proxy.local:3128", "SSL_CERT_FILE": "/etc/ssl/certs/ca.pem"}
    children = []
    session = CodexSession(tmp_path, provider="openrouter", popen=factory(children), environ=env, rpc_timeout=1)
    session.start()
    args, kwargs, _ = children[0]
    assert "secret-key" not in args
    assert kwargs["env"]["OPENAI_API_KEY"] == "secret-key"
    assert kwargs["env"]["HOME"] == "/tmp/user" and kwargs["env"]["LANG"] == "en_US.UTF-8"
    assert kwargs["env"]["HTTPS_PROXY"] and kwargs["env"]["SSL_CERT_FILE"]
    assert "AWS_SECRET_ACCESS_KEY" not in kwargs["env"] and "OPENAI_BASE_URL" not in kwargs["env"]
    assert "model_providers.openrouter.requires_openai_auth=false" in args
    assert "STRATA_OPENROUTER_API_KEY" not in kwargs["env"]
    config = {args[i + 1].split("=", 1)[0]: args[i + 1].split("=", 1)[1]
              for i, arg in enumerate(args[:-1]) if arg == "-c"}
    assert config['shell_environment_policy.inherit'] == '"core"'
    assert config['shell_environment_policy.ignore_default_excludes'] == "false"
    assert "shell_environment_policy.filters." not in " ".join(args)
    assert json.loads(config["shell_environment_policy.include_only"]) == [
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_*", "TMPDIR", "TMP", "TEMP",
        "XDG_RUNTIME_DIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "PATHEXT", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
    ]
    assert json.loads(config["shell_environment_policy.exclude"]) == [
        "OPENAI_API_KEY", "STRATA_*", "*PROXY*", "*KEY*", "*SECRET*",
        "*TOKEN*", "*PASS*", "*CRED*", "*AUTH*", "*COOKIE*",
    ]
    assert not any("secret-key" in json.dumps(e) for e in session.events())
    session.close()
    with pytest.raises(ValueError):
        _child_env("openrouter", {"STRATA_OPENROUTER_API_KEY": "k", "STRATA_OPENROUTER_BASE_URL": "http://example.invalid"})


def test_provider_default_urls_and_missing_key_status():
    assert _child_env("openrouter", {"STRATA_OPENROUTER_API_KEY": "k"})["STRATA_OPENROUTER_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert _child_env("omniroute", {"STRATA_OMNIROUTE_API_KEY": "k"})["STRATA_OMNIROUTE_BASE_URL"] == "http://127.0.0.1:20128/v1"
    status = CodexSession.auth_status("openrouter", environ={})
    assert status["status"] == "configuration_required" and "secret" not in json.dumps(status)


@pytest.mark.parametrize("url", [
    "https://example.test/v1?api_key=secret", "https://example.test/v1#fragment",
    "https://user:pass@example.test/v1", "http://example.test/v1", "http://127.0.0.1/v1?x=1",
])
def test_provider_urls_reject_credentials_queries_and_fragments(url):
    assert not _safe_url(url)


def test_provider_url_defaults_are_safe():
    assert _safe_url("https://openrouter.ai/api/v1")
    assert _safe_url("http://127.0.0.1:20128/v1")


def test_startup_initialization_failure_terminates_and_reaps(tmp_path):
    class SilentProc(FakeProc):
        def __init__(self):
            super().__init__()
            self.stdin.write = lambda raw: len(raw)
    children = []
    session = CodexSession(tmp_path, popen=lambda *a, **kw: children.append(SilentProc()) or children[-1], rpc_timeout=1)
    with pytest.raises(CodexError): session.start()
    assert children[0].terminated and children[0].waited
    assert session._closed is True


def test_kill_path_is_reaped():
    class SlowChild(FakeProc):
        def wait(self, timeout=None):
            self.wait_calls = getattr(self, "wait_calls", 0) + 1
            if self.wait_calls == 1: raise TimeoutError()
            self.waited = True; return 0
    child = SlowChild()
    _terminate_and_reap(child)
    assert child.killed and child.waited and child.wait_calls == 2


def test_gateway_account_null_is_configured_not_login_required(tmp_path):
    children = []
    class ProviderProc(FakeProc):
        def __init__(self):
            super().__init__()
            original = self.stdin.write
            def write(raw):
                message = json.loads(raw)
                if message.get("method") == "account/read":
                    self.stdin.messages.append(message)
                    self.stdout.put({"jsonrpc": "2.0", "id": message["id"],
                                     "result": {"account": None, "requiresOpenaiAuth": False}})
                    return len(raw)
                return original(raw)
            self.stdin.write = write
    status = CodexSession.auth_status("openrouter", popen=lambda *a, **kw: children.append(ProviderProc()) or children[-1],
                                      environ={"STRATA_OPENROUTER_API_KEY": "test-key"}, rpc_timeout=1)
    assert status["status"] == "provider_configured"
    assert status["account_present"] is False and status["requires_openai_auth"] is False
    assert status["configured"] is True and status["inference_verified"] is False


def test_bad_inputs_and_missing_stale_approval(tmp_path):
    session, _ = make_session(tmp_path)
    with pytest.raises(ValueError): session.turn(" \n")
    assert session.decide("unknown", True) is False
    with pytest.raises(ValueError): session.events(-1)
    session.close()
