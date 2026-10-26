"""Small server-side adapter for the local Codex app-server JSON-RPC protocol.

The browser must only talk to Strata. This module owns the child process, local
Codex credentials, session IDs, replay buffer, and approval decisions.
"""
from __future__ import annotations

import collections
import json
import os
import pathlib
import secrets
import shutil
import subprocess
import threading
import time
from typing import Any


MAX_MESSAGE = 1_000_000
MAX_REPLAY = 2000
MAX_REPLAY_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 64 * 1024
MAX_PENDING_APPROVALS = 64
MAX_PENDING_RPCS = 32
MAX_PENDING_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_APPROVAL_BYTES = 48 * 1024
RPC_TIMEOUT = 20
APPROVAL_TIMEOUT = 300
_APPROVAL_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
}
_PROVIDERS = {
    "openrouter": ("STRATA_OPENROUTER_API_KEY", "STRATA_OPENROUTER_BASE_URL", "openrouter", "https://openrouter.ai/api/v1"),
    "omniroute": ("STRATA_OMNIROUTE_API_KEY", "STRATA_OMNIROUTE_BASE_URL", "omniroute", "http://127.0.0.1:20128/v1"),
}


class CodexError(RuntimeError):
    """Safe, user-facing failure from the local Codex adapter."""


def _safe_url(value: str) -> bool:
    """Permit HTTPS endpoints and loopback HTTP only for server-configured gateways."""
    from urllib.parse import urlsplit

    try:
        if not isinstance(value, str) or value != value.strip() or any(ord(c) < 32 for c in value):
            return False
        u = urlsplit(value)
        return (bool(u.hostname and (u.scheme == "https" or u.scheme == "http" and u.hostname in {"localhost", "127.0.0.1", "::1"}))
                and not u.username and not u.password and not u.query and not u.fragment)
    except ValueError:
        return False


