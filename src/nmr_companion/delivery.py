"""Explicit local delivery of an immutable artifact, without replacing user files."""

import hashlib
import os
from pathlib import Path
import stat
import tempfile

from .errors import NmrError


def destination_path(value: str) -> Path:
    if "\x00" in value:
        raise NmrError("INVALID_PATH", "Destination contains a null character.")
    path = Path(value)
    if ".." in path.parts or (
        os.name == "nt"
        and (":" in path.name or path.is_reserved() or path.name.endswith((" ", ".")))
    ):
        raise NmrError("INVALID_PATH", "Destination contains an unsupported path component.")
    if not path.is_absolute() or path.suffix.lower() != ".zip":
        raise NmrError("INVALID_PATH", "Destination must be an absolute path ending in .zip.")
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise NmrError("INVALID_PATH", "Destination path cannot be inspected.") from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise NmrError("INVALID_PATH", "Destination must not use symlinks or reparse points.")
    if not path.parent.is_dir():
        raise NmrError("INVALID_PATH", "Destination parent directory must already exist.")
    if path.exists():
        raise NmrError("FILE_EXISTS", "Destination already exists; it was not changed.")
    return path


def export_file(service, revision: int, destination: str):
    path = destination_path(destination)
    artifact = service.export(revision)
    _, data = service.store.artifact(artifact.id)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".nmr-export-", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # Recheck before publishing, and use no-replace publication on either platform.
        destination_path(str(path))
        if os.name == "nt":
            temporary.rename(path)
        else:
            os.link(temporary, path)
            temporary.unlink()
        temporary = None
        if (
            path.stat().st_size != artifact.size
            or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256
        ):
            raise NmrError(
                "FILE_INTEGRITY", "Saved export changed; reconcile the destination before retrying."
            )
        return artifact, path
    except FileExistsError as exc:
        raise NmrError(
            "FILE_EXISTS", "Destination appeared during export; it was not replaced."
        ) from exc
    except OSError as exc:
        raise NmrError(
            "FILE_WRITE", "Export delivery failed; inspect the destination before retrying."
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
