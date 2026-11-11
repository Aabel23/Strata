"""Saved AI chat history: one transcript per chat, kept as files next to the Strata DB.

Layout: ``<db file>.chats/<project>/<chat id>.json`` (title, times, worktree,
Claude session id, settings) and ``<chat id>.jsonl`` (the chat's events, one per line).
The chat id is the Strata session id the chat started with; its worktree is
``.strata-worktrees/<project>/chat-<chat id>``, which is what lets a later chat
resume it (`claude --resume` only finds a conversation from the same directory).

Nothing here touches the DB or the audit log. Streamed text is stored as one
``text`` event per reply instead of one line per delta.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import threading
import time
from typing import Any

PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
CHAT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
MAX_FILE_BYTES = 32 * 1024 * 1024  # one chat's transcript; later events are dropped once a chat reaches it
MAX_TITLE = 120
MAX_LIST = 200
SKIP = {"turn_started", "text_delta", "approval_decided"}  # live-only, or rebuilt (text) from deltas


class ChatHistory:
    def __init__(self, base: str | os.PathLike[str]):
        self.base = pathlib.Path(base)
        self._lock = threading.Lock()
        self._text: dict[tuple[str, str], dict[str, Any]] = {}  # (project, chat) -> reply being streamed

    # ---- paths ----
    def _dir(self, project: str) -> pathlib.Path:
        if not isinstance(project, str) or not PROJECT_ID.fullmatch(project):
            raise ValueError("invalid project")
        return self.base / project

    def _paths(self, project: str, chat: str) -> tuple[pathlib.Path, pathlib.Path]:
        if not isinstance(chat, str) or not CHAT_ID.fullmatch(chat):
            raise ValueError("invalid chat id")
        d = self._dir(project)
        return d / f"{chat}.json", d / f"{chat}.jsonl"

    # ---- writing ----
    def begin(self, project: str, chat: str, **meta: Any) -> None:
        now = time.time()
        with self._lock:
            path, _ = self._paths(project, chat)
            path.parent.mkdir(parents=True, exist_ok=True)
            old = self._read_meta(path) or {}
            self._write_meta(path, {"id": chat, "project": project, "title": "", "created": now, "turns": 0,
                                    **old, **{k: v for k, v in meta.items() if v is not None}, "updated": now})

    def update(self, project: str, chat: str, **meta: Any) -> None:
        with self._lock:
            path, _ = self._paths(project, chat)
            old = self._read_meta(path)
            if old is not None:
                self._write_meta(path, {**old, **{k: v for k, v in meta.items() if v is not None}, "updated": time.time()})

    def record(self, project: str, chat: str, event: dict[str, Any]) -> None:
        """Add one live chat event. Never raises: a full disk must not break the chat itself."""
        try:
            kind, data = event.get("type"), event.get("data") if isinstance(event.get("data"), dict) else {}
            with self._lock:
                key = (project, chat)
                if kind == "text_delta":
                    cur = self._text.get(key)
                    if cur is None or cur["item_id"] != data.get("item_id"):
                        self._flush(key)
                        cur = self._text[key] = {"item_id": data.get("item_id"), "text": "", "time": event.get("time")}
                    cur["text"] += str(data.get("text") or "")
                    return
                self._flush(key)
                if kind in SKIP:
                    return
                self._append(key, {"type": kind, "data": data, "time": event.get("time") or time.time()})
                path, _ = self._paths(project, chat)
                meta = self._read_meta(path)
                if meta is None:
                    return
                if kind == "user_message":
                    meta["turns"] = int(meta.get("turns") or 0) + 1
                    if not meta.get("title"):
                        meta["title"] = " ".join(str(data.get("text") or "").split())[:MAX_TITLE]
                meta["updated"] = time.time()
                self._write_meta(path, meta)
        except (OSError, ValueError, TypeError):
            pass

    def flush(self, project: str, chat: str) -> None:
        try:
            with self._lock:
                self._flush((project, chat))
        except (OSError, ValueError):
            pass

    def _flush(self, key: tuple[str, str]) -> None:
        cur = self._text.pop(key, None)
        if cur and cur["text"]:
            self._append(key, {"type": "text", "data": {"text": cur["text"], "item_id": cur["item_id"]}, "time": cur["time"]})

    def _append(self, key: tuple[str, str], event: dict[str, Any]) -> None:
        _, path = self._paths(*key)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size + len(line.encode("utf-8")) > MAX_FILE_BYTES:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    @staticmethod
    def _read_meta(path: pathlib.Path) -> dict[str, Any] | None:
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            return meta if isinstance(meta, dict) else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write_meta(path: pathlib.Path, meta: dict[str, Any]) -> None:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    # ---- reading ----
    def meta(self, project: str, chat: str) -> dict[str, Any] | None:
        path, _ = self._paths(project, chat)
        return self._read_meta(path)

    def list(self, project: str) -> list[dict[str, Any]]:
        d = self._dir(project)
        chats = []
        try:
            files = [p for p in d.iterdir() if p.suffix == ".json" and CHAT_ID.fullmatch(p.stem)]
        except FileNotFoundError:
            return []
        for p in files:
            meta = self._read_meta(p)
            if meta and meta.get("turns"):  # a chat that never got a message is not worth listing
                chats.append({k: meta.get(k) for k in ("id", "title", "created", "updated", "turns", "settings")})
        chats.sort(key=lambda m: m.get("updated") or 0, reverse=True)
        return chats[:MAX_LIST]

    def events(self, project: str, chat: str) -> list[dict[str, Any]]:
        self.flush(project, chat)
        _, path = self._paths(project, chat)
        out = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        out.append(event)
        except FileNotFoundError:
            pass
        return out

    def delete(self, project: str, chat: str) -> bool:
        with self._lock:
            self._text.pop((project, chat), None)
            gone = False
            for path in self._paths(project, chat):
                try:
                    path.unlink()
                    gone = True
                except FileNotFoundError:
                    pass
            return gone


__all__ = ["ChatHistory"]
