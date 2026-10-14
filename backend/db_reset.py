"""Restore the working database from the original, safely.

The paths come from server configuration, never from an API request. The
original is only ever opened for reading. The copy is written to a temporary
file next to the working database, verified (byte hash and SQLite integrity
check), and only then swapped in with an atomic os.replace. If anything fails,
the working database is left exactly as it was.
"""

import hashlib
import os
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

EXPECTED_TABLES = {"desk", "tickets", "inventory", "pricing", "vendors", "invoices", "leases", "cash_accounts", "payments"}


class ResetError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_sqlite(path: Path) -> None:
    try:
        with closing(sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)) as con:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ResetError("integrity check failed on the reset copy")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    except sqlite3.DatabaseError as exc:
        raise ResetError("original database is not a valid SQLite database") from exc
    missing = EXPECTED_TABLES - tables
    if missing:
        raise ResetError(f"original database is missing tables: {sorted(missing)}")


def reset_working_db(original: Path, working: Path) -> str:
    """Copy `original` over `working` atomically. Returns the new working hash."""
    original, working = Path(original).resolve(), Path(working).resolve()
    if original == working:
        raise ResetError("original and working database paths are the same file")
    if not original.is_file():
        raise ResetError("original database not found")
    if not working.parent.is_dir():
        raise ResetError("working database folder not found")

    original_hash = sha256(original)
    tmp = working.with_name(working.name + ".reset-tmp")
    try:
        shutil.copyfile(original, tmp)
        if sha256(tmp) != original_hash:
            raise ResetError("copy does not match the original")
        _check_sqlite(tmp)
        for attempt in range(5):  # Windows: a reader may briefly hold the file
            try:
                os.replace(tmp, working)
                break
            except PermissionError:
                if attempt == 4:
                    raise ResetError("working database is in use; try again when no run is active")
                time.sleep(0.2)
    finally:
        if tmp.exists():
            tmp.unlink()
    if sha256(original) != original_hash:
        raise ResetError("original database changed during reset")  # should be impossible
    new_hash = sha256(working)
    if new_hash != original_hash:
        raise ResetError("working database does not match the original after reset")
    return new_hash
