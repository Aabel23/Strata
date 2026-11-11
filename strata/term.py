"""Browser terminal: real shells on the server, each behind a PTY.

The viewer's dock opens one with `POST /api/term` and reads its output with a
long-polling `GET /api/term/read`. A terminal belongs to the server process, not
to a page: reloading the viewer re-attaches and replays the kept tail of output.
This is a shell with the server user's rights, so the routes sit behind their
own switch (`allow_terminal`), the per-start token and the Origin/Host checks.
"""
from __future__ import annotations

import fcntl
import os
import pty
import secrets
import signal
import struct
import subprocess
import termios
import threading

MAX_TERMINALS = 6
MAX_BUFFER = 512 * 1024  # replayed to a page that re-attaches
MAX_INPUT = 64 * 1024
READ_WAIT = 25.0


class TermError(RuntimeError):
    pass


class Terminal:
    def __init__(self, cwd: str, cols: int, rows: int, title: str = ""):
        self.id, self.cwd, self.title = secrets.token_urlsafe(12), cwd, title
        self._changed = threading.Condition()
        self._buffer, self._start, self.closed = bytearray(), 0, False  # _start: stream offset of _buffer[0]
        master, slave = pty.openpty()
        self._fd = master
        self._resize_fd(cols, rows)
        shell = os.environ.get("SHELL") or "/bin/bash"
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
        for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):  # a `claude` started here is its own session
            env.pop(name, None)
        try:
            self._proc = subprocess.Popen([shell, "-l"], stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env, start_new_session=True,
                                          preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0), close_fds=True)
        except OSError as exc:
            os.close(master)
            raise TermError("could not start a shell") from exc
        finally:
            os.close(slave)
        threading.Thread(target=self._pump, daemon=True).start()

    def _resize_fd(self, cols: int, rows: int) -> None:
        fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(2, min(rows, 500)), max(2, min(cols, 1000)), 0, 0))

    def _pump(self) -> None:
        try:
            while True:
                chunk = os.read(self._fd, 65536)
                if not chunk:
                    break
                with self._changed:
                    self._buffer += chunk
                    extra = len(self._buffer) - MAX_BUFFER
                    if extra > 0:
                        del self._buffer[:extra]
                        self._start += extra
                    self._changed.notify_all()
        except OSError:
            pass  # EIO: the shell exited
        with self._changed:
            self.closed = True
            self._changed.notify_all()
        try:
            self._proc.wait(timeout=2)
        except Exception:
            pass

    def read(self, after: int, wait: float = READ_WAIT) -> tuple[bytes, int, bool]:
        """Output from stream offset `after` on: (bytes, next offset, closed). Waits while there is nothing new."""
        with self._changed:
            end = lambda: self._start + len(self._buffer)
            self._changed.wait_for(lambda: end() > after or self.closed, wait)
            begin = max(after, self._start)
            return bytes(self._buffer[begin - self._start:]), end(), self.closed

    def write(self, data: bytes) -> None:
        if self.closed:
            raise TermError("terminal has exited")
        try:
            os.write(self._fd, data)
        except OSError as exc:
            raise TermError("terminal has exited") from exc

    def resize(self, cols: int, rows: int) -> None:
        try:
            self._resize_fd(cols, rows)
        except OSError:
            pass

    def close(self) -> None:
        try:
            os.killpg(self._proc.pid, signal.SIGHUP)
        except (OSError, AttributeError):
            pass
        try:
            self._proc.wait(timeout=2)
        except Exception:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        with self._changed:
            self.closed = True
            self._changed.notify_all()


class TerminalManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._terms: dict[str, Terminal] = {}

    def open(self, cwd: str, cols: int = 100, rows: int = 28, title: str = "") -> Terminal:
        with self._lock:
            for key in [k for k, t in self._terms.items() if t.closed]:
                del self._terms[key]
            if len(self._terms) >= MAX_TERMINALS:
                raise TermError(f"at most {MAX_TERMINALS} terminals; close one first")
            if not os.path.isdir(cwd):
                raise TermError("working directory does not exist")
            term = Terminal(cwd, cols, rows, title)
            self._terms[term.id] = term
            return term

    def get(self, term_id: str) -> Terminal:
        with self._lock:
            term = self._terms.get(term_id)
        if term is None:
            raise TermError("no such terminal")
        return term

    def list(self) -> list[dict]:
        with self._lock:
            return [{"id": t.id, "title": t.title, "cwd": t.cwd} for t in self._terms.values() if not t.closed]

    def process_roots(self) -> list[tuple[str, int]]:
        """Internal PTY owners for matching live CLI descendants; PIDs never enter the UI."""
        with self._lock:
            return [(t.id, t._proc.pid) for t in self._terms.values() if not t.closed]

    def close(self, term_id: str) -> bool:
        with self._lock:
            term = self._terms.pop(term_id, None)
        if term is None:
            return False
        term.close()
        return True

    def close_all(self) -> None:
        with self._lock:
            terms, self._terms = list(self._terms.values()), {}
        for term in terms:
            term.close()


MANAGER = TerminalManager()  # one per process: every bound address serves the same terminals

__all__ = ["MANAGER", "TermError", "Terminal", "TerminalManager"]
