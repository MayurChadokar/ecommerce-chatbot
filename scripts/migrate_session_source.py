"""Add sessions.source to an existing SQLite database, preserving old records.

Usage: python scripts/migrate_session_source.py [--db /path/to/lotus_app.db]
Uses only Python's standard library. Does not import the chatbot or AI models.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


DEFAULT_DB = Path(__file__).resolve().parents[1] / "lotus_app.db"


def migrate(database):
    database = Path(database).resolve()
    # mode=rw prevents silently creating a new database at a mistyped path.
    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True,
                                 timeout=30)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if not columns:
            raise ValueError("sessions table not found; check the database path")
        if "source" in columns:
            print("Already migrated: sessions.source exists. No changes made.")
            return False

        backup_dir = database.parent / "logs" / "db-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"{database.stem}-before-source-{stamp}.db"
        with closing(sqlite3.connect(backup_path)) as backup:
            conn.backup(backup)
            if backup.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("Backup verification failed; migration not started")
        backup_path.chmod(0o600)
        print(f"Backup: {backup_path}")

        with conn:
            conn.execute("BEGIN IMMEDIATE")
            # Recheck under the write lock in case another worker migrated first.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "source" in columns:
                print("Already migrated by another process. No changes made.")
                return False
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown'"
            )
        print("Migration complete: sessions.source added. Existing sessions are Unknown.")
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    try:
        migrate(args.db)
    except (sqlite3.Error, OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Migration failed: {error}\n")


if __name__ == "__main__":
    main()
