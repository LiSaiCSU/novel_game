from __future__ import annotations

from database.session import prepare_database_path


def test_file_backed_sqlite_parent_is_created_before_first_connection(tmp_path) -> None:
    database_file = tmp_path / "new-data-directory" / "game.db"

    prepare_database_path(f"sqlite+aiosqlite:///{database_file.as_posix()}")

    assert database_file.parent.is_dir()
    assert not database_file.exists()


def test_non_file_database_urls_do_not_create_directories(tmp_path) -> None:
    prepare_database_path("sqlite+aiosqlite:///:memory:")
    prepare_database_path("postgresql+asyncpg://user:pass@localhost/game")

    assert list(tmp_path.iterdir()) == []
