"""Create consistent SQLite snapshots without stopping the chatbot.

Also works on Windows for transferring existing local records to a new server.
The output contains customer records: keep it private and outside Git.
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3


def backup_records(app_dir, output_dir):
    sources = [app_dir / "lotus_app.db", app_dir / "tools" / "lotus_stores.db"]
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Database not found: {source}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot_dir = output_dir / stamp
    # Windows must inherit the workspace ACL; mode 0700 can exclude a sandboxed
    # process from the directory it just created. POSIX uses private permissions.
    snapshot_dir.mkdir(parents=True, mode=0o777 if os.name == "nt" else 0o700, exist_ok=False)
    for source in sources:
        destination = snapshot_dir / source.name
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(destination)) as snapshot:
                original.backup(snapshot)
                result = snapshot.execute("PRAGMA quick_check").fetchall()
                if result != [("ok",)]:
                    raise RuntimeError(f"Backup verification failed: {source.name}")
        destination.chmod(0o600)
        print(f"Verified backup: {destination}")
    return snapshot_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    backup_records(args.app_dir.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
