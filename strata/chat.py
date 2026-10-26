"""Project-bound supervisor for local Codex sessions and review worktrees."""
from __future__ import annotations

import os
import pathlib
import re
import secrets
import selectors
import signal
import subprocess
import threading
import time
import difflib
import stat
import json
import hashlib
from typing import Any, Mapping
from urllib.parse import urlsplit

from strata.chat_codex import CodexSession


MAX_SESSIONS = 4
MAX_DIFF_BYTES = 256 * 1024
MAX_STATUS_BYTES = 64 * 1024
MAX_GIT_OUTPUT = 16 * 1024 * 1024
MAX_FILE_DIFF_BYTES = 64 * 1024
MAX_WORKTREE_FILE_BYTES = 128 * 1024 * 1024
MAX_WORKTREE_BYTES = 2 * 1024 * 1024 * 1024
MAX_WORKTREE_TREE_BYTES = 16 * 1024 * 1024
GIT_TIMEOUT = 30
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_AUTH_HOSTS = {"auth.openai.com", "chatgpt.com"}


class ChatError(RuntimeError):
    """Safe supervisor failure suitable for conversion to a client error."""

    def __init__(self, message: str, *, session_id: str | None = None,
                 worktree: str | None = None):
        super().__init__(message)
        self.session_id = session_id
        self.worktree = worktree


def _safe_auth_url(value: Any) -> bool:
    if (not isinstance(value, str) or not value or len(value) > 4096
            or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7f for char in value)
            or "#" in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname in _AUTH_HOSTS
                and parsed.username is None and parsed.password is None
                and parsed.port in (None, 443) and not parsed.netloc.endswith(":"))
    except ValueError:
        return False


def _git_env() -> dict[str, str]:
    """Keep git's environment small and free of application/provider secrets."""
    allowed = {
        "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "USER", "LOGNAME", "LANG",
        "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA",
    }
    env = {key: value for key, value in os.environ.items()
           if key in allowed or key.startswith("LC_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
                "GIT_ATTR_NOSYSTEM": "1"})
    return env


