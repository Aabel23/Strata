"""Chat history kept as Markdown notes in the user's Obsidian vault.

One note per chat: `<vault>/strata-chat/<project>/<YYYYMMDD-HHMMSS-xxxxxxxx>.md`, pasted images next to it in
`images/`. The note reads as a normal transcript in Obsidian; every block starts with a line that ends in an HTML
comment carrying a per-note random mark, which is how Strata reads the blocks back (text typed by the user or
written by Claude cannot contain the mark, so it cannot forge a block). Notes are only ever appended to.

The vault is `$STRATA_CHAT_VAULT`, else `~/.secondbrain`; when that folder does not exist, history is off.
"""
from __future__ import annotations

import base64
import binascii
import os
import pathlib
import re
import secrets
import threading
import time
from typing import Any

import yaml

FOLDER = "strata-chat"
DEFAULT_VAULT = "~/.secondbrain"
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_NOTE_BYTES = 8 * 1024 * 1024
MAX_LIST = 100
MAX_BLOCKS = 600
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
_EXT_TYPES = {ext: kind for kind, ext in IMAGE_TYPES.items()}
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
HISTORY_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{8}")
IMAGE_NAME = re.compile(r"(\d{8}-\d{6}-[0-9a-f]{8})-\d{1,4}\.(png|jpg|gif|webp)")
_SESSION = re.compile(r"[A-Za-z0-9_-]{8,128}")
_THREAD = re.compile(r"[A-Za-z0-9_-]{1,128}")
_MARK = re.compile(r"[0-9a-f]{16}")
_KINDS = "user|claude|tool|note|image|session|thread"
_HEADS = {"user": "#### You ", "claude": "#### Claude ", "tool": "", "note": ""}


class HistoryError(ValueError):
    pass


def _magic(kind: str, data: bytes) -> bool:
    return {"image/png": data.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": data.startswith(b"\xff\xd8\xff"),
            "image/gif": data[:6] in (b"GIF87a", b"GIF89a"),
            "image/webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP"}.get(kind, False)


