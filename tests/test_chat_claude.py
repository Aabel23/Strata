"""ClaudeSession / ClaudeLogin against a fake `claude` executable that speaks the CLI's stream-json protocol."""
import json, os, stat, sys, time
import pytest
from strata.chat import ChatSupervisor, ChatError
from strata.chat_claude import ClaudeError, ClaudeLogin, ClaudeSession, _child_env, check_images, safe_login_url

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

FAKE = r'''#!%s
import json, os, sys
a = sys.argv[1:]
if a[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": os.environ.get("FAKE_OUT") != "1", "authMethod": "claude.ai", "subscriptionType": "max", "email": "a@b.c"})); sys.exit(0)
if a[:2] == ["auth", "login"]:
    print("Opening browser to sign in…\nIf the browser didn't open, visit: " + os.environ.get("FAKE_URL", "https://claude.com/cai/oauth/authorize?code=true&state=s"), flush=True)
    sys.stdout.write("Paste code here if prompted > "); sys.stdout.flush()
    sys.exit(0 if sys.stdin.readline().strip() == "good-code" else 1)
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"argv": a, "cwd": os.getcwd(), "env": sorted(os.environ)}) + "\n")
out = lambda o: (sys.stdout.write(json.dumps(o) + "\n"), sys.stdout.flush())
for line in sys.stdin:
    m = json.loads(line)
    if m["type"] == "control_request":
        out({"type": "control_response", "response": {"subtype": "success", "request_id": m["request_id"], "response": {}}})
        out({"type": "result", "subtype": "error_during_execution", "is_error": True}); continue
    if m["type"] != "user": continue
    text = m["message"]["content"]
    if isinstance(text, list): open(os.environ["FAKE_LOG"] + ".content", "a").write(json.dumps(text) + "\n")
    out({"type": "system", "subtype": "init", "session_id": "sess-1"})
    if text == "die": sys.exit(3)
    if text == "wait": continue
    if text == "write":
        out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": "x.txt", "content": "hi"}}]}})
        out({"type": "control_request", "request_id": "r1", "request": {"subtype": "can_use_tool", "tool_name": "Write", "description": "x.txt", "input": {"file_path": "x.txt", "content": "hi"}}})
        r = json.loads(sys.stdin.readline())["response"]["response"]
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": r["behavior"] != "allow", "content": r.get("message") or "wrote " + r["updatedInput"]["file_path"]}]}})
    for part in ("Hel", "lo"):
        out({"type": "stream_event", "api_message_id": "m1", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": part}}})
    out({"type": "stream_event", "parent_tool_use_id": "sub", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "subagent chatter"}}})
    out({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 12, "total_cost_usd": 0.01, "num_turns": 1})
'''


@pytest.fixture
def env(tmp_path):
    exe = tmp_path / "claude"; exe.write_text(FAKE % sys.executable); exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return {"STRATA_CLAUDE_BIN": str(exe), "PATH": os.environ["PATH"], "HOME": str(tmp_path), "FAKE_LOG": str(tmp_path / "log"),
            "ANTHROPIC_API_KEY": "sk-secret", "OPENAI_API_KEY": "sk-other", "CLAUDECODE": "1"}


def collect(s, until, timeout=10, after=0):
    seen, out, end = after, [], time.time() + timeout
    while time.time() < end:
        for e in s.wait_events(seen, 0.5):
            seen = e["seq"]; out.append(e)
            if e["type"] == until: return out
    raise AssertionError(f"no {until}: {[e['type'] for e in out]}")


def session(tmp_path, env, **kw):
    # the fake reads its settings from the environment; the real allowlist would drop them
    s = ClaudeSession(tmp_path, environ=env, **kw); s._env.update({k: v for k, v in env.items() if k.startswith("FAKE_")}); return s


