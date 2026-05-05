"""SQLite index layer — fast fuzzy SN search across millions of envelopes.

Each envelope (one laptop test report) gets a row in `envelopes` plus one
row in `envelope_sns` for every searchable SN (system SN + every storage
device SN). LIKE '%q%' against the smaller `envelope_sns.sn` column
returns matching envelope_ids quickly; full payloads are then loaded
from the original history JSON files by `history_path`.

Source of truth stays the filesystem — the DB is a rebuildable index.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Iterable, Optional

import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS envelopes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    module          TEXT NOT NULL,
    sn              TEXT NOT NULL,
    hostname        TEXT,
    overall_result  TEXT,
    summary         TEXT,
    timestamp       TEXT NOT NULL,
    history_path    TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_envelopes_module_ts ON envelopes(module, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_envelopes_sn        ON envelopes(sn);

CREATE TABLE IF NOT EXISTS envelope_sns (
    envelope_id INTEGER NOT NULL,
    sn          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    PRIMARY KEY (envelope_id, sn, kind),
    FOREIGN KEY (envelope_id) REFERENCES envelopes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_envelope_sns_sn ON envelope_sns(sn);
"""

_lock = threading.Lock()


def _open() -> sqlite3.Connection:
    config.INDEX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.INDEX_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema() -> None:
    with _lock:
        conn = _open()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def count() -> int:
    conn = _open()
    try:
        return conn.execute("SELECT COUNT(*) FROM envelopes").fetchone()[0]
    finally:
        conn.close()


def upsert(module: str, envelope: dict, sns: Iterable[dict], history_path: str) -> int:
    """Insert or update an envelope index row + its searchable SN list.

    `sns` is an iterable of {"sn": str, "kind": str}. Duplicates and empty
    SNs are filtered.
    """
    with _lock:
        conn = _open()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO envelopes
                        (module, sn, hostname, overall_result, summary, timestamp, history_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(history_path) DO UPDATE SET
                        module=excluded.module,
                        sn=excluded.sn,
                        hostname=excluded.hostname,
                        overall_result=excluded.overall_result,
                        summary=excluded.summary,
                        timestamp=excluded.timestamp
                    """,
                    (
                        module,
                        envelope.get("sn", ""),
                        envelope.get("hostname", ""),
                        envelope.get("overall_result", ""),
                        envelope.get("summary", ""),
                        envelope.get("timestamp", ""),
                        history_path,
                    ),
                )
                envelope_id = conn.execute(
                    "SELECT id FROM envelopes WHERE history_path = ?",
                    (history_path,),
                ).fetchone()[0]

                conn.execute(
                    "DELETE FROM envelope_sns WHERE envelope_id = ?", (envelope_id,)
                )
                seen: set[tuple[str, str]] = set()
                rows = []
                for s in sns:
                    val = (s.get("sn") or "").strip()
                    kind = (s.get("kind") or "system").strip()
                    if not val:
                        continue
                    key = (val, kind)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append((envelope_id, val, kind))
                if rows:
                    conn.executemany(
                        "INSERT OR IGNORE INTO envelope_sns (envelope_id, sn, kind) VALUES (?, ?, ?)",
                        rows,
                    )
                return envelope_id
        finally:
            conn.close()


def delete_by_history_path(history_path: str) -> None:
    """Remove an envelope row (and its envelope_sns rows via cascade)
    matching this history_path. No-op if not present."""
    conn = _open()
    try:
        with conn:
            conn.execute("DELETE FROM envelopes WHERE history_path = ?", (history_path,))
    finally:
        conn.close()


def search(query: str, module: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Fuzzy substring search. Returns full envelope dicts, newest first.

    Matches any indexed SN (system or storage). Duplicate envelopes
    (e.g. an envelope whose system SN + a storage SN both match) are
    deduped via DISTINCT.
    """
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"

    sql = """
        SELECT DISTINCT e.id, e.history_path
        FROM envelopes e
        JOIN envelope_sns s ON s.envelope_id = e.id
        WHERE s.sn LIKE ?
    """
    params: list = [like]
    if module:
        sql += " AND e.module = ?"
        params.append(module)
    sql += " ORDER BY e.timestamp DESC LIMIT ?"
    params.append(limit)

    conn = _open()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for row in rows:
        p = Path(row["history_path"])
        if not p.exists():
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def rebuild_all(extract_sns_fn: Optional[Callable[[str, dict], list[dict]]] = None) -> int:
    """Wipe the index and rebuild it from every history/*.json on disk.

    `extract_sns_fn(module_name, envelope) -> list[{sn, kind}]` supplies
    the searchable SN list for each envelope. If None, only the system
    SN (envelope["sn"]) is indexed.
    """
    with _lock:
        conn = _open()
        try:
            conn.executescript("DELETE FROM envelope_sns; DELETE FROM envelopes;")
            conn.commit()
        finally:
            conn.close()

    if not config.BASE_DIR.exists():
        return 0

    n = 0
    for module_dir in sorted(config.BASE_DIR.iterdir()):
        if not module_dir.is_dir():
            continue
        history = module_dir / "history"
        if not history.exists():
            continue
        module_name = module_dir.name
        for p in history.rglob("*.json"):
            try:
                env = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if extract_sns_fn is not None:
                try:
                    sns = extract_sns_fn(module_name, env)
                except Exception:
                    sns = [{"sn": env.get("sn", ""), "kind": "system"}]
            else:
                sns = [{"sn": env.get("sn", ""), "kind": "system"}]
            upsert(module_name, env, sns, str(p))
            n += 1
    return n