def check_images(raw: Any) -> list[dict[str, str]]:
    """Validate the `images` of a turn: [{media_type, data(base64)}]. Returns them normalized; ValueError when bad."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_IMAGES:
        raise HistoryError(f"at most {MAX_IMAGES} images per message")
    out = []
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"media_type", "data"}:
            raise HistoryError("invalid image")
        kind, data = item["media_type"], item["data"]
        if kind not in IMAGE_TYPES or not isinstance(data, str) or len(data) > MAX_IMAGE_BYTES * 4 // 3 + 4:
            raise HistoryError("unsupported or too large image")
        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HistoryError("invalid image data") from exc
        if not decoded or len(decoded) > MAX_IMAGE_BYTES or not _magic(kind, decoded):
            raise HistoryError("image data does not match its type")
        out.append({"media_type": kind, "data": data})
    return out


def _arg(input_: Any) -> str:
    if isinstance(input_, dict):
        for key in ("command", "file_path", "notebook_path", "path", "pattern", "url", "query", "description", "prompt"):
            if input_.get(key) is not None:
                input_ = input_[key]
                break
        else:
            return ""
    return str(input_ or "").split("\n")[0][:160]


class ChatHistory:
    def __init__(self, vault: str | os.PathLike[str] | None = None, environ: dict[str, str] | None = None):
        source = os.environ if environ is None else environ
        raw = vault if vault is not None else (source.get("STRATA_CHAT_VAULT") or DEFAULT_VAULT)
        path = pathlib.Path(raw).expanduser()
        self.vault = path.resolve() if path.is_dir() else None

    @property
    def enabled(self) -> bool:
        return self.vault is not None

    def folder(self, project: str, *, create: bool = False) -> pathlib.Path:
        if self.vault is None:
            raise HistoryError("chat history is off: the vault folder does not exist")
        if not isinstance(project, str) or not _PROJECT.fullmatch(project):
            raise HistoryError("invalid project")
        path = self.vault / FOLDER / project
        if create:
            (path / "images").mkdir(parents=True, exist_ok=True)
        if path.exists() and not path.resolve().is_relative_to(self.vault):
            raise HistoryError("chat history folder leaves the vault")
        return path

    def _note(self, project: str, hid: str) -> pathlib.Path:
        if not isinstance(hid, str) or not HISTORY_ID.fullmatch(hid):
            raise HistoryError("invalid chat id")
        return self.folder(project) / f"{hid}.md"

    @staticmethod
    def _front(text: str) -> tuple[dict[str, Any], str]:
        if text.startswith("---\n"):
            end = text.find("\n---\n", 4)
            if end > 0:
                try:
                    meta = yaml.safe_load(text[4:end])
                except yaml.YAMLError:
                    meta = None
                if isinstance(meta, dict):
                    return meta, text[end + 5:]
        return {}, text

    def list(self, project: str) -> list[dict[str, Any]]:
        """Newest first. Only notes this module wrote (name and front matter both fit)."""
        folder = self.folder(project)
        found = []
        try:
            entries = [e for e in os.scandir(folder) if e.name.endswith(".md") and HISTORY_ID.fullmatch(e.name[:-3]) and e.is_file(follow_symlinks=False)]
        except OSError:
            return []
        for entry in sorted(entries, key=lambda e: e.stat().st_mtime, reverse=True)[:MAX_LIST]:
            try:
                with open(entry.path, encoding="utf-8", errors="replace") as handle:
                    meta, _ = self._front(handle.read(8192))
            except OSError:
                continue
            if isinstance(meta.get("mark"), str):
                found.append({"id": entry.name[:-3], "title": str(meta.get("title") or "Chat")[:200],
                              "started": str(meta.get("started") or ""), "updated": entry.stat().st_mtime})
        return found

    def read(self, project: str, hid: str) -> dict[str, Any]:
        """The note as blocks, plus what a later chat needs to carry on: worktree session and Claude conversation id."""
        path = self._note(project, hid)
        try:
            if path.is_symlink() or path.stat().st_size > MAX_NOTE_BYTES:
                raise HistoryError("chat note is not readable")
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise HistoryError("chat not found") from exc
        meta, body = self._front(text)
        mark = meta.get("mark")
        if not isinstance(mark, str) or not _MARK.fullmatch(mark):
            raise HistoryError("chat note was not written by Strata")
        line = re.compile(r".*<!-- strata:" + mark + r":(" + _KINDS + r")(?::(\S*))? -->")
        blocks, session, thread, current = [], None, None, None
        for raw in body.split("\n"):
            hit = line.fullmatch(raw)
            if not hit:
                if current is not None:
                    current["text"] += raw + "\n"
                continue
            kind, arg = hit.group(1), hit.group(2) or ""
            current = None
            if kind == "session":
                session, thread = (arg if _SESSION.fullmatch(arg) else None), None
            elif kind == "thread":
                thread = arg if _THREAD.fullmatch(arg) else None
            elif kind == "image":
                if IMAGE_NAME.fullmatch(arg) and arg.startswith(hid + "-"):
                    blocks.append({"kind": "image", "image": arg})
            else:
                current = {"kind": kind, "text": ""}
                if arg.isdigit():
                    current["time"] = int(arg)
                blocks.append(current)
        for block in blocks:
            if "text" in block:
                block["text"] = block["text"].strip("\n")
        return {"id": hid, "title": str(meta.get("title") or "Chat")[:200], "started": str(meta.get("started") or ""),
                "mark": mark, "session": session, "thread": thread,
                "images": sum(b["kind"] == "image" for b in blocks), "blocks": blocks[-MAX_BLOCKS:]}

    def image(self, project: str, hid: str, name: str) -> dict[str, str]:
        hit = IMAGE_NAME.fullmatch(name) if isinstance(name, str) else None
        if not hit or not HISTORY_ID.fullmatch(hid or "") or hit.group(1) != hid:
            raise HistoryError("invalid image name")
        path = self.folder(project) / "images" / name
        try:
            if path.is_symlink() or path.stat().st_size > MAX_IMAGE_BYTES:
                raise HistoryError("image is not readable")
            data = path.read_bytes()
        except OSError as exc:
            raise HistoryError("image not found") from exc
        return {"media_type": _EXT_TYPES[hit.group(2)], "data": base64.b64encode(data).decode("ascii")}

    def recorder(self, project: str, session: str, resume: dict[str, Any] | None = None) -> "Recorder | None":
        """A writer for one chat. `session` names its worktree (`chat-<session>`); `resume` is a `read()` result to continue."""
        if not self.enabled:
            return None
        return Recorder(self, project, session, resume)


class Recorder:
    """Appends one chat to its note. The note appears with the first message, so chats nobody typed in leave nothing."""

    def __init__(self, history: ChatHistory, project: str, session: str, resume: dict[str, Any] | None = None):
        self._history, self.project, self._session = history, project, session
        self._lock = threading.Lock()
        self._pending: tuple[str, list[dict[str, str]]] | None = None
        self._text, self._item = "", None
        if resume:
            self.hid, self._mark, self._created = resume["id"], resume["mark"], True
            self._thread, self._images = resume.get("thread"), int(resume.get("images") or 0)
            self._session_written = resume.get("session") == session
            if not self._session_written:
                self._thread = None  # another worktree: Claude's earlier conversation is not reachable from it
        else:
            self.hid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)
            self._mark, self._created, self._thread, self._images, self._session_written = secrets.token_hex(8), False, None, 0, False

    def expect(self, text: str, images: list[dict[str, str]] | None = None) -> None:
        """The message about to be sent; it is written when the session reports the turn as started."""
        with self._lock:
            self._pending = (text, list(images or []))

    def forget(self) -> None:
        with self._lock:
            self._pending = None

    def event(self, event: dict[str, Any], thread: str | None = None) -> None:
        kind, data = event.get("type"), event.get("data") if isinstance(event.get("data"), dict) else {}
        with self._lock:
            try:
                if kind == "text_delta":
                    if self._text and data.get("item_id") != self._item:
                        self._flush()
                    self._item, self._text = data.get("item_id"), self._text + str(data.get("text") or "")
                    return
                self._flush()
                if kind == "turn_started" and self._pending is not None:
                    (text, images), self._pending = self._pending, None
                    self._user(text, images)
                elif kind == "item_started" and isinstance(data.get("item"), dict) and data["item"].get("type") == "tool":
                    item = data["item"]
                    self._block("tool", f"`{str(item.get('name') or 'tool')[:80]}` {_arg(item.get('input'))}".rstrip())
                elif kind in ("error", "protocol_error"):
                    self._block("note", str(data.get("message") or "Claude reported an error.")[:2000])
                elif kind == "turn_cancelled":
                    self._block("note", "Stopped.")
                if kind in ("turn_completed", "turn_cancelled") and self._created and thread and thread != self._thread and _THREAD.fullmatch(thread):
                    self._thread = thread
                    self._append(f"\n<!-- strata:{self._mark}:thread:{thread} -->\n")
            except OSError:
                pass  # a full or read-only vault must not break the chat itself

    # ---- writing (all under self._lock) ----
    def _path(self) -> pathlib.Path:
        return self._history.folder(self.project, create=True) / f"{self.hid}.md"

    def _append(self, text: str) -> None:
        with open(self._path(), "a", encoding="utf-8") as handle:
            handle.write(text)

    def _flush(self) -> None:
        text, self._text, self._item = self._text.strip("\n"), "", None
        if text:
            self._block("claude", text)

    def _block(self, kind: str, text: str) -> None:
        if not self._created:
            return  # nothing is recorded before the first user message
        stamp = f":{int(time.time())}" if kind in ("user", "claude") else ""
        self._append(f"\n{_HEADS[kind]}<!-- strata:{self._mark}:{kind}{stamp} -->\n\n{text}\n")

    def _user(self, text: str, images: list[dict[str, str]]) -> None:
        if not self._created:
            title = " ".join(text.split())[:80] or "Image"
            front = yaml.safe_dump({"title": title, "project": self.project, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "mark": self._mark, "tags": ["strata-chat"]}, allow_unicode=True, sort_keys=False)
            path = self._path()
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(f"---\n{front}---\n\n# {title}\n")
            self._created = True
        if not self._session_written:
            self._append(f"\n<!-- strata:{self._mark}:session:{self._session} -->\n")
            self._session_written = True
        self._block("user", text)
        for image in images:
            self._images += 1
            name = f"{self.hid}-{self._images}.{IMAGE_TYPES[image['media_type']]}"
            with open(self._path().parent / "images" / name, "xb") as handle:
                handle.write(base64.b64decode(image["data"]))
            self._append(f"\n![[{name}]] <!-- strata:{self._mark}:image:{name} -->\n")


__all__ = ["ChatHistory", "HistoryError", "Recorder", "check_images", "HISTORY_ID", "IMAGE_NAME", "MAX_IMAGES", "MAX_IMAGE_BYTES"]
