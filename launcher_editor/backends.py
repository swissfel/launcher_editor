"""File access backends.

The editor talks to configuration files through a small backend interface so
that the exact same GUI and model code can work against a local checkout or
directly against a remote host over SFTP (e.g. saresb-cons-05, where the
Bernina beamline launcher configuration actually lives).

All paths handled by backends are POSIX-style strings (the launcher
configuration always lives on Linux hosts), regardless of the platform the
editor itself runs on.
"""

from __future__ import annotations

import os
import posixpath
import stat
from dataclasses import dataclass
from typing import List, Optional


class BackendError(Exception):
    """Raised for any backend I/O failure, wrapping the underlying error."""


class Backend:
    """Abstract file-access backend. Paths are POSIX-style strings."""

    #: short label shown in the UI, e.g. "local" or "saresb-cons-05"
    label = "backend"

    def read_text(self, path: str) -> str:
        raise NotImplementedError

    def write_text(self, path: str, text: str) -> None:
        raise NotImplementedError

    def exists(self, path: str) -> bool:
        raise NotImplementedError

    def is_dir(self, path: str) -> bool:
        raise NotImplementedError

    def listdir(self, path: str) -> List[str]:
        raise NotImplementedError

    def remove(self, path: str) -> None:
        raise NotImplementedError

    def run_git(self, directory: str, args: List[str]) -> str:
        """Run a git command in ``directory`` and return combined output."""
        raise NotImplementedError

    # -- shared helpers -------------------------------------------------
    @staticmethod
    def dirname(path: str) -> str:
        return posixpath.dirname(path)

    @staticmethod
    def basename(path: str) -> str:
        return posixpath.basename(path)

    @staticmethod
    def join(base: str, *parts: str) -> str:
        return posixpath.normpath(posixpath.join(base, *parts))

    def close(self) -> None:
        pass


class LocalBackend(Backend):
    """Reads/writes files on the local filesystem."""

    label = "local"

    def read_text(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            raise BackendError(str(exc)) from exc

    def write_text(self, path: str, text: str) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            raise BackendError(str(exc)) from exc

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(path)

    def listdir(self, path: str) -> List[str]:
        try:
            return sorted(os.listdir(path))
        except OSError as exc:
            raise BackendError(str(exc)) from exc

    def remove(self, path: str) -> None:
        try:
            os.remove(path)
        except OSError as exc:
            raise BackendError(str(exc)) from exc

    def run_git(self, directory: str, args: List[str]) -> str:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "-C", directory] + args,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except OSError as exc:
            raise BackendError(str(exc)) from exc
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            raise BackendError(output.strip() or f"git {' '.join(args)} failed")
        return output


@dataclass
class RemoteConnectionInfo:
    host: str
    username: Optional[str] = None
    port: int = 22
    key_filename: Optional[str] = None
    password: Optional[str] = None


class SFTPBackend(Backend):
    """Reads/writes files on a remote host over SFTP (via paramiko).

    Intended for editing configuration that lives on a console server such
    as ``saresb-cons-05`` without needing a local NFS mount of ``/sf``.
    """

    def __init__(self, info: RemoteConnectionInfo):
        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover - exercised via message
            raise BackendError(
                "The 'paramiko' package is required for remote (SSH/SFTP) "
                "editing. Install it with: pip install paramiko"
            ) from exc

        self._paramiko = paramiko
        self.info = info
        self.label = info.host

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                info.host,
                port=info.port,
                username=info.username,
                key_filename=info.key_filename,
                password=info.password,
                timeout=10,
                allow_agent=True,
                look_for_keys=True,
            )
        except Exception as exc:
            raise BackendError(f"Could not connect to {info.host}: {exc}") from exc

        self._client = client
        self._sftp = client.open_sftp()

    def read_text(self, path: str) -> str:
        try:
            with self._sftp.open(path, "r") as fh:
                return fh.read().decode("utf-8")
        except (OSError, IOError) as exc:
            raise BackendError(f"{path}: {exc}") from exc

    def write_text(self, path: str, text: str) -> None:
        try:
            with self._sftp.open(path, "w") as fh:
                fh.write(text.encode("utf-8"))
        except (OSError, IOError) as exc:
            raise BackendError(f"{path}: {exc}") from exc

    def exists(self, path: str) -> bool:
        try:
            self._sftp.stat(path)
            return True
        except FileNotFoundError:
            return False
        except (OSError, IOError):
            return False

    def is_dir(self, path: str) -> bool:
        try:
            st = self._sftp.stat(path)
            return stat.S_ISDIR(st.st_mode)
        except (OSError, IOError):
            return False

    def listdir(self, path: str) -> List[str]:
        try:
            return sorted(self._sftp.listdir(path))
        except (OSError, IOError) as exc:
            raise BackendError(f"{path}: {exc}") from exc

    def remove(self, path: str) -> None:
        try:
            self._sftp.remove(path)
        except (OSError, IOError) as exc:
            raise BackendError(f"{path}: {exc}") from exc

    def run_git(self, directory: str, args: List[str]) -> str:
        cmd = "git -C " + _shell_quote(directory) + " " + " ".join(
            _shell_quote(a) for a in args
        )
        stdin, stdout, stderr = self._client.exec_command(cmd, timeout=30)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        output = out + err
        if rc != 0:
            raise BackendError(output.strip() or f"git {' '.join(args)} failed")
        return output

    def close(self) -> None:
        try:
            self._sftp.close()
        finally:
            self._client.close()


def _shell_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)
