"""Claude Code as a chat provider: one supervised `claude -p` child per session, spoken to in stream-json.

The child uses the Claude login already stored on this machine (the same one the
Claude Code CLI and editor extensions use), so no API key passes through Strata:
API-key variables are not forwarded, which also keeps usage on the subscription.
Every action Claude Code would ask about (file writes, shell commands, ...)
arrives as a `can_use_tool` control request and becomes an `approval_required`
event; nothing runs until the viewer answers through `decide`.
The public surface mirrors `CodexSession`, so `ChatSupervisor` drives either.
"""
from __future__ import annotations

import collections
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from strata.chat_codex import _terminate_and_reap
from strata.claude_models import DEFAULT_PERMISSION, EFFORT_IDS, PERMISSION_IDS

MAX_MESSAGE = 1_000_000
MAX_REPLAY = 2000
MAX_REPLAY_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_PENDING_APPROVALS = 64
MAX_FIELD = 6000
APPROVAL_TIMEOUT = 300
STATUS_TIMEOUT = 15
LOGIN_URL_TIMEOUT = 20
LOGIN_HOSTS = {"claude.ai", "claude.com", "platform.claude.com", "console.anthropic.com"}
_ENV = {"PATH", "HOME", "CLAUDE_CONFIG_DIR", "TMPDIR", "TMP", "TEMP", "USER", "LOGNAME", "LANG", "SHELL", "TERM",
        "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy"}
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/\[\]-]{0,127}")


class ClaudeError(RuntimeError):
    pass


def _child_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Allowlisted environment: no API keys (subscription login only) and no trace of a parent Claude Code session."""
    source = os.environ if environ is None else environ
    env = {k: v for k, v in source.items() if k in _ENV or k.startswith("LC_")}
    env["BROWSER"] = "true"  # the server never opens a browser; the viewer shows the sign-in link instead
    return env


def _claude_executable(environ: dict[str, str]) -> str:
    configured = environ.get("STRATA_CLAUDE_BIN")
    if configured is not None:
        if not os.path.isabs(configured) or not os.path.isfile(configured) or not os.access(configured, os.X_OK):
            raise ClaudeError("STRATA_CLAUDE_BIN must name an absolute executable")
        return configured
    home = environ.get("HOME") or os.path.expanduser("~")
    for found in (shutil.which("claude", path=environ.get("PATH")), os.path.join(home, ".local/bin/claude"), os.path.join(home, ".claude/local/claude")):
        if found and os.path.isfile(found) and os.access(found, os.X_OK):
            return found
    raise ClaudeError("Claude Code CLI is not installed or not on the server PATH")


def safe_login_url(value: Any) -> bool:
    if not isinstance(value, str) or len(value) > 4096 or re.search(r"[\s\x00-\x1f\x7f]", value):
        return False
    try:
        u = urlsplit(value)
        return u.scheme == "https" and u.hostname in LOGIN_HOSTS and u.port in (None, 443) and not u.username and not u.password
    except ValueError:
        return False


def _clip(value: Any, limit: int = MAX_FIELD) -> Any:
    """Bound what one event carries: long strings are cut, containers are walked."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"\n[{len(value) - limit} more characters not shown]"
    if isinstance(value, dict):
        return {str(k)[:200]: _clip(v, limit) for k, v in list(value.items())[:64]}
    if isinstance(value, list):
        return [_clip(v, limit) for v in value[:64]]
    return value


def _check_settings(model, effort, permission) -> None:
    if model is not None and not (isinstance(model, str) and (model == "" or _MODEL.fullmatch(model))):
        raise ValueError("invalid model")
    if effort is not None and effort not in EFFORT_IDS:
        raise ValueError("invalid effort")
    if permission not in PERMISSION_IDS:
        raise ValueError("invalid permission mode")


