import pytest

import src.db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Keep test runs out of the real dashboard database (guardian_log.db)."""
    monkeypatch.setattr(src.db, "DB_PATH", tmp_path / "test_log.db")
    src.db.init_db()
