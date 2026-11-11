"""Persistent Antigravity CLI chat through its documented stream-JSON protocol."""
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


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if k in {"HOME", "PATH", "USER", "LOGNAME", "LANG", "TERM", "TMPDIR",
                     "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"} or k.startswith("LC_")}


class AntigravitySession:
    def __init__(self, cwd: str | pathlib.Path, provider: str = "antigravity", model: str | None = None,
                 *, popen=subprocess.Popen):
        if provider != "antigravity":
            raise ValueError("invalid provider")
        self.cwd, self.provider, self.model = str(pathlib.Path(cwd).resolve()), provider, model
        self._popen = popen
        self._proc = None
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._events: collections.deque[dict[str, Any]] = collections.deque(maxlen=2000)
        self._seq = 0
        self._turn: str | None = None
        self._turn_has_text = False
        self._thread_id: str | None = None
        self._closed = False

    @classmethod
    def auth_status(cls, provider: str = "antigravity") -> dict[str, Any]:
        available = bool(shutil.which("agy"))
        return {"provider": provider, "status": "account_present" if available else "unavailable",
                "configured": available, "account_present": None,
                "inference_verified": False,
                **({"message": "Antigravity CLI (agy) is not installed"} if not available else {})}

    def start(self) -> str | None:
        # The CLI starts on the first turn; a new chat can be opened without a process.
        return self._thread_id

    @property
    def thread_id(self) -> str | None:
        return self._thread_id

    @property
    def process_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @property
    def turn_running(self) -> bool:
        with self._lock:
            return self._turn is not None

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        with self._changed:
            self._seq += 1
            self._events.append({"seq": self._seq, "type": kind, "data": data, "time": time.time()})
            self._changed.notify_all()

    def events(self, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [event for event in self._events if event["seq"] > after]

    def wait_events(self, after: int = 0, timeout: float | None = None) -> list[dict[str, Any]]:
        with self._changed:
            self._changed.wait_for(lambda: self._seq > after or self._closed, timeout)
            return self.events(after)

    def _launch(self) -> None:
        executable = shutil.which("agy")
        if not executable:
            raise RuntimeError("Antigravity CLI is not installed")
        args = [executable, "--input-format", "stream-json", "--output-format", "stream-json", "--mode", "auto", "--sandbox"]
        if self.model:
            args.extend(["--model", self.model])
        self._proc = self._popen(args, cwd=self.cwd, env=child_env(), stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read_loop, args=(self._proc,), daemon=True).start()

    def turn(self, message: str) -> str:
        if not isinstance(message, str) or not message.strip() or len(message) > 100000:
            raise ValueError("invalid message")
        with self._lock:
            if self._closed or self._turn:
                raise RuntimeError("Antigravity chat is closed or busy")
            if self._proc is None or self._proc.poll() is not None:
                self._launch()
            turn_id = secrets.token_urlsafe(12)
            self._turn = turn_id
            self._turn_has_text = False
            try:
                self._proc.stdin.write(json.dumps({"event": "user", "message": {"content": message}}) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError, AttributeError):
                self._turn = None
                raise RuntimeError("Antigravity CLI stopped") from None
            self._emit("turn_started", {"turn_id": turn_id})
            return turn_id

    def _read_loop(self, proc) -> None:
        try:
            for line in proc.stdout:
                if len(line) > 2_000_000:
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                kind = event.get("event")
                if kind == "init":
                    self._thread_id = event.get("conversation_id")
                elif kind == "step_update":
                    update = event.get("step_update") or {}
                    delta = update.get("text_delta")
                    if isinstance(delta, str) and delta:
                        self._turn_has_text = True
                        self._emit("text_delta", {"item_id": str(update.get("step_index", "response")), "text": delta[:100000]})
                elif kind == "result":
                    result = event.get("result") or {}
                    with self._lock:
                        if not self._turn:
                            continue
                        self._turn = None
                    if result.get("status") == "SUCCESS":
                        if not self._turn_has_text and isinstance(result.get("response"), str):
                            self._emit("text_delta", {"item_id": "response", "text": result["response"][:100000]})
                        self._emit("turn_completed", {"turn": {"status": "completed",
                                   "duration_ms": int(result.get("duration_seconds", 0) * 1000)}})
                    else:
                        self._emit("error", {"message": str(result.get("error") or "Antigravity turn failed")[:500]})
                        self._emit("turn_completed", {"turn": {"status": "failed"}})
        finally:
            with self._lock:
                was_active = self._proc is proc and bool(self._turn)
                if self._proc is proc:
                    self._turn = None
            if was_active and not self._closed:
                self._emit("error", {"message": "Antigravity CLI stopped unexpectedly"})
                self._emit("turn_completed", {"turn": {"status": "failed"}})

    def decide(self, approval_id: str, allow: bool) -> bool:
        return False  # Headless CLI permission requests are handled by its own policy.

    def cancel(self) -> bool:
        with self._lock:
            if not self._turn:
                return False
            self._turn = None
            proc, self._proc = self._proc, None
            self._emit("turn_cancelled", {})
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        return True

    def close(self) -> None:
        with self._changed:
            if self._closed:
                return
            self._closed = True
            proc, self._proc = self._proc, None
            self._changed.notify_all()
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