class ClaudeSession:
    """One Claude Code conversation in `cwd`. The child starts on the first turn and stays for the following ones."""

    def __init__(self, cwd, provider: str = "claude", model: str | None = None, *, effort: str | None = None,
                 permission: str = DEFAULT_PERMISSION, popen=subprocess.Popen,
                 environ: dict[str, str] | None = None, approval_timeout: int = APPROVAL_TIMEOUT, replay_limit: int = MAX_REPLAY,
                 resume: str | None = None, listener=None):
        """resume: a Claude Code session id to carry on (from saved chat history). listener: called with every
        event, plus a `user_message` event per turn, so the chat can be saved (strata/chat_history.py)."""
        if provider != "claude":
            raise ValueError("provider must be claude")
        _check_settings(model, effort, permission)
        self.cwd, self.provider = os.fspath(cwd), provider
        self.model, self.effort, self.permission = model or None, effort or None, permission
        self._popen, self._source_env = popen, dict(os.environ if environ is None else environ)
        self._env = _child_env(self._source_env)
        self._approval_timeout, self._replay_limit = approval_timeout, max(1, min(int(replay_limit), MAX_REPLAY))
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._events: collections.deque = collections.deque()
        self._event_bytes = self._seq = 0
        self._proc = None
        self._pending: dict[str, dict[str, Any]] = {}
        self._active_turn: str | None = None
        self._closed = self._verified = False
        self._skip_results = 0  # an interrupted turn still ends with one result message; it was already reported as cancelled
        if resume is not None and not (isinstance(resume, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", resume)):
            raise ValueError("invalid resume id")
        self._thread_id: str | None = resume
        self._listener = listener

    # ---- status and sign-in (no session needed) ----
    @classmethod
    def auth_status(cls, provider: str = "claude", *, run=subprocess.run, environ: dict[str, str] | None = None) -> dict[str, Any]:
        """What `claude auth status` reports. Being signed in is not proof that a turn will succeed."""
        base = {"provider": "claude", "account_present": False, "inference_verified": False}
        try:
            source = dict(os.environ if environ is None else environ)
            done = run([_claude_executable(source), "auth", "status"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       timeout=STATUS_TIMEOUT, env=_child_env(source))
            info = json.loads(done.stdout)
            if not isinstance(info, dict):
                raise ValueError
        except ClaudeError as exc:
            return {**base, "status": "unavailable", "message": str(exc)}
        except Exception:
            return {**base, "status": "unavailable"}
        if info.get("loggedIn") is not True:
            return {**base, "status": "login_required"}
        plan = info.get("subscriptionType")
        return {**base, "account_present": True, "configured": True, "status": "account_present",
                "auth_method": str(info.get("authMethod") or "")[:40],
                **({"subscription": plan[:40]} if isinstance(plan, str) and plan else {})}

    # ---- conversation ----
    def start(self) -> str | None:
        """Nothing to launch yet: the child starts with the first turn, so a session can exist before sign-in."""
        return self._thread_id

    def _launch_locked(self) -> None:
        if self._closed:
            raise ClaudeError("session is closed")
        args = [_claude_executable(self._source_env), "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--permission-prompt-tool", "stdio", "--permission-mode", self.permission]
        if self.model:
            args += ["--model", self.model]
        if self.effort:
            args += ["--effort", self.effort]
        if self._thread_id:  # relaunched after a settings change: carry on the same conversation
            args += ["--resume", self._thread_id]
        try:
            self._proc = self._popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1, cwd=self.cwd, env=self._env)
        except OSError as exc:
            raise ClaudeError("could not start Claude Code") from exc
        threading.Thread(target=self._read_loop, args=(self._proc,), daemon=True).start()

    def turn(self, message: str) -> str:
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE:
            raise ClaudeError("invalid message")
        with self._lock:
            if self._closed:
                raise ClaudeError("session is closed")
            if self._active_turn:
                raise ClaudeError("a turn is already running")
            if self._proc is None or self._proc.poll() is not None:
                self._launch_locked()
            turn_id = secrets.token_urlsafe(12)
            self._active_turn = turn_id
            try:
                self._send({"type": "user", "message": {"role": "user", "content": message}})
            except ClaudeError:
                self._active_turn = None
                raise
            self._tell({"type": "user_message", "data": {"text": message, "turn_id": turn_id}, "time": time.time()})
            self._emit("turn_started", {"turn_id": turn_id})
            return turn_id

    def configure(self, model: str | None, effort: str | None, permission: str) -> dict[str, Any]:
        """Change model, effort and permission mode between turns. The idle child stops; the next turn
        starts a new one with the new settings that resumes this conversation."""
        _check_settings(model, effort, permission)
        with self._lock:
            if self._closed:
                raise ClaudeError("session is closed")
            if self._active_turn:
                raise ClaudeError("wait for the current turn to finish")
            self.model, self.effort, self.permission = model or None, effort or None, permission
            proc, self._proc = self._proc, None
            settings = self.settings
            self._emit("settings_changed", settings)
        _terminate_and_reap(proc)
        return settings

    @property
    def settings(self) -> dict[str, Any]:
        return {"model": self.model or "", "effort": self.effort or "", "permission": self.permission}

    def events(self, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [event for event, _ in self._events if event["seq"] > after]

    def wait_events(self, after: int = 0, timeout: float | None = None) -> list[dict[str, Any]]:
        with self._changed:
            self._changed.wait_for(lambda: self._seq > after or self._closed, timeout)
            return [event for event, _ in self._events if event["seq"] > after]

    def decide(self, approval_id: str, allow: bool) -> bool:
        with self._lock:
            pending = self._pending.pop(approval_id, None)
            if pending is None:
                return False
            pending["timer"].cancel()
            self._answer(pending, bool(allow))
            self._emit("approval_decided", {"approval_id": approval_id, "allow": bool(allow)})
            return True

    def cancel(self) -> bool:
        with self._lock:
            if not self._active_turn:
                return False
            for approval_id in list(self._pending):
                self.decide(approval_id, False)
            try:
                self._send({"type": "control_request", "request_id": secrets.token_hex(8), "request": {"subtype": "interrupt"}})
                self._skip_results += 1
            except ClaudeError:
                pass
            self._active_turn = None
            self._emit("turn_cancelled", {})
            return True

    def close(self) -> None:
        with self._changed:
            if self._closed:
                return
            self._closed = True
            for pending in self._pending.values():
                pending["timer"].cancel()
            self._pending.clear()
            proc, self._proc = self._proc, None
            self._changed.notify_all()
        _terminate_and_reap(proc)

    # The supervisor's Codex-shaped sign-in calls do not apply to a session: Claude sign-in is machine-wide (see ClaudeLogin).
    def login(self):
        raise ClaudeError("Claude sign-in is not tied to a session")

    login_device = login

    def cancel_login(self, login_id: str) -> bool:
        return False

    # ---- child I/O ----
    def _send(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (AttributeError, OSError, ValueError) as exc:
            raise ClaudeError("Claude Code is not running") from exc

    def _answer(self, pending: dict[str, Any], allow: bool) -> None:
        reply = ({"behavior": "allow", "updatedInput": pending["input"]} if allow
                 else {"behavior": "deny", "message": "The user did not allow this action in Strata."})
        try:
            self._send({"type": "control_response", "response": {"subtype": "success", "request_id": pending["request_id"], "response": reply}})
        except ClaudeError:
            pass

    def _read_loop(self, proc) -> None:
        try:
            for line in proc.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    try:
                        self._handle(message)
                    except Exception:
                        self._emit("protocol_error", {"message": "unreadable message from Claude Code"})
        except (OSError, ValueError):
            pass
        with self._lock:
            if self._proc is proc:
                self._proc = None
            if self._active_turn and not self._closed:  # the child died mid-turn
                self._active_turn = None
                self._emit("error", {"message": "Claude Code stopped unexpectedly. Check that you are signed in, then send the message again."})
                self._emit("turn_completed", {"turn": {"status": "failed"}})

    def _handle(self, m: dict[str, Any]) -> None:
        kind = m.get("type")
        if kind == "system" and m.get("subtype") == "init":
            if isinstance(m.get("session_id"), str):
                self._thread_id = m["session_id"][:128]
        elif kind == "stream_event":
            event = m.get("event") if isinstance(m.get("event"), dict) else {}
            delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta" and isinstance(delta.get("text"), str) and not m.get("parent_tool_use_id"):
                self._emit("text_delta", {"text": delta["text"], "item_id": m.get("api_message_id")})
        elif kind == "assistant":
            content = (m.get("message") or {}).get("content") if isinstance(m.get("message"), dict) else None
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self._emit("item_started", {"item": {"type": "tool", "id": block.get("id"), "name": block.get("name"), "input": _clip(block.get("input"))}})
        elif kind == "user":
            content = (m.get("message") or {}).get("content") if isinstance(m.get("message"), dict) else None
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out = block.get("content")
                    if isinstance(out, list):
                        out = "\n".join(str(x.get("text", "")) for x in out if isinstance(x, dict))
                    self._emit("tool_completed", {"item": {"type": "tool_result", "id": block.get("tool_use_id"), "error": bool(block.get("is_error")), "output": _clip(str(out or ""))}})
        elif kind == "control_request":
            self._handle_control(m)
        elif kind == "result":
            with self._lock:
                if self._skip_results:
                    self._skip_results -= 1
                    return
                self._active_turn = None
                failed = bool(m.get("is_error")) or m.get("subtype") != "success"
                if not failed:
                    self._verified = True
                if failed:
                    self._emit("error", {"message": _clip(str(m.get("result") or m.get("subtype") or "The turn failed"), 2000)})
                turn = {"status": "failed" if failed else "completed"}
                for src, dst in (("duration_ms", "duration_ms"), ("total_cost_usd", "cost_usd"), ("num_turns", "steps")):
                    if isinstance(m.get(src), (int, float)):
                        turn[dst] = m[src]
                self._emit("turn_completed", {"turn": turn})

    def _handle_control(self, m: dict[str, Any]) -> None:
        request, request_id = m.get("request"), m.get("request_id")
        if not isinstance(request, dict) or not isinstance(request_id, str):
            return
        if request.get("subtype") != "can_use_tool" or not isinstance(request.get("input"), dict):
            self._send({"type": "control_response", "response": {"subtype": "error", "request_id": request_id, "error": "unsupported request"}})
            return
        pending = {"request_id": request_id, "input": request["input"]}
        with self._lock:
            if len(self._pending) >= MAX_PENDING_APPROVALS or len(json.dumps(request["input"], ensure_ascii=False)) > MAX_MESSAGE:
                self._answer(pending, False)
                self._emit("approval_overflow", {"method": "claude/can_use_tool"})
                return
            approval_id = secrets.token_urlsafe(24)
            pending["timer"] = threading.Timer(self._approval_timeout, self._expire, args=(approval_id,))
            pending["timer"].daemon = True
            self._pending[approval_id] = pending
            self._emit("approval_required", {"approval_id": approval_id, "method": "claude/can_use_tool", "expires_in": self._approval_timeout,
                                              "request": {"tool": str(request.get("tool_name"))[:200], "what": _clip(str(request.get("description") or ""), 500),
                                                          "input": _clip(request["input"])}})
            pending["timer"].start()

    def _expire(self, approval_id: str) -> None:
        with self._lock:
            pending = self._pending.pop(approval_id, None)
            if pending is not None:
                self._answer(pending, False)
                self._emit("approval_expired", {"approval_id": approval_id, "message": "Approval timed out; the action was not allowed."})

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        with self._changed:
            self._seq += 1
            event = {"seq": self._seq, "type": kind, "data": data, "time": time.time()}
            size = len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if size > MAX_EVENT_BYTES:
                event = {"seq": self._seq, "type": "event_truncated", "data": {"original_type": kind, "size_bytes": size}, "time": time.time()}
                size = len(json.dumps(event, separators=(",", ":")).encode("utf-8"))
            self._events.append((event, size))
            self._event_bytes += size
            while len(self._events) > self._replay_limit or self._event_bytes > MAX_REPLAY_BYTES:
                self._event_bytes -= self._events.popleft()[1]
            self._changed.notify_all()
            self._tell(event)

    def _tell(self, event: dict[str, Any]) -> None:
        if self._listener is not None:
            try:
                self._listener(event)
            except Exception:
                pass

    @property
    def inference_status(self) -> dict[str, Any]:
        return {"provider": "claude", "account_present": None, "inference_verified": self._verified,
                "status": "inference_verified" if self._verified else "not_verified"}

    @property
    def thread_id(self) -> str | None:
        return self._thread_id

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class ClaudeLogin:
    """Machine-wide sign-in through `claude auth login`: it prints a sign-in link, the user signs in in their own
    browser and pastes the code the page shows; the CLI stores the login where every Claude Code client reads it."""

    def __init__(self, *, popen=subprocess.Popen, environ: dict[str, str] | None = None):
        source = dict(os.environ if environ is None else environ)
        try:
            self._proc = popen([_claude_executable(source), "auth", "login", "--claudeai"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=0, env=_child_env(source))
        except OSError as exc:
            raise ClaudeError("could not start Claude sign-in") from exc
        self._text, self._ready = "", threading.Event()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        try:
            while len(self._text) < 16384:
                chunk = self._proc.stdout.read(1)
                if not chunk:
                    break
                self._text += chunk
                if chunk in "\n>" and re.search(r"https://\S+", self._text):
                    self._ready.set()
        except (OSError, ValueError):
            pass
        self._ready.set()

    def url(self, timeout: float = LOGIN_URL_TIMEOUT) -> str:
        self._ready.wait(timeout)
        found = re.search(r"https://\S+", self._text)
        if not found or not safe_login_url(found.group(0)):
            self.close()
            raise ClaudeError("Claude Code did not offer a sign-in link")
        return found.group(0)

    def submit(self, code: str, timeout: float = 30) -> bool:
        """Hand the pasted code to the CLI; True once it has stored the login."""
        if not isinstance(code, str) or not re.fullmatch(r"[\x21-\x7e]{4,1024}", code):
            raise ClaudeError("invalid sign-in code")
        try:
            self._proc.stdin.write(code + "\n")
            self._proc.stdin.flush()
            return self._proc.wait(timeout=timeout) == 0
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        finally:
            self.close()

    def close(self) -> None:
        _terminate_and_reap(self._proc)


__all__ = ["ClaudeError", "ClaudeLogin", "ClaudeSession", "safe_login_url"]