def _capture_git(root: pathlib.Path, args: list[str], *, timeout: int = GIT_TIMEOUT,
                 output_limit: int = MAX_GIT_OUTPUT) -> tuple[bytes, bool]:
    # Command-scope overrides beat hostile local config (notably fsmonitor,
    # pager and external diff). Status/diff content is generated separately.
    command = ["git", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
               "-c", "core.hooksPath=" + os.devnull, "-c", "core.quotepath=true",
               "-c", "diff.external=", *args]
    proc = None
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    stderr = bytearray()
    truncated = False
    try:
        proc = subprocess.Popen(command, cwd=root, env=_git_env(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True, bufsize=0)
        assert proc.stdout is not None and proc.stderr is not None
        selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
        selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
        deadline = time.monotonic() + timeout
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            for key, _ in selector.select(min(remaining, 0.2)):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                if key.data == "stdout":
                    room = max(0, output_limit - len(stdout))
                    stdout.extend(chunk[:room])
                    if len(chunk) > room and not truncated:
                        truncated = True
                        _kill_git_process(proc)
                else:
                    room = max(0, 4096 - len(stderr))
                    stderr.extend(chunk[:room])
        try:
            code = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _kill_git_process(proc)
            raise TimeoutError
    except (OSError, TimeoutError) as exc:
        if proc is not None:
            _kill_git_process(proc)
        raise ChatError("git operation failed or timed out") from exc
    finally:
        selector.close()
    if code and not truncated:
        detail = bytes(stderr).decode("utf-8", "replace")[:1000].strip()
        raise ChatError(f"git operation failed{': ' + detail if detail else ''}")
    return bytes(stdout), truncated


def _kill_git_process(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=0.25)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass


def _run_git(root: pathlib.Path, args: list[str], *, timeout: int = GIT_TIMEOUT,
             output_limit: int = MAX_GIT_OUTPUT) -> bytes:
    output, truncated = _capture_git(root, args, timeout=timeout, output_limit=output_limit)
    if truncated:
        raise ChatError("git output exceeded the response limit")
    return output


def _has_symlink_ancestor(path: pathlib.Path) -> bool:
    raw = pathlib.Path(os.path.expanduser(os.fspath(path)))
    if not raw.is_absolute():
        raw = pathlib.Path.cwd() / raw
    current = pathlib.Path(raw.anchor)
    for part in raw.parts[1:]:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        candidate = current / part
        try:
            if candidate.is_symlink():
                return True
        except OSError:
            return True
        current = candidate
    return False


def _materialize_head(root: pathlib.Path, worktree: pathlib.Path) -> None:
    """Populate a no-checkout worktree from Git blobs without running filters."""
    tree = _run_git(root, ["ls-tree", "-r", "-z", "--full-tree", "HEAD"],
                    output_limit=MAX_WORKTREE_TREE_BYTES)
    entries = [entry for entry in tree.split(b"\0") if entry]
    total = 0
    worktree_root = worktree.resolve(strict=True)
    for entry in entries:
        try:
            header, raw_path = entry.split(b"\t", 1)
            mode, obj_type, oid = header.decode("ascii").split(" ")
            path_parts = raw_path.split(b"/")
            if (not path_parts or any(part in (b"", b".", b"..") for part in path_parts)
                    or raw_path.startswith(b"/")):
                raise ValueError
        except (ValueError, UnicodeDecodeError) as exc:
            raise ChatError("Git tree contains an invalid path") from exc
        if obj_type != "blob":
            continue  # Submodule gitlinks are not materialized as files.
        size_raw = _run_git(root, ["cat-file", "-s", oid], output_limit=64).strip()
        try:
            size = int(size_raw)
        except ValueError as exc:
            raise ChatError("Git returned an invalid blob size") from exc
        if size > MAX_WORKTREE_FILE_BYTES or total + size > MAX_WORKTREE_BYTES:
            raise ChatError("project is too large for a bounded chat worktree")
        total += size
        target = worktree_root
        for part in path_parts[:-1]:
            target = target / os.fsdecode(part)
            if target.is_symlink():
                raise ChatError("Git tree contains a symlinked parent path")
            target.mkdir(exist_ok=True)
            if not target.is_dir():
                raise ChatError("Git tree contains a file and directory path collision")
        destination = target / os.fsdecode(path_parts[-1])
        mode_value = int(mode, 8)
        if mode_value == 0o120000:
            link = _run_git(root, ["cat-file", "blob", oid], output_limit=4096)
            if len(link) > 4096 or b"\0" in link:
                raise ChatError("Git tree contains an unsafe symlink")
            link_target = os.fsdecode(link)
            if os.path.isabs(link_target):
                raise ChatError("Git tree contains an absolute symlink")
            resolved_target = (destination.parent / link_target).resolve(strict=False)
            if not resolved_target.is_relative_to(worktree_root):
                raise ChatError("Git tree contains an escaping symlink")
            os.symlink(link_target, destination)
            continue
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=True) as output:
                try:
                    proc = subprocess.run(["git", "-c", "core.fsmonitor=false",
                                           "-c", "core.untrackedCache=false", "cat-file", "blob", oid],
                                          cwd=root, env=_git_env(), stdin=subprocess.DEVNULL,
                                          stdout=output, stderr=subprocess.DEVNULL,
                                          timeout=GIT_TIMEOUT, check=False)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise ChatError("could not materialize Git worktree file") from exc
                if proc.returncode != 0 or destination.stat().st_size != size:
                    raise ChatError("could not materialize Git worktree file")
            os.chmod(destination, 0o755 if mode_value & 0o111 else 0o644)
        except Exception:
            try:
                destination.unlink()
            except OSError:
                pass
            raise


