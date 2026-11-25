"""Persistencia SQLite. Minimización: NO se guarda el texto de entrada ni las imágenes, solo el expediente resultante.

El propietario es un identificador de sesión anónimo almacenado solo como hash (aislamiento entre usuarios).
Esquema compatible con la migración futura a PostgreSQL (docs/02-esquema-bd.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
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
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'free', is_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  key_hash TEXT UNIQUE NOT NULL, prefix TEXT NOT NULL, label TEXT, created_at TEXT NOT NULL, revoked_at TEXT, last_used_at TEXT);
CREATE TABLE IF NOT EXISTS usage(
  owner_hash TEXT NOT NULL, month TEXT NOT NULL, total INTEGER NOT NULL DEFAULT 0, images INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(owner_hash, month));
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, owner_hash TEXT, action TEXT NOT NULL, target TEXT);
"""


def hash_owner(owner: str) -> str:
    return hashlib.sha256(("fg-owner:" + owner).encode()).hexdigest()


def hash_token(tok: str) -> str:
    return hashlib.sha256(("fg-token:" + tok).encode()).hexdigest()


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

    # ------------------------------------------------------------ usuarios
    def create_user(self, email: str, pw_hash: str, is_admin: bool = False) -> int | None:
        try:
            cur = self._x("INSERT INTO users(email,pw_hash,is_admin,created_at) VALUES(?,?,?,?)",
                          (email, pw_hash, int(is_admin), now_utc().isoformat()))
        except sqlite3.IntegrityError:
            return None
        return cur.lastrowid

    def user_by_email(self, email: str) -> dict | None:
        r = self._x("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(r) if r else None

    def user_by_id(self, uid: int) -> dict | None:
        r = self._x("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None

    def list_users(self, limit: int = 200) -> list[dict]:
        rows = self._x("SELECT id,email,plan,is_admin,disabled,created_at FROM users ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def set_plan(self, uid: int, plan: str) -> bool:
        return bool(self._x("UPDATE users SET plan=? WHERE id=?", (plan, uid)).rowcount)

    def set_disabled(self, uid: int, disabled: bool) -> bool:
        n = self._x("UPDATE users SET disabled=? WHERE id=?", (int(disabled), uid)).rowcount
        if disabled:
            self._x("DELETE FROM sessions WHERE user_id=?", (uid,))
        return bool(n)

    def create_session(self, uid: int, days: int = 30) -> str:
        tok = secrets.token_urlsafe(32)
        self._x("INSERT INTO sessions VALUES(?,?,?,?)", (hash_token(tok), uid, now_utc().isoformat(),
                                                         (now_utc() + timedelta(days=days)).isoformat()))
        return tok

    def user_for_session(self, tok: str) -> dict | None:
        r = self._x("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0",
                    (hash_token(tok), now_utc().isoformat())).fetchone()
        return dict(r) if r else None

    def delete_session(self, tok: str) -> None:
        self._x("DELETE FROM sessions WHERE token_hash=?", (hash_token(tok),))

    def claim_anonymous(self, anon_owner: str, user_owner: str) -> int:
        """Traslada el historial anónimo a la cuenta recién autenticada."""
        return self._x("UPDATE analyses SET owner_hash=? WHERE owner_hash=?",
                       (hash_owner(user_owner), hash_owner(anon_owner))).rowcount

    # ------------------------------------------------------------ claves de API
    def create_api_key(self, uid: int, label: str) -> tuple[int, str]:
        key = "fg_" + secrets.token_urlsafe(32)
        cur = self._x("INSERT INTO api_keys(user_id,key_hash,prefix,label,created_at) VALUES(?,?,?,?,?)",
                      (uid, hash_token(key), key[:9], label[:60], now_utc().isoformat()))
        return cur.lastrowid, key

    def user_for_api_key(self, key: str) -> tuple[dict, int] | None:
        r = self._x("SELECT u.*, k.id AS key_id FROM api_keys k JOIN users u ON u.id=k.user_id "
                    "WHERE k.key_hash=? AND k.revoked_at IS NULL AND u.disabled=0", (hash_token(key),)).fetchone()
        if not r:
            return None
        d = dict(r)
        kid = d.pop("key_id")
        self._x("UPDATE api_keys SET last_used_at=? WHERE id=?", (now_utc().isoformat(), kid))
        return d, kid

    def list_api_keys(self, uid: int) -> list[dict]:
        rows = self._x("SELECT id,prefix,label,created_at,last_used_at FROM api_keys WHERE user_id=? AND revoked_at IS NULL ORDER BY id DESC", (uid,)).fetchall()
        return [dict(r) for r in rows]

    def revoke_api_key(self, uid: int, kid: int) -> bool:
        return bool(self._x("UPDATE api_keys SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
                            (now_utc().isoformat(), kid, uid)).rowcount)

    # ------------------------------------------------------------ cuotas y estadísticas
    @staticmethod
    def month() -> str:
        return now_utc().strftime("%Y-%m")

    def usage(self, owner: str) -> dict:
        r = self._x("SELECT total,images FROM usage WHERE owner_hash=? AND month=?", (hash_owner(owner), self.month())).fetchone()
        return {"total": r["total"], "images": r["images"]} if r else {"total": 0, "images": 0}

    def add_usage(self, owner: str, image: bool) -> None:
        self._x("INSERT INTO usage(owner_hash,month,total,images) VALUES(?,?,1,?) "
                "ON CONFLICT(owner_hash,month) DO UPDATE SET total=total+1, images=images+?",
                (hash_owner(owner), self.month(), int(image), int(image)))

    def stats(self) -> dict:
        q = lambda sql, a=(): [dict(r) for r in self._x(sql, a).fetchall()]
        m = self.month()
        return {
            "users": q("SELECT plan, COUNT(*) n FROM users GROUP BY plan"),
            "analyses_total": q("SELECT COUNT(*) n FROM analyses")[0]["n"],
            "analyses_by_kind": q("SELECT kind, COUNT(*) n FROM analyses GROUP BY kind"),
            "analyses_by_band": q("SELECT band, COUNT(*) n FROM analyses GROUP BY band"),
            "usage_month": q("SELECT COALESCE(SUM(total),0) total, COALESCE(SUM(images),0) images FROM usage WHERE month=?", (m,))[0],
            "active_keys": q("SELECT COUNT(*) n FROM api_keys WHERE revoked_at IS NULL")[0]["n"],
        }
