import sqlite3
from pathlib import Path

# Scan cache: skip re-reading files whose (mtime_ns, size) did not change.
# Bump nothing here when extractors change; extractor_version joins the key in phase 2.


class HashCache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS file_hashes ("
            "path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER, hash TEXT)"
        )

    def get(self, path: str, mtime_ns: int, size: int) -> str | None:
        row = self._db.execute(
            "SELECT hash FROM file_hashes WHERE path=? AND mtime_ns=? AND size=?",
            (path, mtime_ns, size),
        ).fetchone()
        return None if row is None else str(row[0])

    def put(self, path: str, mtime_ns: int, size: int, digest: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO file_hashes VALUES (?, ?, ?, ?)",
            (path, mtime_ns, size, digest),
        )

    def close(self) -> None:
        self._db.commit()
        self._db.close()
