from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS probes (
  ts          INTEGER NOT NULL,
  target      TEXT    NOT NULL,
  address     TEXT    NOT NULL,
  ok          INTEGER NOT NULL,
  latency_ms  REAL,
  method      TEXT    NOT NULL,
  error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_probes_ts ON probes(ts);
CREATE INDEX IF NOT EXISTS idx_probes_target_ts ON probes(target, ts);
"""


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.commit()


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def insert_probes(db_path: Path, rows: list[tuple]) -> None:
    """rows: list of (ts, target, address, ok, latency_ms, method, error)"""
    if not rows:
        return
    with connect(db_path) as conn:
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT INTO probes (ts, target, address, ok, latency_ms, method, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute("COMMIT")


def fetch_since(db_path: Path, since_ts: int) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT ts, target, address, ok, latency_ms, method, error "
            "FROM probes WHERE ts >= ? ORDER BY ts",
            (since_ts,),
        ).fetchall()


def fetch_latest_per_target(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT p.ts, p.target, p.address, p.ok, p.latency_ms, p.method, p.error "
            "FROM probes p "
            "JOIN (SELECT target, MAX(ts) AS mx FROM probes GROUP BY target) m "
            "  ON p.target = m.target AND p.ts = m.mx"
        ).fetchall()


def fetch_older_than(db_path: Path, cutoff_ts: int) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT ts, target, address, ok, latency_ms, method, error "
            "FROM probes WHERE ts < ? ORDER BY ts",
            (cutoff_ts,),
        ).fetchall()


def delete_older_than(db_path: Path, cutoff_ts: int) -> int:
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM probes WHERE ts < ?", (cutoff_ts,))
        conn.execute("VACUUM")
        return cur.rowcount
