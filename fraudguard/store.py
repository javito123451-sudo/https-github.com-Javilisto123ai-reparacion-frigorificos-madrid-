"""Persistencia SQLite. Minimización: NO se guarda el texto de entrada ni las imágenes, solo el expediente resultante.

El propietario es un identificador de sesión anónimo almacenado solo como hash (aislamiento entre usuarios).
Esquema compatible con la migración futura a PostgreSQL (docs/02-esquema-bd.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses(
  id TEXT PRIMARY KEY, owner_hash TEXT NOT NULL, kind TEXT NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  score INTEGER, band TEXT NOT NULL, verdict TEXT NOT NULL, confidence REAL NOT NULL,
  summary TEXT, result_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_an_owner ON analyses(owner_hash, created_at DESC);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, owner_hash TEXT, action TEXT NOT NULL, target TEXT);
"""


def hash_owner(owner: str) -> str:
    return hashlib.sha256(("fg-owner:" + owner).encode()).hexdigest()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)

    def _x(self, sql, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    def audit(self, owner: str | None, action: str, target: str | None = None):
        self._x("INSERT INTO audit_log(at,owner_hash,action,target) VALUES(?,?,?,?)",
                (now_utc().isoformat(), hash_owner(owner) if owner else None, action, target))

    def save(self, owner: str, result: dict, retention_days: int) -> None:
        a = result["assessment"]
        self._x("INSERT INTO analyses VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (result["id"], hash_owner(owner), result["kind"], result["created_at"],
                 (now_utc() + timedelta(days=retention_days)).isoformat(),
                 a["score"], a["band"], a["verdict"], a["confidence"], result.get("summary", ""),
                 json.dumps(result, ensure_ascii=False)))
        self.audit(owner, "analysis.create", result["id"])

    def get(self, owner: str, analysis_id: str) -> dict | None:
        r = self._x("SELECT result_json FROM analyses WHERE id=? AND owner_hash=? AND expires_at>?",
                    (analysis_id, hash_owner(owner), now_utc().isoformat())).fetchone()
        return json.loads(r["result_json"]) if r else None

    def list(self, owner: str, limit: int = 50) -> list[dict]:
        rows = self._x("SELECT id,kind,created_at,score,band,verdict,confidence,summary FROM analyses "
                       "WHERE owner_hash=? AND expires_at>? ORDER BY created_at DESC LIMIT ?",
                       (hash_owner(owner), now_utc().isoformat(), limit)).fetchall()
        return [dict(r) for r in rows]

    def delete(self, owner: str, analysis_id: str) -> bool:
        n = self._x("DELETE FROM analyses WHERE id=? AND owner_hash=?", (analysis_id, hash_owner(owner))).rowcount
        if n:
            self.audit(owner, "analysis.delete", analysis_id)
        return bool(n)

    def delete_all(self, owner: str) -> int:
        n = self._x("DELETE FROM analyses WHERE owner_hash=?", (hash_owner(owner),)).rowcount
        self.audit(owner, "analysis.delete_all", str(n))
        return n

    def purge_expired(self) -> int:
        return self._x("DELETE FROM analyses WHERE expires_at<=?", (now_utc().isoformat(),)).rowcount
