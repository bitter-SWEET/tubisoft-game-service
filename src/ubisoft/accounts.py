"""SQLite account persistence; no plaintext passwords, emails, or client IPs."""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path


@contextmanager
def _connection(path: Path):
    with closing(sqlite3.connect(path, timeout=10)) as db:
        with db:
            yield db


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(descriptor)
    os.chmod(path, 0o600)
    with _connection(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise ValueError("account database schema is newer than this server")
        db.execute("CREATE TABLE IF NOT EXISTS accounts (name_key TEXT PRIMARY KEY, name TEXT NOT NULL, salt BLOB NOT NULL, password_hash BLOB NOT NULL)")
        columns = {row[1] for row in db.execute("PRAGMA table_info(accounts)")}
        if "created_at" not in columns:
            db.execute("ALTER TABLE accounts ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0")
        if "last_login_at" not in columns:
            db.execute("ALTER TABLE accounts ADD COLUMN last_login_at INTEGER")
        db.execute("PRAGMA user_version=1")


def _valid(username: str, password: str, *, creating: bool = False) -> bool:
    if not username or not password or len(username) > (16 if creating else 128) or len(password) > 256:
        return False
    try:
        username.encode("utf-8")
        password.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return not any(ord(char) < 32 or ord(char) == 127 for char in username + password)


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)


def create_account(path: Path, username: str, password: str) -> bool:
    """Atomically create a case-insensitive name, retaining the display spelling."""
    if not _valid(username, password, creating=True):
        raise ValueError("invalid account fields")
    initialize_database(path)
    salt = secrets.token_bytes(16)
    password_hash = _hash(password, salt)
    with _connection(path) as db:
        try:
            db.execute("INSERT INTO accounts (name_key, name, salt, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                       (username.casefold(), username, salt, password_hash, int(time.time())))
        except sqlite3.IntegrityError:
            return False
    return True


def verify_account(path: Path, username: str, password: str) -> bool:
    if not _valid(username, password):
        return False
    initialize_database(path)
    with _connection(path) as db:
        row = db.execute("SELECT salt, password_hash FROM accounts WHERE name_key = ?", (username.casefold(),)).fetchone()
    candidate = _hash(password, row[0] if row else bytes(16))
    if row is None or not hmac.compare_digest(candidate, row[1]):
        return False
    with _connection(path) as db:
        db.execute("UPDATE accounts SET last_login_at = ? WHERE name_key = ?", (int(time.time()), username.casefold()))
    return True


def backup_database(path: Path, destination: Path) -> None:
    """Snapshot committed SQLite state, including WAL, without copying live files."""
    if path.resolve() == destination.resolve() or destination.exists():
        raise ValueError("backup destination must be a new, separate file")
    if not path.is_file():
        raise ValueError("account database does not exist")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup integrity check failed")