def _child_env(provider: str, environ: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    if provider != "codex" and provider not in _PROVIDERS:
        raise ValueError("provider must be codex, openrouter, or omniroute")
    allowed = {
    "PATH", "HOME", "CODEX_HOME", "TMPDIR", "TMP", "TEMP", "USER", "LOGNAME", "LANG",
        "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy", "SYSTEMROOT", "WINDIR",
        "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
    }
    env = {k: v for k, v in source.items() if k in allowed or k.startswith("LC_")}
    if provider != "codex":
        key_name, url_name, _, default_url = _PROVIDERS[provider]
        key, base_url = source.get(key_name, ""), source.get(url_name, default_url)
        if not key or not _safe_url(base_url):
            raise ValueError(f"{provider} requires a server-configured API key and HTTPS or loopback base URL")
        env[url_name] = base_url
        # Never place credentials in argv or events. Codex receives the key for
        # inference; shell_environment_policy filters it from tool subprocesses.
        env["OPENAI_API_KEY"] = key
    return env


def _provider_args(provider: str, environ: dict[str, str]) -> list[str]:
    # The app-server keeps its own inference environment, then applies this
    # policy to command/tool subprocesses. Use a small runtime allowlist and
    # explicitly remove credential-bearing names and proxy URLs.
    from json import dumps
    safe_names = [
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_*", "TMPDIR", "TMP", "TEMP",
        "XDG_RUNTIME_DIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "SYSTEMROOT", "WINDIR", "COMSPEC",
        "PATHEXT", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
    ]
    secret_patterns = ["OPENAI_API_KEY", "STRATA_*", "*PROXY*", "*KEY*", "*SECRET*",
                       "*TOKEN*", "*PASS*", "*CRED*", "*AUTH*", "*COOKIE*"]
    args = [
        "-c", 'shell_environment_policy.inherit="core"',
        "-c", "shell_environment_policy.ignore_default_excludes=false",
        "-c", f"shell_environment_policy.include_only={dumps(safe_names)}",
        "-c", f"shell_environment_policy.exclude={dumps(secret_patterns)}",
    ]
    if provider == "codex":
        return args
    _, url_name, provider_id, default_url = _PROVIDERS[provider]
    url = environ.get(url_name, default_url)
    # `-c` values are fixed from server environment and TOML-quoted. No browser
    # input is interpolated into the command line.
    args.extend([
        "-c", f'model_provider={dumps(provider_id)}',
        "-c", f'model_providers.{provider_id}.name={dumps(provider_id)}',
        "-c", f'model_providers.{provider_id}.base_url={dumps(url)}',
        "-c", f'model_providers.{provider_id}.env_key="OPENAI_API_KEY"',
        "-c", f'model_providers.{provider_id}.wire_api="responses"',
        "-c", f'model_providers.{provider_id}.requires_openai_auth=false',
    ])
    return args


def _redact_error(value: Any, secrets_to_hide=()) -> str:
    """Keep protocol error messages useful while stripping common secret forms."""
    s = str(value)[:1000]
    for secret in secrets_to_hide:
        if secret:
            s = s.replace(secret, "[redacted]")
    return s


def _terminate_and_reap(proc) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


class CodexSession:
    """One Codex app-server child and one durable conversation thread.

    ``cwd`` must already be validated by the caller (normally an isolated
    worktree). API: start() -> thread ID; turn(message) -> turn ID; events(after)
    -> ordered replay list; decide(approval_id, allow); cancel(); close().
    """

    def __init__(self, cwd: str | pathlib.Path, provider: str = "codex", model: str | None = None,
                 *, popen=subprocess.Popen, environ: dict[str, str] | None = None,
                 replay_limit: int = MAX_REPLAY, approval_timeout: int = APPROVAL_TIMEOUT,
                 rpc_timeout: int = RPC_TIMEOUT):
        self.cwd = str(pathlib.Path(cwd).resolve())
        if not pathlib.Path(self.cwd).is_dir():
            raise ValueError("cwd must be an existing directory")
        self.provider, self.model = provider, model
        self._env_source = dict(os.environ if environ is None else environ)
        self._env = _child_env(provider, self._env_source)
        self._popen = popen
        self._replay_limit = max(10, min(int(replay_limit), MAX_REPLAY))
        self._approval_timeout = max(1, int(approval_timeout))
        self._rpc_timeout = max(1, int(rpc_timeout))
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._lifecycle = threading.RLock()
        self._events: collections.deque[tuple[dict[str, Any], int]] = collections.deque()
        self._event_bytes = 0
        self._pending: dict[str, dict[str, Any]] = {}
        self._responses: dict[int, dict[str, Any]] = {}
        self._response_bytes = 0
        self._waiters: set[int] = set()
        self._next_id = 1
        self._seq = 0
        self._thread_id: str | None = None
        self._active_turn: str | None = None
        self._reader: threading.Thread | None = None
        self._proc = None
        self._closed = False
        self._started = False
        self._initialized = False
        self._verified = False

    @classmethod
    def auth_status(cls, provider: str = "codex", *, popen=subprocess.Popen,
                    environ: dict[str, str] | None = None, rpc_timeout: int = RPC_TIMEOUT) -> dict[str, Any]:
        """Read local auth readiness. This is not proof that inference works."""
        proc = None
        temp = None
        try:
            env_source = dict(os.environ if environ is None else environ)
            env = _child_env(provider, env_source)
            args = ["codex", "app-server", "--listen", "stdio://", *_provider_args(provider, env_source)]
            proc = popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, bufsize=1, env=env)
            temp = cls.__new__(cls)
            temp._init_rpc_only(proc, rpc_timeout, env)
            temp._rpc("initialize", {"clientInfo": {"name": "strata", "version": "0.1.0"}, "capabilities": {"experimentalApi": False}})
            temp._notify("initialized", {})
            result = temp._rpc("account/read", {})
            account = result.get("account") if isinstance(result, dict) else None
            requires_auth = bool(result.get("requiresOpenaiAuth", False)) if isinstance(result, dict) else None
            status = "account_present" if account else (
                "provider_configured" if provider != "codex" or requires_auth is False else "login_required")
            return {"provider": provider, "account_present": bool(account),
                    "requires_openai_auth": requires_auth,
                    "configured": bool(account) or provider != "codex" or requires_auth is False,
                    "inference_verified": False, "status": status}
        except ValueError as exc:
            return {"provider": provider, "account_present": False, "inference_verified": False,
                    "status": "configuration_required", "message": str(exc)}
        except Exception:
            return {"provider": provider, "account_present": False, "inference_verified": False,
                    "status": "unavailable"}
        finally:
            try:
                if temp is not None:
                    temp._stop_rpc_only()
                else:
                    _terminate_and_reap(proc)
            except Exception:
                _terminate_and_reap(proc)

    def _init_rpc_only(self, proc, timeout, env):
        self._proc, self._rpc_timeout = proc, max(1, int(timeout))
        self._env = env
        self._lock = threading.RLock(); self._changed = threading.Condition(self._lock)
        self._lifecycle = threading.RLock()
        self._responses = {}; self._response_bytes = 0; self._waiters = set(); self._next_id = 1; self._closed = False
        self._events = collections.deque(); self._event_bytes = 0; self._seq = 0; self._replay_limit = 32
        self._pending = {}; self._approval_timeout = APPROVAL_TIMEOUT
        self._reader = threading.Thread(target=self._read_loop, daemon=True); self._reader.start()

    def _stop_rpc_only(self):
        self._closed = True
        _terminate_and_reap(self._proc)

    def start(self) -> str:
        with self._lifecycle:
            return self._start_locked()

    def _start_locked(self) -> str:
        with self._lock:
            if self._started:
                return self._thread_id  # type: ignore[return-value]
            if self._closed:
                raise CodexError("session is closed")
        self._launch()
        # Read-only is required for write attempts to surface as server approval
        # requests. workspace-write could let in-worktree writes bypass the UI.
        params: dict[str, Any] = {"cwd": self.cwd, "approvalPolicy": "on-request", "sandbox": "read-only"}
        if self.model:
            params["model"] = self.model
        try:
            result = self._rpc("thread/start", params)
            thread = result.get("thread") if isinstance(result, dict) else None
            thread_id = thread.get("id") if isinstance(thread, dict) else None
            if not isinstance(thread_id, str):
                raise CodexError("Codex did not return a thread ID")
            with self._lock:
                self._thread_id, self._started = thread_id, True
            self._emit("session_started", {"thread_id": thread_id, "provider": self.provider})
            return thread_id
        except Exception:
            self.close()
            raise

    def _launch(self) -> None:
        with self._lifecycle:
            self._launch_locked()

    def _launch_locked(self) -> None:
        with self._lock:
            if self._initialized:
                return
            if self._closed:
                raise CodexError("session is closed")
        codex = shutil.which("codex")
        if not codex:
            raise CodexError("Codex CLI is not installed or not on the server PATH")
        args = [codex, "app-server", "--listen", "stdio://", *_provider_args(self.provider, self._env_source)]
        try:
            self._proc = self._popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1, env=self._env)
        except OSError as exc:
            with self._lock: self._closed = True
            raise CodexError("could not start Codex app-server") from exc
        try:
            self._reader = threading.Thread(target=self._read_loop, name="strata-codex-events", daemon=True)
            self._reader.start()
            self._rpc("initialize", {"clientInfo": {"name": "strata", "version": "0.1.0"},
                                      "capabilities": {"experimentalApi": False}})
            # Newer app-server versions use this handshake notification. Codex
            # 0.114.0 ignores this proper no-ID notification.
            self._notify("initialized", {})
            with self._lock:
                self._initialized = True
        except Exception:
            with self._lock: self._closed = True
            _terminate_and_reap(self._proc)
            raise

    def login(self) -> dict[str, Any]:
        with self._lifecycle:
            return self._login_locked()

    def _login_locked(self) -> dict[str, Any]:
        """Start Codex's native browser sign-in flow when supported by the CLI."""
        if self.provider != "codex":
            raise CodexError("login is available through the local Codex account only")
        self._launch()
        try:
            result = self._rpc("account/login/start", {"type": "chatgpt"})
            # Login URLs are intended for the local UI; tokens and callback data
            # are never included. Do not mark auth verified until a turn works.
            fields = ("type", "authUrl", "url", "loginId")
            self._emit("login_started", {k: result[k] for k in fields if isinstance(result, dict) and k in result})
            return {k: result[k] for k in fields if isinstance(result, dict) and k in result}
        except CodexError as exc:
            raise CodexError("Codex login flow is unavailable in this CLI version") from exc

    def cancel_login(self, login_id: str) -> bool:
        with self._lifecycle:
            return self._cancel_login_locked(login_id)

    def _cancel_login_locked(self, login_id: str) -> bool:
        if not isinstance(login_id, str) or not login_id:
            raise ValueError("login ID required")
        if self.provider != "codex":
            return False
        self._launch()
        return self._rpc("account/login/cancel", {"loginId": login_id}).get("status") == "canceled"

    def turn(self, message: str) -> str:
        with self._lifecycle:
            return self._turn_locked(message)

    def _turn_locked(self, message: str) -> str:
        if not isinstance(message, str) or not message.strip() or len(message) > 100_000:
            raise ValueError("message must be non-empty text up to 100000 characters")
        if not self._started:
            self.start()
        with self._lock:
            if self._active_turn:
                raise CodexError("a turn is already running")
            thread_id = self._thread_id
        result = self._rpc("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": message}]})
        turn = result.get("turn") if isinstance(result, dict) else None
        turn_id = turn.get("id") if isinstance(turn, dict) else None
        if not isinstance(turn_id, str):
            raise CodexError("Codex did not return a turn ID")
        with self._lock:
            self._active_turn = turn_id
        self._emit("turn_started", {"turn_id": turn_id})
        return turn_id

    def resume(self, thread_id: str) -> str:
        with self._lifecycle:
            return self._resume_locked(thread_id)

    def _resume_locked(self, thread_id: str) -> str:
        """Attach to a durable local Codex thread whose ID the caller retained."""
        if not isinstance(thread_id, str) or not thread_id.strip() or len(thread_id) > 128:
            raise ValueError("valid Codex thread ID required")
        self._launch()
        result = self._rpc("thread/resume", {"threadId": thread_id, "cwd": self.cwd})
        thread = result.get("thread") if isinstance(result, dict) else None
        if not isinstance(thread, dict) or thread.get("id") != thread_id:
            raise CodexError("Codex did not resume the requested thread")
        with self._lock:
            self._thread_id, self._started = thread_id, True
        self._emit("session_resumed", {"thread_id": thread_id, "provider": self.provider})
        return thread_id

    def events(self, after: int = 0) -> list[dict[str, Any]]:
        """Return retained events with sequence greater than ``after``."""
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise ValueError("after must be a non-negative event sequence")
        with self._lock:
            return [dict(event) for event, _ in self._events if event["seq"] > after]

    def wait_events(self, after: int = 0, timeout: float | None = None) -> list[dict[str, Any]]:
        with self._changed:
            if not any(e["seq"] > after for e, _ in self._events):
                self._changed.wait(timeout)
            return self.events(after)

    def decide(self, approval_id: str, allow: bool) -> bool:
        if not isinstance(approval_id, str) or not isinstance(allow, bool):
            raise ValueError("approval ID and boolean decision required")
        with self._lock:
            pending = self._pending.pop(approval_id, None)
        if pending is None or pending["expires"] <= time.monotonic():
            if pending is not None:
                self._answer_approval(pending, False)
            return False
        self._answer_approval(pending, allow)
        self._emit("approval_decided", {"approval_id": approval_id, "allow": allow})
        return True

    def cancel(self) -> bool:
        with self._lifecycle:
            return self._cancel_locked()

    def _cancel_locked(self) -> bool:
        with self._lock:
            turn_id, thread_id = self._active_turn, self._thread_id
            pending = list(self._pending.values())
            self._pending.clear()
        for approval in pending:
            self._answer_approval(approval, False)
        if not turn_id or not thread_id or self._closed:
            return False
        try:
            self._rpc("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        except CodexError:
            pass
        self._emit("turn_cancelled", {"turn_id": turn_id})
        return True

    def close(self) -> None:
        with self._lifecycle:
            self._close_locked()

    def _close_locked(self) -> None:
        with self._lock:
            if self._closed:
                return
            pending = list(self._pending.values()); self._pending.clear()
        for approval in pending:
            self._answer_approval(approval, False)
        with self._lock:
            self._closed = True
        _terminate_and_reap(self._proc)
        with self._changed:
            self._changed.notify_all()

    def _send(self, payload: dict[str, Any]) -> None:
        proc = self._proc
        if self._closed or proc is None or proc.stdin is None:
            raise CodexError("Codex app-server is not running")
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            try:
                proc.stdin.write(raw + "\n"); proc.stdin.flush()
            except (OSError, BrokenPipeError) as exc:
                raise CodexError("Codex app-server connection closed") from exc

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if len(self._waiters) >= MAX_PENDING_RPCS:
                raise CodexError("too many pending Codex requests")
            request_id = self._next_id; self._next_id += 1
            self._waiters.add(request_id)
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        except Exception:
            with self._lock: self._waiters.discard(request_id)
            raise
        deadline = time.monotonic() + self._rpc_timeout
        with self._changed:
            while request_id not in self._responses:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._waiters.discard(request_id)
                    raise CodexError(f"Codex request timed out: {method}")
                self._changed.wait(remaining)
            response = self._responses.pop(request_id)
            self._response_bytes -= len(json.dumps(response, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
            self._waiters.discard(request_id)
        if "error" in response:
            message = _redact_error(response["error"].get("message", "request failed"),
                                    [self._env.get("OPENAI_API_KEY", "")])
            raise CodexError(message)
        result = response.get("result", {})
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        try:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})
        except CodexError:
            pass

    def _read_loop(self) -> None:
        proc = self._proc
        try:
            while proc is not None and proc.stdout is not None:
                line = proc.stdout.readline(MAX_MESSAGE + 1)
                if not line:
                    break
                if len(line) > MAX_MESSAGE or not line.endswith("\n"):
                    self._emit("protocol_error", {"message": "oversized or incomplete app-server message"})
                    continue
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._emit("protocol_error", {"message": "malformed app-server JSON message"})
                    continue
                if not isinstance(message, dict):
                    self._emit("protocol_error", {"message": "app-server message must be an object"})
                    continue
                if "id" in message and ("result" in message or "error" in message):
                    with self._changed:
                        response_id = message.get("id")
                        if type(response_id) is not int or response_id not in self._waiters:
                            self._emit("protocol_error", {"message": "unknown app-server response ID"})
                            continue
                        if response_id in self._responses:
                            self._emit("protocol_error", {"message": "duplicate app-server response ID"})
                            continue
                        size = len(json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
                        if self._response_bytes + size > MAX_PENDING_RESPONSE_BYTES:
                            message = {"jsonrpc": "2.0", "id": response_id,
                                       "error": {"code": -32000, "message": "response buffer limit exceeded"}}
                            size = len(json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
                        self._responses[response_id] = message
                        self._response_bytes += size
                        self._changed.notify_all()
                    continue
                if "id" in message and isinstance(message.get("method"), str):
                    self._handle_server_request(message)
                    continue
                method, params = message.get("method"), message.get("params", {})
                if not isinstance(method, str) or not isinstance(params, dict):
                    self._emit("protocol_error", {"message": "malformed app-server event"})
                    continue
                self._handle_notification(method, params)
        except Exception:
            self._emit("protocol_error", {"message": "app-server event stream failed"})
        finally:
            with self._changed:
                self._changed.notify_all()

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        method, params = message.get("method"), message.get("params", {})
        if method not in _APPROVAL_METHODS or not isinstance(params, dict):
            self._send_error(message.get("id"), -32601, "unsupported app-server request")
            self._emit("approval_unsupported", {"method": str(method)[:100]})
            return
        dto = self._approval_dto(method, params)
        if dto is None:
            self._send_error(message.get("id"), -32600, "unsupported or oversized approval request")
            self._emit("approval_unsupported", {"method": method, "reason": "unknown shape or size limit"})
            return
        approval_id = secrets.token_urlsafe(24)
        with self._lock:
            if len(self._pending) >= MAX_PENDING_APPROVALS:
                self._send_error(message.get("id"), -32000, "too many pending approvals")
                self._emit("approval_overflow", {"method": method})
                return
        pending = {"rpc_id": message.get("id"), "method": method,
                   "expires": time.monotonic() + self._approval_timeout}
        with self._lock:
            self._pending[approval_id] = pending
        self._emit("approval_required", {"approval_id": approval_id, "method": method, "request": dto,
                                          "expires_in": self._approval_timeout})
        timer = threading.Timer(self._approval_timeout, self._expire_approval, args=(approval_id,))
        timer.daemon = True; timer.start()

    @staticmethod
    def _approval_dto(method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        common = {"itemId", "threadId", "turnId", "reason"}
        command_fields = {"command", "cwd", "commandActions", "networkApprovalContext",
                          "availableDecisions", "proposedExecpolicyAmendment",
                          "proposedNetworkPolicyAmendments", "additionalPermissions",
                          "environmentId", "approvalId"}
        file_fields = {"grantRoot", "changes"}
        allowed = common | (command_fields if method == "item/commandExecution/requestApproval" else file_fields)
        if set(params) - allowed:
            return None
        for key in ("itemId", "threadId", "turnId"):
            if not isinstance(params.get(key), str) or not params[key] or len(params[key]) > 128:
                return None
        if method == "item/commandExecution/requestApproval":
            command, actions = params.get("command"), params.get("commandActions")
            if command is not None and (not isinstance(command, str) or len(command) > 16_000):
                return None
            if actions is not None and not isinstance(actions, (list, dict)):
                return None
            if command is None and actions is None:
                return None
        for key in ("reason", "cwd", "grantRoot", "environmentId", "approvalId"):
            if key in params and (not isinstance(params[key], str) or len(params[key]) > 8192):
                return None
        if "availableDecisions" in params:
            decisions = params["availableDecisions"]
            if not isinstance(decisions, list) or len(decisions) > 16 or not all(isinstance(x, str) and len(x) <= 64 for x in decisions):
                return None
        if "changes" in params and not isinstance(params["changes"], (list, dict)):
            return None
        try:
            encoded = json.dumps(params, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            return None
        if len(encoded) > MAX_APPROVAL_BYTES:
            return None
        return {key: params[key] for key in allowed if key in params}

    def _answer_approval(self, pending: dict[str, Any], allow: bool) -> None:
        self._send_response(pending["rpc_id"], {"decision": "accept" if allow else "decline"})

    def _send_response(self, request_id: Any, result: dict[str, Any]) -> None:
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "result": result})
        except CodexError:
            pass

    def _send_error(self, request_id: Any, code: int, message: str) -> None:
        try:
            self._send({"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": code, "message": message}})
        except CodexError:
            pass

    def _expire_approval(self, approval_id: str) -> None:
        with self._lock:
            pending = self._pending.pop(approval_id, None)
        if pending:
            self._answer_approval(pending, False)
            self._emit("approval_expired", {"approval_id": approval_id})

    def _handle_notification(self, method: str, p: dict[str, Any]) -> None:
        if method == "item/agentMessage/delta":
            self._emit("text_delta", {"text": p.get("delta", ""), "item_id": p.get("itemId")})
        elif method == "item/started":
            self._emit("item_started", {"item": p.get("item")})
        elif method == "item/completed":
            item = p.get("item", {})
            if isinstance(item, dict) and item.get("type") in ("commandExecution", "fileChange", "mcpToolCall"):
                self._emit("tool_completed", {"item": item})
            else:
                self._emit("item_completed", {"item": item})
        elif method == "turn/completed":
            turn = p.get("turn", {})
            status = turn.get("status") if isinstance(turn, dict) else None
            self._emit("turn_completed", {"turn": turn})
            with self._lock:
                self._active_turn = None
                if status == "completed": self._verified = True
        elif method in ("account/login/changed", "account/login/completed"):
            # Never forward credentials or raw provider errors.
            status = p.get("loginStatus") or p.get("status")
            safe = {"status": status} if isinstance(status, str) else {}
            for key in ("authUrl", "url", "loginId"):
                if isinstance(p.get(key), str): safe[key] = p[key]
            self._emit("login_status", safe)
        else:
            # Preserve useful typed events without returning arbitrary raw
            # protocol payloads (which could include auth material).
            allow = {"turn/started": "turn_started", "error": "error", "item/commandExecution/outputDelta": "tool_output",
                     "item/reasoning/summaryTextDelta": "reasoning_delta", "item/fileChange/outputDelta": "tool_output"}
            kind = allow.get(method)
            if kind:
                body = {k: v for k, v in p.items() if k not in {"token", "apiKey", "authorization"}}
                self._emit(kind, body)

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        with self._changed:
            self._seq += 1
            data = self._scrub(data)
            event = {"seq": self._seq, "type": kind, "data": data, "time": time.time()}
            size = len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if size > MAX_EVENT_BYTES:
                event = {"seq": self._seq, "type": "event_truncated",
                         "data": {"original_type": kind, "size_bytes": size}, "time": time.time()}
                size = len(json.dumps(event, separators=(",", ":")).encode("utf-8"))
            self._events.append((event, size))
            self._event_bytes += size
            while len(self._events) > self._replay_limit or self._event_bytes > MAX_REPLAY_BYTES:
                _, removed_size = self._events.popleft()
                self._event_bytes -= removed_size
            self._changed.notify_all()

    def _scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            secret = self._env.get("OPENAI_API_KEY", "")
            return value.replace(secret, "[redacted]") if secret else value
        if isinstance(value, dict):
            return {k: self._scrub(v) for k, v in value.items()
                    if k.lower() not in {"token", "apikey", "authorization", "access_token", "refresh_token"}}
        if isinstance(value, list):
            return [self._scrub(v) for v in value]
        return value

    @property
    def inference_status(self) -> dict[str, Any]:
        return {"provider": self.provider, "account_present": None,
                "inference_verified": self._verified,
                "status": "inference_verified" if self._verified else "not_verified"}

    @property
    def thread_id(self) -> str | None:
        return self._thread_id

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

