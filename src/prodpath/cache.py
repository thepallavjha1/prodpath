import sqlite3
from pathlib import Path

# Scan cache: skip re-reading files whose (mtime_ns, size) did not change.
# file_facts is keyed by extractor_version; bump EXTRACTOR_VERSION in extract.py on changes.


class HashCache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS file_hashes ("
            "path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER, hash TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, response TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS file_facts ("
            "path TEXT, hash TEXT, extractor_version TEXT, facts_json TEXT, "
            "PRIMARY KEY (path, hash, extractor_version))"
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

    def get_facts(self, path: str, digest: str, version: str) -> str | None:
        row = self._db.execute(
            "SELECT facts_json FROM file_facts WHERE path=? AND hash=? AND extractor_version=?",
            (path, digest, version),
        ).fetchone()
        return None if row is None else str(row[0])

    def put_facts(self, path: str, digest: str, version: str, facts_json: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO file_facts VALUES (?, ?, ?, ?)",
            (path, digest, version, facts_json),
        )

    def get_llm(self, key: str) -> str | None:
        row = self._db.execute("SELECT response FROM llm_cache WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def put_llm(self, key: str, response: str) -> None:
        self._db.execute("INSERT OR REPLACE INTO llm_cache VALUES (?, ?)", (key, response))

    def close(self) -> None:
        self._db.commit()
        self._db.close()
