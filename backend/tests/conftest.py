"""Shared fixtures. Tests never touch data/campus_customs.db or output/audit_trail.json:
MCP tests run against a temporary copy of the working database, and agent
tests write audit events to a temporary file."""

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
WORKING_DB = ROOT / "data" / "campus_customs_new.db"
REAL_AUDIT = ROOT / "output" / "audit_trail.json"


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="session", autouse=True)
def protected_files_unchanged():
    """Fail the session if any test changes the real databases or audit trail."""
    before = {p: sha256(p) for p in (ORIGINAL_DB, WORKING_DB, REAL_AUDIT)}
    yield
    after = {p: sha256(p) for p in (ORIGINAL_DB, WORKING_DB, REAL_AUDIT)}
    assert before == after, "a test modified a protected file"


@pytest.fixture
def iso_db(tmp_path) -> Path:
    """An isolated copy of the working database for this test only."""
    path = tmp_path / "campus_customs_test.db"
    shutil.copyfile(WORKING_DB, path)
    return path


@pytest.fixture
def audit_path(tmp_path) -> Path:
    return tmp_path / "audit_trail.json"