def test_child_gets_no_api_keys_and_no_parent_session_markers(env):
    child = _child_env(env)
    assert child["BROWSER"] == "true" and child["HOME"] == env["HOME"] and not {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CLAUDECODE", "STRATA_CLAUDE_BIN"} & set(child)


def test_turn_streams_text_and_runs_in_cwd_with_auto_permissions_by_default(tmp_path, env):
    with session(tmp_path, env, model="sonnet") as s:
        assert s.start() is None and s.events() == []  # nothing is launched before the first turn
        s.turn("hello")
        ev = collect(s, "turn_completed")
        assert [e["type"] for e in ev] == ["turn_started", "text_delta", "text_delta", "turn_completed"]
        assert "".join(e["data"]["text"] for e in ev[1:3]) == "Hello" and ev[-1]["data"]["turn"] == {"status": "completed", "duration_ms": 12, "cost_usd": 0.01, "steps": 1}
        assert s.thread_id == "sess-1" and s.inference_status["inference_verified"]
        s.turn("again"); collect(s, "turn_completed", after=ev[-1]["seq"])  # same child serves the next turn
    log = [json.loads(l) for l in (tmp_path / "log").read_text().splitlines()]
    assert len(log) == 1 and log[0]["cwd"] == str(tmp_path) and "ANTHROPIC_API_KEY" not in log[0]["env"]
    a = log[0]["argv"]
    assert a[a.index("--permission-mode") + 1] == "auto" and a[a.index("--permission-prompt-tool") + 1] == "stdio" and a[a.index("--model") + 1] == "sonnet"
    assert "--effort" not in a and "--resume" not in a


def test_settings_change_between_turns_relaunches_and_resumes(tmp_path, env):
    with session(tmp_path, env, model="opus", effort="high", permission="manual") as s:
        s.turn("hello"); ev = collect(s, "turn_completed")
        assert s.configure("claude-sonnet-5-5", "low", "plan") == {"model": "claude-sonnet-5-5", "effort": "low", "permission": "plan"}
        changed = collect(s, "settings_changed", after=ev[-1]["seq"])
        s.turn("again"); collect(s, "turn_completed", after=changed[-1]["seq"])
    first, second = [json.loads(l)["argv"] for l in (tmp_path / "log").read_text().splitlines()]
    opt = lambda a, k: a[a.index(k) + 1] if k in a else None
    assert (opt(first, "--model"), opt(first, "--effort"), opt(first, "--permission-mode"), opt(first, "--resume")) == ("opus", "high", "manual", None)
    assert (opt(second, "--model"), opt(second, "--effort"), opt(second, "--permission-mode"), opt(second, "--resume")) == ("claude-sonnet-5-5", "low", "plan", "sess-1")


def test_settings_are_checked_and_refused_mid_turn(tmp_path, env):
    for bad in ({"effort": "huge"}, {"permission": "bypassPermissions"}, {"permission": "dontAsk"}):
        with pytest.raises(ValueError): ClaudeSession(tmp_path, environ=env, **bad)
    with session(tmp_path, env) as s:
        with pytest.raises(ValueError): s.configure(None, None, "bypassPermissions")
        s.turn("wait"); collect(s, "turn_started")
        with pytest.raises(ClaudeError): s.configure("opus", "", "auto")


@pytest.mark.parametrize("allow", [True, False])
def test_tool_use_waits_for_the_decision(tmp_path, env, allow):
    with session(tmp_path, env) as s:
        s.turn("write")
        ev = collect(s, "approval_required")
        assert ev[1]["type"] == "item_started" and ev[1]["data"]["item"]["name"] == "Write"
        req = ev[-1]["data"]
        assert req["method"] == "claude/can_use_tool" and req["request"] == {"tool": "Write", "what": "x.txt", "input": {"file_path": "x.txt", "content": "hi"}}
        assert s.decide("nope", True) is False and s.decide(req["approval_id"], allow) is True and s.decide(req["approval_id"], allow) is False
        ev = collect(s, "turn_completed")
        done = next(e for e in ev if e["type"] == "tool_completed")["data"]["item"]
        assert done["error"] is (not allow) and ("wrote x.txt" in done["output"]) is allow


def test_approval_times_out_as_a_denial(tmp_path, env):
    with session(tmp_path, env, approval_timeout=0.2) as s:
        s.turn("write")
        ev = collect(s, "turn_completed")
        assert "approval_expired" in [e["type"] for e in ev] and next(e for e in ev if e["type"] == "tool_completed")["data"]["item"]["error"]


def test_cancel_reports_once_and_the_session_continues(tmp_path, env):
    with session(tmp_path, env) as s:
        assert s.cancel() is False
        s.turn("wait"); collect(s, "turn_started")
        with pytest.raises(ClaudeError): s.turn("second while running")
        assert s.cancel() is True
        s.turn("hello")
        types = [e["type"] for e in collect(s, "turn_completed")]
        assert types.count("turn_cancelled") == 1 and types.count("turn_completed") == 1 and "error" not in types


def test_child_death_ends_the_turn_and_next_turn_relaunches(tmp_path, env):
    with session(tmp_path, env) as s:
        s.turn("die")
        ev = collect(s, "turn_completed")
        assert ev[-1]["data"]["turn"]["status"] == "failed" and ev[-2]["type"] == "error"
        s.turn("hello"); assert collect(s, "turn_completed", after=ev[-1]["seq"])[-1]["data"]["turn"]["status"] == "completed"
    s.close()
    with pytest.raises(ClaudeError): s.turn("after close")


def test_bad_inputs(tmp_path, env):
    with pytest.raises(ValueError): ClaudeSession(tmp_path, provider="codex", environ=env)
    with pytest.raises(ValueError): ClaudeSession(tmp_path, model="--dangerously-skip-permissions", environ=env)
    with pytest.raises(ClaudeError): ClaudeSession(tmp_path, environ=env).turn("  ")
    missing = ClaudeSession(tmp_path, environ={**env, "STRATA_CLAUDE_BIN": "/nope/claude"})
    with pytest.raises(ClaudeError): missing.turn("x")


def test_auth_status(env):
    assert ClaudeSession.auth_status(environ=env) == {"provider": "claude", "account_present": True, "inference_verified": False, "configured": True,
                                                      "status": "account_present", "auth_method": "claude.ai", "subscription": "max"}  # no e-mail leaves the server
    assert ClaudeSession.auth_status(environ={**env, "STRATA_CLAUDE_BIN": "/nope"})["status"] == "unavailable"
    assert ClaudeSession.auth_status(environ=env, run=lambda *a, **k: type("R", (), {"stdout": '{"loggedIn": false}'})())["status"] == "login_required"


def test_login_link_then_code(env, monkeypatch):
    monkeypatch.setenv("PATH", env["PATH"])
    lg = ClaudeLogin(environ=env)
    assert lg.url() == "https://claude.com/cai/oauth/authorize?code=true&state=s" and lg.submit("good-code") is True
    lg = ClaudeLogin(environ=env); lg.url(); assert lg.submit("bad-code") is False
    with pytest.raises(ClaudeError): ClaudeLogin(environ=env).submit("has space")
    assert safe_login_url("https://claude.ai/oauth?x=1") and not any(safe_login_url(u) for u in (
        "http://claude.ai/x", "https://claude.ai.evil.example/x", "https://user@claude.ai/x", "https://claude.ai:8443/x", "https://claude.ai/a b", None))


def test_supervisor_claude_sign_in(tmp_path):
    class Login:
        made = []
        def __init__(self): Login.made.append(self); self.closed = False
        def url(self): return "https://claude.com/cai/oauth/authorize?state=1"
        def submit(self, code): return code == "good"
        def close(self): self.closed = True
    sup = ChatSupervisor({})
    with pytest.raises(ChatError): sup.login_claude("good", login_factory=Login)  # nothing waiting
    assert sup.login_claude(login_factory=Login) == {"mode": "code", "url": "https://claude.com/cai/oauth/authorize?state=1"}
    assert sup.login_claude(login_factory=Login)["url"] and Login.made[0].closed  # a new link replaces the old attempt
    assert sup.login_claude("good", login_factory=Login) == {"mode": "code", "signed_in": True}
    with pytest.raises(ChatError): sup.login_claude("good", login_factory=Login)
    sup.login_claude(login_factory=Login); sup.shutdown(); assert Login.made[-1].closed


def test_turn_with_pasted_images_sends_image_blocks_then_text(tmp_path, env):
    with session(tmp_path, env) as s:
        s.turn("what is this?", [{"media_type": "image/png", "data": PNG}])
        ev = collect(s, "turn_completed")
        s.turn("", [{"media_type": "image/png", "data": PNG}]); collect(s, "turn_completed", after=ev[-1]["seq"])  # an image alone is a message
        with pytest.raises(ClaudeError): s.turn("", [])
    sent = [json.loads(l) for l in (tmp_path / "log.content").read_text().splitlines()]
    assert sent[0] == [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}, {"type": "text", "text": "what is this?"}]
    assert [b["type"] for b in sent[1]] == ["image"]


@pytest.mark.parametrize("images", [
    "x", [PNG], [{"media_type": "image/svg+xml", "data": PNG}], [{"media_type": "image/jpeg", "data": PNG}],
    [{"media_type": "image/png", "data": "not base64!"}], [{"media_type": "image/png", "data": PNG, "extra": 1}],
    [{"media_type": "image/png", "data": PNG}] * 5, [{"media_type": "image/png", "data": "A" * (5 * 1024 * 1024 + 4)}],
])
def test_check_images_rejects_anything_but_a_few_real_images(images):
    with pytest.raises(ValueError):
        check_images(images)
    assert check_images(None) == [] and len(check_images([{"media_type": "image/png", "data": PNG}] * 4)) == 4
