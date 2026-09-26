from __future__ import annotations
from contextlib import contextmanager, closing
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from .errors import NmrError
from .models import Artifact, Project, Receipt

SCHEMA = 2


def canonical_json(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def identifier(prefix: str) -> str:
    return prefix + "_" + uuid4().hex[:16]


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if self.path.exists() and not self.path.is_file():
            raise NmrError("PROJECT_PATH", "Project path must be a file.")

    @contextmanager
    def connection(self, *, create=False):
        if not create and not self.path.exists():
            raise NmrError("NO_PROJECT", "Create or open a project first.")
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            if not create:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (1, SCHEMA):
                    raise NmrError(
                        "SCHEMA_VERSION", "Unsupported project format; preserve the file."
                    )
            yield connection
        except sqlite3.DatabaseError as exc:
            raise NmrError(
                "STORAGE_ERROR", "Project storage failed; reopen and check the request ID."
            ) from exc
        finally:
            if connection is not None:
                connection.close()

    def create(self, name: str) -> Project:
        project = Project(id=identifier("project"), name=name, revision=0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create prevents accidental replacement, including an empty user file.
        try:
            with self.path.open("xb"):
                pass
        except FileExistsError as exc:
            raise NmrError(
                "PROJECT_EXISTS", "Project already exists. Open it without creating."
            ) from exc
        with self.connection(create=True) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            for statement in (
                "CREATE TABLE snapshots(revision INTEGER PRIMARY KEY, payload TEXT NOT NULL)",
                "CREATE TABLE requests(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, receipt TEXT NOT NULL)",
                "CREATE TABLE originals(sha256 TEXT PRIMARY KEY, data BLOB NOT NULL)",
                "CREATE TABLE artifacts(id TEXT PRIMARY KEY, metadata TEXT NOT NULL, data BLOB NOT NULL)",
            ):
                db.execute(statement)
            db.execute("INSERT INTO snapshots VALUES(?,?)", (0, project.model_dump_json()))
            db.execute(f"PRAGMA user_version={SCHEMA}")
            db.commit()
            return project

    @staticmethod
    def read_from(db, revision=None) -> Project:
        if revision is None:
            row = db.execute(
                "SELECT payload FROM snapshots ORDER BY revision DESC LIMIT 1"
            ).fetchone()
        else:
            row = db.execute(
                "SELECT payload FROM snapshots WHERE revision=?", (revision,)
            ).fetchone()
        if row is None:
            raise NmrError("NOT_FOUND", "Project revision does not exist.")
        return Project.model_validate_json(row[0])

    def read(self, revision=None) -> Project:
        with self.connection() as db:
            return self.read_from(db, revision)

    def request(self, request_id: str) -> Receipt:
        with self.connection() as db:
            row = db.execute("SELECT receipt FROM requests WHERE id=?", (request_id,)).fetchone()
            if row is None:
                raise NmrError("NOT_FOUND", "No committed operation has this request ID.")
            return Receipt.model_validate_json(row[0])

    def mutate(self, expected_revision: int, request_id: str, command: dict, callback) -> Receipt:
        fingerprint = hashlib.sha256(
            canonical_json({"expected_revision": expected_revision, "command": command}).encode()
        ).hexdigest()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT fingerprint,receipt FROM requests WHERE id=?", (request_id,)
            ).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise NmrError(
                        "REQUEST_ID_REUSED", "Request ID was used for a different command."
                    )
                receipt = Receipt.model_validate_json(row[1])
                receipt.replayed = True
                return receipt
            current = self.read_from(db)
            if current.revision != expected_revision:
                raise NmrError(
                    "REVISION_CONFLICT",
                    "Refresh the project before editing.",
                    current_revision=current.revision,
                )
            with self._migration_backup(db) as backup:
                if command["op"] == "undo":
                    target = command["target_revision"]
                    if target >= current.revision:
                        raise NmrError(
                            "INVALID_UNDO", "Undo target must precede the current revision."
                        )
                    project = self.read_from(db, target)
                    ids, warnings = [], ["A prior state was restored as a new revision."]
                else:
                    project = current.model_copy(deep=True)
                    ids, warnings = callback(project, db)
                project.schema_version = SCHEMA
                project.revision = current.revision + 1
                # Validate the complete state before any commit, including callback results.
                project = Project.model_validate(project.model_dump())
                payload = project.model_dump_json()
                if len(payload.encode()) > 128 * 1024 * 1024:
                    raise NmrError("PROJECT_LIMIT", "Snapshot exceeds the alpha 128 MiB limit.")
                if backup is not None:
                    final_backup = backup.with_suffix("")
                    backup.rename(final_backup)
                    warnings = ["Schema 1 rollback backup: " + final_backup.name, *warnings]
                receipt = Receipt(
                    request_id=request_id,
                    operation=command["op"],
                    project_id=project.id,
                    revision=project.revision,
                    object_ids=ids,
                    warnings=warnings,
                )
                db.execute(f"PRAGMA user_version={SCHEMA}")
                db.execute("INSERT INTO snapshots VALUES(?,?)", (project.revision, payload))
                db.execute(
                    "INSERT INTO requests VALUES(?,?,?)",
                    (request_id, fingerprint, receipt.model_dump_json()),
                )
                db.commit()
                return receipt

    @contextmanager
    def _migration_backup(self, db):
        # Create before callbacks can acquire write locks in rollback-journal projects.
        # Publish the validated backup only when the new state passes validation.
        backup = self._backup_v1() if db.execute("PRAGMA user_version").fetchone()[0] == 1 else None
        try:
            yield backup
        finally:
            if backup is not None:
                backup.unlink(missing_ok=True)  # Only this call's unpublished .partial file.

    def _backup_v1(self):
        """Called under BEGIN IMMEDIATE: no writer can change the committed source."""
        backup = self.path.with_name(
            self.path.name + ".schema1-" + uuid4().hex[:12] + ".backup.partial"
        )
        with backup.open("xb"):
            pass
        try:
            # A separate reader sees the committed state, excluding the new mutation.
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(backup)) as target:
                    source.backup(target)
                    target.execute("PRAGMA journal_mode=DELETE")
                    if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise NmrError(
                            "BACKUP_INTEGRITY", "Project upgrade backup failed validation."
                        )
            return backup
        except Exception:
            backup.unlink(missing_ok=True)
            raise

    @staticmethod
    def preserve_original(db, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        db.execute("INSERT OR IGNORE INTO originals VALUES(?,?)", (digest, data))
        return digest

    def artifact(self, artifact_id: str) -> tuple[Artifact, bytes]:
        with self.connection() as db:
            row = db.execute(
                "SELECT metadata,data FROM artifacts WHERE id=?", (artifact_id,)
            ).fetchone()
            if row is None:
                raise NmrError("NOT_FOUND", "Artifact does not exist.")
            metadata = Artifact.model_validate_json(row[0])
            if hashlib.sha256(row[1]).hexdigest() != metadata.sha256:
                raise NmrError("ARTIFACT_INTEGRITY", "Artifact hash does not match.")
            return metadata, row[1]