def _read_worktree_file(root: pathlib.Path, raw_path: bytes) -> tuple[bytes | None, str]:
    """Read a regular file without following any symlinked path component."""
    parts = raw_path.split(b"/")
    if not parts or any(part in (b"", b".", b"..") for part in parts):
        return None, "unsafe"
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(root, directory_flags)
    except OSError:
        return None, "unsafe"
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags | nofollow, dir_fd=fd)
            except OSError:
                return None, "unsafe"
            os.close(fd)
            fd = next_fd
        name = parts[-1]
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return None, "missing"
        except OSError:
            return None, "unsafe"
        if stat.S_ISLNK(info.st_mode):
            try:
                target = os.readlink(name, dir_fd=fd)
                return os.fsencode(target), "symlink"
            except OSError:
                return None, "unsafe"
        if not stat.S_ISREG(info.st_mode):
            return None, "special"
        if info.st_size > MAX_FILE_DIFF_BYTES:
            return None, "large"
        flags = os.O_RDONLY | nofollow
        try:
            file_fd = os.open(name, flags, dir_fd=fd)
        except OSError:
            return None, "unsafe"
        try:
            opened = os.fstat(file_fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_FILE_DIFF_BYTES:
                return None, "large"
            content = bytearray()
            while len(content) <= MAX_FILE_DIFF_BYTES:
                chunk = os.read(file_fd, min(8192, MAX_FILE_DIFF_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
            if len(content) > MAX_FILE_DIFF_BYTES:
                return None, "large"
            return bytes(content), "regular"
        finally:
            os.close(file_fd)
    finally:
        os.close(fd)


def _format_review_diff(root: pathlib.Path, status_raw: bytes, *, limit: int) -> tuple[str, bool]:
    tree = _read_head_tree(root)

    changed: dict[bytes, bytes] = {}
    entries = status_raw.split(b"\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4 or entry[2:3] != b" ":
            continue
        code, path = entry[:2], entry[3:]
        changed[path] = code
        if b"R" in code or b"C" in code:
            if index < len(entries) and entries[index]:
                changed[entries[index]] = code
            index += 1

    output = bytearray()
    truncated = False

    def append(piece: str) -> None:
        nonlocal truncated
        raw = piece.encode("utf-8", "replace")
        remaining = limit - len(output)
        if len(raw) <= remaining:
            output.extend(raw)
        else:
            output.extend(raw[:max(0, remaining)])
            truncated = True

    for path, code in changed.items():
        head = tree.get(path)
        if code == b"??" and head is not None:
            head = None
        old: bytes | None = None
        if head is not None:
            old_raw, old_truncated = _capture_git(root, ["cat-file", "blob", head[1]],
                                                  output_limit=MAX_FILE_DIFF_BYTES + 1)
            if old_truncated or len(old_raw) > MAX_FILE_DIFF_BYTES:
                append(f"--- a/{json.dumps(os.fsdecode(path))}\n+++ b/{json.dumps(os.fsdecode(path))}\n[tracked file omitted: too large]\n")
                if truncated:
                    break
                continue
            old = old_raw
        current, current_kind = _read_worktree_file(root, path)
        if current_kind in {"large", "unsafe", "special"}:
            append(f"--- a/{json.dumps(os.fsdecode(path))}\n+++ b/{json.dumps(os.fsdecode(path))}\n[{current_kind} file content omitted]\n")
            if truncated:
                break
            continue
        if current_kind == "symlink":
            append(f"--- a/{json.dumps(os.fsdecode(path))}\n+++ b/{json.dumps(os.fsdecode(path))}\n[symlink target omitted]\n")
            if truncated:
                break
            continue
        new = current if current is not None else b""
        if old == new:
            continue
        if (old is not None and b"\0" in old) or b"\0" in new:
            append(f"--- a/{json.dumps(os.fsdecode(path))}\n+++ b/{json.dumps(os.fsdecode(path))}\n[binary file content omitted]\n")
            if truncated:
                break
            continue
        old_text = old.decode("utf-8", "replace").splitlines(keepends=True) if old is not None else []
        new_text = new.decode("utf-8", "replace").splitlines(keepends=True)
        label = json.dumps(os.fsdecode(path), ensure_ascii=True)
        diff_lines = difflib.unified_diff(old_text, new_text, fromfile=f"a/{label}",
                                          tofile=f"b/{label}", n=3)
        append("".join(diff_lines))
        if truncated:
            break
    if truncated and limit >= 32:
        marker = "\n[review diff truncated]\n".encode()
        keep = min(len(output), len(marker))
        if keep:
            output[-keep:] = marker[:keep]
        if keep < len(marker):
            output.extend(marker[keep:min(len(marker) - keep, limit - len(output))])
    return output.decode("utf-8", "ignore"), truncated


def _read_head_tree(root: pathlib.Path) -> dict[bytes, tuple[str, str]]:
    raw = _run_git(root, ["ls-tree", "-r", "-z", "--full-tree", "HEAD"],
                   output_limit=MAX_WORKTREE_TREE_BYTES)
    tree = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        try:
            header, path = entry.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split(" ")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ChatError("Git returned an invalid tree entry") from exc
        if kind == "blob":
            tree[path] = (mode, oid)
    return tree


def _read_index(root: pathlib.Path) -> dict[bytes, tuple[str, str, int]]:
    raw = _run_git(root, ["ls-files", "--stage", "-z"], output_limit=MAX_WORKTREE_TREE_BYTES)
    index = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        try:
            header, path = entry.split(b"\t", 1)
            mode, oid, stage = header.decode("ascii").split(" ")
            index[path] = (mode, oid, int(stage))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ChatError("Git returned an invalid index entry") from exc
    return index


def _hash_worktree_file(root: pathlib.Path, raw_path: bytes, object_format: str) -> tuple[str | None, str, str | None]:
    parts = raw_path.split(b"/")
    if not parts or any(part in (b"", b".", b"..") for part in parts):
        return None, "unsafe", None
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(root, directory_flags)
    except OSError:
        return None, "unsafe", None
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags | nofollow, dir_fd=fd)
            except OSError:
                return None, "missing", None
            os.close(fd)
            fd = next_fd
        try:
            info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            return None, "missing", None
        except OSError:
            return None, "unsafe", None
        if stat.S_ISLNK(info.st_mode):
            try:
                target = os.fsencode(os.readlink(parts[-1], dir_fd=fd))
            except OSError:
                return None, "unsafe", None
            data = target
            mode = "120000"
        elif stat.S_ISREG(info.st_mode):
            if info.st_size > MAX_WORKTREE_FILE_BYTES:
                return None, "large", None
            try:
                file_fd = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=fd)
            except OSError:
                return None, "unsafe", None
            try:
                opened = os.fstat(file_fd)
                if not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_WORKTREE_FILE_BYTES:
                    return None, "large", None
                digest = hashlib.sha1() if object_format == "sha1" else hashlib.sha256()
                digest.update(f"blob {opened.st_size}\0".encode())
                read = 0
                while True:
                    block = os.read(file_fd, 65536)
                    if not block:
                        break
                    read += len(block)
                    if read > MAX_WORKTREE_FILE_BYTES:
                        return None, "large", None
                    digest.update(block)
                if read != opened.st_size:
                    return None, "unsafe", None
                mode = "100755" if opened.st_mode & 0o111 else "100644"
                return digest.hexdigest(), "regular", mode
            finally:
                os.close(file_fd)
        else:
            return None, "special", None
        digest = hashlib.sha1() if object_format == "sha1" else hashlib.sha256()
        digest.update(f"blob {len(data)}\0".encode())
        digest.update(data)
        return digest.hexdigest(), "symlink", mode
    finally:
        os.close(fd)


def _safe_status(root: pathlib.Path) -> tuple[bytes, bool]:
    head = _read_head_tree(root)
    index = _read_index(root)
    object_format = _run_git(root, ["rev-parse", "--show-object-format"], output_limit=64).decode().strip()
    if object_format not in {"sha1", "sha256"}:
        raise ChatError("unsupported Git object format")
    entries: dict[bytes, bytes] = {}
    for path in sorted(set(head) | set(index)):
        head_entry = head.get(path)
        index_entry = index.get(path)
        if index_entry is not None and index_entry[2] != 0:
            entries[path] = b"U "
            continue
        x = b" "
        if head_entry is None and index_entry is not None:
            x = b"A"
        elif head_entry is not None and index_entry is None:
            x = b"D"
        elif head_entry and index_entry and (head_entry[1] != index_entry[1] or head_entry[0] != index_entry[0]):
            x = b"M"
        y = b" "
        if index_entry is not None:
            actual_oid, kind, actual_mode = _hash_worktree_file(root, path, object_format)
            if kind == "missing":
                y = b"D"
            elif kind not in {"unsafe", "special"} and actual_oid is not None:
                if actual_oid != index_entry[1] or actual_mode != index_entry[0]:
                    y = b"M"
        elif head_entry is not None:
            actual_oid, kind, actual_mode = _hash_worktree_file(root, path, object_format)
            if kind not in {"missing", "unsafe", "special"}:
                y = b"A"
        if x != b" " or y != b" ":
            entries[path] = x + y
    untracked, truncated = _capture_git(root, ["ls-files", "--others", "--exclude-standard", "-z"],
                                        output_limit=MAX_STATUS_BYTES)
    for path in untracked.split(b"\0"):
        if path:
            entries[path] = b"??"
    result = bytearray()
    for path, code in sorted(entries.items()):
        item = code + b" " + path + b"\0"
        if len(result) + len(item) > MAX_STATUS_BYTES:
            truncated = True
            break
        result.extend(item)
    return bytes(result), truncated


class ChatSupervisor:
    """Own Codex sessions rooted only in registered project Git worktrees.

    ``projects`` maps registered project IDs to their registered root paths.
    Every public operation except ``auth_status`` and ``shutdown`` requires the
    project ID plus the opaque session ID returned by ``start``.
    """

    def __init__(self, projects: Mapping[str, str | os.PathLike[str]], *,
                 session_factory=CodexSession, max_sessions: int = MAX_SESSIONS):
        self._projects = self._validated_projects(projects)
        self._session_factory = session_factory
        self._max_sessions = max(1, min(int(max_sessions), MAX_SESSIONS))
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._shutting_down = False

    @classmethod
    def _validated_projects(cls, projects: Mapping[str, str | os.PathLike[str]]) -> dict[str, str]:
        if not isinstance(projects, Mapping):
            raise ChatError("project registry must be a mapping")
        validated = {}
        for project, root in projects.items():
            project = cls._project_id(project)
            if not isinstance(root, (str, os.PathLike)):
                raise ChatError("registered project root must be a path")
            try:
                path = pathlib.Path(root).expanduser()
                if not path.is_absolute():
                    path = pathlib.Path.cwd() / path
                if _has_symlink_ancestor(path):
                    raise ChatError("registered project root or one of its ancestors may not be a symlink")
                validated[project] = os.path.normpath(os.fspath(path))
            except ChatError:
                raise
            except (TypeError, ValueError, OSError) as exc:
                raise ChatError("registered project root is invalid") from exc
        return validated

    def refresh_projects(self, projects: Mapping[str, str | os.PathLike[str]]) -> None:
        """Replace the DB-backed registry and invalidate sessions with stale roots.

        The lock covers both registry replacement and session shutdown. Public
        session operations hold the same lock through delegation, so refresh
        cannot race an operation using a registration that has just changed.
        Worktrees remain on disk for review.
        """
        updated = self._validated_projects(projects)
        with self._lock:
            self._projects = updated
            for record in self._sessions.values():
                registered = updated.get(record["project"])
                if registered is None or not self._same_root(record["root"], registered):
                    record["invalidated"] = True
                    if not record["closed"]:
                        record["closed"] = True
                        session = record.get("session")
                        if session is not None:
                            try:
                                session.close()
                            except Exception:
                                pass

    update_projects = refresh_projects

    @staticmethod
    def _same_root(left: str | os.PathLike[str], right: str | os.PathLike[str]) -> bool:
        try:
            return pathlib.Path(left).expanduser().resolve(strict=False) == pathlib.Path(right).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return False

    @staticmethod
    def _project_id(project: str) -> str:
        if not isinstance(project, str) or not _PROJECT_ID.fullmatch(project):
            raise ChatError("invalid project ID")
        return project

    def _registered_root(self, project: str, root: str | os.PathLike[str]) -> pathlib.Path:
        project = self._project_id(project)
        if project not in self._projects:
            raise ChatError("project is not registered")
        try:
            supplied = pathlib.Path(root).expanduser()
            registered = pathlib.Path(self._projects[project]).expanduser()
            if _has_symlink_ancestor(supplied) or _has_symlink_ancestor(registered):
                raise ChatError("project root or one of its ancestors may not be a symlink")
            supplied = supplied.resolve(strict=True)
            registered = registered.resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise ChatError("project root is unavailable") from exc
        if supplied != registered or not supplied.is_dir():
            raise ChatError("project root does not match its registered root")
        try:
            top = _run_git(supplied, ["rev-parse", "--show-toplevel"], output_limit=8192).decode().strip()
            inside = _run_git(supplied, ["rev-parse", "--is-inside-work-tree"], output_limit=64).decode().strip()
            if inside != "true" or pathlib.Path(top).resolve(strict=True) != supplied:
                raise ChatError("project root must be the Git top-level directory")
            # A real repository nested in another repository is also rejected.
            parent = supplied.parent
            while parent != parent.parent:
                try:
                    ancestor_top = _run_git(parent, ["rev-parse", "--show-toplevel"], output_limit=8192).decode().strip()
                except ChatError:
                    ancestor_top = ""
                if ancestor_top:
                    raise ChatError("nested Git project roots are not supported")
                parent = parent.parent
        except (OSError, ValueError) as exc:
            if isinstance(exc, ChatError):
                raise
            raise ChatError("project root is not a valid Git repository") from exc
        return supplied

    def _worktree_base(self, project: str, root: pathlib.Path) -> pathlib.Path:
        base = root.parent / ".strata-worktrees"
        if base.exists() and base.is_symlink():
            raise ChatError("worktree directory may not be a symlink")
        base.mkdir(parents=True, exist_ok=True)
        project_dir = base / project
        if project_dir.exists() and project_dir.is_symlink():
            raise ChatError("project worktree directory may not be a symlink")
        project_dir.mkdir(parents=True, exist_ok=True)
        if not project_dir.resolve().is_relative_to(base.resolve()):
            raise ChatError("worktree directory escaped its allowed parent")
        return project_dir

    def start(self, project: str, root: str | os.PathLike[str], provider: str = "codex",
              model: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._shutting_down:
                raise ChatError("chat supervisor is shutting down")
            if sum(not record["closed"] for record in self._sessions.values()) >= self._max_sessions:
                raise ChatError("maximum live chat sessions reached")
            project = self._project_id(project)
            git_root = self._registered_root(project, root)
            session_id = secrets.token_urlsafe(24)
            worktree = self._worktree_base(project, git_root) / f"chat-{session_id}"
            record = {"project": project, "root": git_root, "worktree": worktree,
                      "session": None, "closed": True, "startup_error": None}
            registered_worktree = False
            session = None
            try:
                _run_git(git_root, ["-c", "core.hooksPath=" + os.devnull,
                                    "worktree", "add", "--detach", "--no-checkout",
                                    str(worktree), "HEAD"])
                registered_worktree = True
                record["worktree"] = worktree.resolve(strict=True)
                self._sessions[session_id] = record
                _run_git(record["worktree"], ["read-tree", "HEAD"])
                _materialize_head(git_root, record["worktree"])
                resolved = record["worktree"]
                if not resolved.is_relative_to(worktree.parent.resolve()):
                    raise ChatError("created worktree escaped its allowed parent")
                session = self._session_factory(resolved, provider=provider, model=model)
                record["session"] = session
                auth = (CodexSession.auth_status(provider)
                        if provider == "codex" and self._session_factory is CodexSession else None)
                if isinstance(auth, dict) and auth.get("status") == "login_required":
                    thread_id = None
                else:
                    thread_id = session.start()
                record["closed"] = False
            except Exception as exc:
                # Keep partial worktrees and an opaque lookup record. Close only
                # the agent process; the user can inspect the retained files.
                if not registered_worktree and worktree.exists() and (worktree / ".git").exists():
                    registered_worktree = True
                    record["worktree"] = worktree.resolve()
                    self._sessions[session_id] = record
                if registered_worktree:
                    if session is not None:
                        try:
                            session.close()
                        except Exception:
                            pass
                    message = str(exc)[:500] or "could not start Codex in the project worktree"
                    record["startup_error"] = message
                    raise ChatError("chat startup failed; review worktree retained",
                                    session_id=session_id, worktree=str(record["worktree"])) from exc
                if isinstance(exc, ChatError):
                    raise
                raise ChatError("could not create Codex review worktree") from exc
            return {"project": project, "session_id": session_id,
                    "thread_id": thread_id, "worktree": str(record["worktree"])}

    def _get(self, project: str, session_id: str, *, allow_closed: bool = False) -> dict[str, Any]:
        if not isinstance(project, str) or not isinstance(session_id, str):
            raise ChatError("project and session ID are required")
        try:
            project = self._project_id(project)
        except ChatError as exc:
            raise ChatError("chat session not found for this project") from exc
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None or not secrets.compare_digest(record["project"], project):
                raise ChatError("chat session not found for this project")
            if record.get("invalidated"):
                raise ChatError("chat session was invalidated by a project registration change")
            if record["closed"] and not allow_closed:
                raise ChatError("chat session is closed")
            return record

    def turn(self, project: str, session_id: str, message: str) -> str:
        with self._lock:
            return self._get(project, session_id)["session"].turn(message)

    def events(self, project: str, session_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            events = self._get(project, session_id)["session"].events(after)
        safe = []
        for event in events[:MAX_SESSIONS * 2000]:
            if not isinstance(event, dict):
                continue
            kind, data = event.get("type"), event.get("data")
            if kind in {"login_started", "login_status"}:
                if not isinstance(data, dict):
                    continue
                url = data.get("authUrl") or data.get("url")
                if url is not None and not _safe_auth_url(url):
                    continue
            safe.append(event)
        return safe

    def decide(self, project: str, session_id: str, approval_id: str, allow: bool) -> bool:
        with self._lock:
            return self._get(project, session_id)["session"].decide(approval_id, allow)

    def cancel(self, project: str, session_id: str) -> bool:
        with self._lock:
            return self._get(project, session_id)["session"].cancel()

    def close(self, project: str, session_id: str) -> bool:
        with self._lock:
            record = self._get(project, session_id, allow_closed=True)
            if record["closed"]:
                return False
            record["closed"] = True
            record["session"].close()
            return True

    def login(self, project: str, session_id: str) -> dict[str, str]:
        """Return an official login URL for the UI to display; never open it.

        Codex's browser flow redirects to a localhost callback on the Strata
        server, so remote viewers may need a tunnel for that callback port.
        """
        with self._lock:
            result = self._get(project, session_id)["session"].login()
        url = result.get("authUrl") or result.get("url") if isinstance(result, dict) else None
        login_id = result.get("loginId") if isinstance(result, dict) else None
        if not _safe_auth_url(url):
            raise ChatError("Codex returned an unsupported login URL")
        response = {"url": url}
        if isinstance(login_id, str) and login_id and len(login_id) <= 256:
            response["login_id"] = login_id
        return response

    def cancel_login(self, project: str, session_id: str, login_id: str) -> bool:
        if not isinstance(login_id, str) or not login_id or len(login_id) > 256:
            raise ChatError("invalid login ID")
        with self._lock:
            return self._get(project, session_id)["session"].cancel_login(login_id)

    @staticmethod
    def auth_status(provider: str = "codex") -> dict[str, Any]:
        return CodexSession.auth_status(provider)

    def diff_status(self, project: str, session_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._get(project, session_id, allow_closed=True)
            root = record["worktree"]
            status_raw, status_truncated = _safe_status(root)
            status_output = bytearray()
            for entry in status_raw.split(b"\0"):
                if len(entry) >= 4 and entry[2:3] == b" ":
                    line = f"{entry[:2].decode('ascii', 'replace')} {json.dumps(os.fsdecode(entry[3:]), ensure_ascii=True)}\n".encode()
                    if len(status_output) + len(line) > MAX_STATUS_BYTES:
                        status_truncated = True
                        break
                    status_output.extend(line)
            if status_truncated:
                marker = b"[status truncated]\n"
                status_output = status_output[:max(0, MAX_STATUS_BYTES - len(marker))]
                status_output.extend(marker)
            status_text = status_output.decode("utf-8", "replace")
            diff_text, diff_truncated = _format_review_diff(root, status_raw, limit=MAX_DIFF_BYTES)
            return {"status": status_text,
                    "diff": diff_text,
                    "status_truncated": status_truncated, "diff_truncated": diff_truncated,
                    "worktree": str(root), "closed": record["closed"],
                    "startup_error": record.get("startup_error")}

    def diff(self, project: str, session_id: str) -> dict[str, Any]:
        return self.diff_status(project, session_id)

    def status(self, project: str, session_id: str) -> dict[str, Any]:
        return self.diff_status(project, session_id)

    def shutdown(self) -> None:
        with self._lock:
            self._shutting_down = True
            records = list(self._sessions.values())
            for record in records:
                record["closed"] = True
        for record in records:
            try:
                record["session"].close()
            except Exception:
                pass


__all__ = ["ChatError", "ChatSupervisor"]
