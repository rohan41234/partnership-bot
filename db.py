"""
SQLite storage for the Partnership bot.

Settings now live in config.toml — this file only stores DATA:
  points          current week's scores (wiped by the weekly reset)
  lifetime        all-time totals (never wiped)
  weeks           one row per completed week
  weekly_archive  frozen standings for each completed week
  partnerships    every submission
  points_log      audit trail of every point change
  state           small runtime values (live board message id, reset clock)

Back it up by copying  data/partnership.db.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Iterable, Optional

DB_PATH = os.getenv("DB_PATH", "data/partnership.db")

_conn: Optional[sqlite3.Connection] = None
_lock = threading.RLock()


SCHEMA = """
CREATE TABLE IF NOT EXISTS partnerships (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id          INTEGER NOT NULL,
    dedupe_key        TEXT    NOT NULL,
    invite_code       TEXT,
    target_guild_id   INTEGER,
    target_name       TEXT,
    source_channel_id INTEGER,
    source_message_id INTEGER,
    thread_id         INTEGER,
    control_msg_id    INTEGER,
    poster_id         INTEGER NOT NULL,
    approver_id       INTEGER,
    proof_msg_id      INTEGER,
    proof_url         TEXT,
    status            TEXT    NOT NULL DEFAULT 'pending',
    reason            TEXT,
    created_at        INTEGER NOT NULL,
    resolved_at       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pship_dedupe ON partnerships (guild_id, dedupe_key, status);
CREATE INDEX IF NOT EXISTS idx_pship_thread ON partnerships (thread_id);
CREATE INDEX IF NOT EXISTS idx_pship_status ON partnerships (guild_id, status);

CREATE TABLE IF NOT EXISTS points (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    points       INTEGER NOT NULL DEFAULT 0,
    partnerships INTEGER NOT NULL DEFAULT 0,
    approvals    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_points_lb ON points (guild_id, points DESC);

CREATE TABLE IF NOT EXISTS lifetime (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    points       INTEGER NOT NULL DEFAULT 0,
    partnerships INTEGER NOT NULL DEFAULT 0,
    approvals    INTEGER NOT NULL DEFAULT 0,
    weeks_won    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_lifetime_lb ON lifetime (guild_id, points DESC);

CREATE TABLE IF NOT EXISTS points_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    delta      INTEGER NOT NULL,
    reason     TEXT,
    actor_id   INTEGER,
    pship_id   INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    guild_id INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    value    TEXT,
    PRIMARY KEY (guild_id, key)
);
"""


def connect() -> None:
    global _conn
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA synchronous=NORMAL")
    with _lock:
        _conn.executescript(SCHEMA)
        _conn.commit()


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.commit()
        _conn.close()
        _conn = None


def _q(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    assert _conn is not None, "db.connect() was never called"
    with _lock:
        cur = _conn.execute(sql, tuple(params))
        _conn.commit()
        return cur


def _one(sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    return _q(sql, params).fetchone()


def _all(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return _q(sql, params).fetchall()


def now() -> int:
    return int(time.time())


# --------------------------------------------------------------------------- #
#  Settings shim — everything comes from config.toml now
# --------------------------------------------------------------------------- #

def get_config(guild_id: int | None = None):
    """Kept so the rest of the bot can keep doing cfg['staff_role_id']."""
    import config

    return config.get()


def is_configured(cfg) -> bool:
    return bool(cfg["listen_channel_id"] and cfg["approver_role_id"])


# --------------------------------------------------------------------------- #
#  Runtime state
# --------------------------------------------------------------------------- #

def get_state(guild_id: int, key: str, default: Any = None) -> Any:
    row = _one("SELECT value FROM state WHERE guild_id = ? AND key = ?", (guild_id, key))
    return row["value"] if row and row["value"] is not None else default


def get_state_int(guild_id: int, key: str, default: int = 0) -> int:
    val = get_state(guild_id, key)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def set_state(guild_id: int, key: str, value: Any) -> None:
    _q(
        "INSERT INTO state (guild_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value",
        (guild_id, key, None if value is None else str(value)),
    )


def clear_state(guild_id: int, key: str) -> None:
    _q("DELETE FROM state WHERE guild_id = ? AND key = ?", (guild_id, key))


# --------------------------------------------------------------------------- #
#  Partnerships
# --------------------------------------------------------------------------- #

def find_open_partnership(guild_id: int, dedupe_key: str) -> Optional[sqlite3.Row]:
    return _one(
        "SELECT * FROM partnerships "
        "WHERE guild_id = ? AND dedupe_key = ? AND status IN ('pending','approved') "
        "ORDER BY id DESC LIMIT 1",
        (guild_id, dedupe_key),
    )


def create_partnership(**kw: Any) -> int:
    cur = _q(
        """
        INSERT INTO partnerships
            (guild_id, dedupe_key, invite_code, target_guild_id, target_name,
             source_channel_id, source_message_id, poster_id, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,'pending',?)
        """,
        (
            kw["guild_id"], kw["dedupe_key"], kw.get("invite_code"),
            kw.get("target_guild_id"), kw.get("target_name"),
            kw.get("source_channel_id"), kw.get("source_message_id"),
            kw["poster_id"], now(),
        ),
    )
    return int(cur.lastrowid)


def update_partnership(pship_id: int, **kwargs: Any) -> None:
    allowed = {
        "thread_id", "control_msg_id", "approver_id", "proof_msg_id",
        "proof_url", "status", "reason", "resolved_at", "target_name", "target_guild_id",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    _q(f"UPDATE partnerships SET {assignments} WHERE id = ?", (*fields.values(), pship_id))


def claim_partnership(
    pship_id: int,
    new_status: str,
    approver_id: int,
    reason: Optional[str] = None,
) -> bool:
    """
    Atomically move a partnership out of 'pending'.

    Returns True only for the caller that actually won the race. Two approvers
    hitting Approve at the same instant would otherwise both pass a
    read-then-write status check and award the points twice.
    """
    cur = _q(
        "UPDATE partnerships SET status = ?, approver_id = ?, reason = ?, resolved_at = ? "
        " WHERE id = ? AND status = 'pending'",
        (new_status, approver_id, reason, now(), pship_id),
    )
    return cur.rowcount == 1


def clear_proof(pship_id: int, proof_msg_id: int) -> bool:
    """Forget the proof if *that specific* message was the one deleted."""
    cur = _q(
        "UPDATE partnerships SET proof_msg_id = NULL, proof_url = NULL "
        " WHERE id = ? AND proof_msg_id = ? AND status = 'pending'",
        (pship_id, proof_msg_id),
    )
    return cur.rowcount == 1


def get_partnership_by_proof(proof_msg_id: int) -> Optional[sqlite3.Row]:
    return _one("SELECT * FROM partnerships WHERE proof_msg_id = ?", (proof_msg_id,))


def get_partnership(pship_id: int) -> Optional[sqlite3.Row]:
    return _one("SELECT * FROM partnerships WHERE id = ?", (pship_id,))


def get_partnership_by_thread(thread_id: int) -> Optional[sqlite3.Row]:
    return _one("SELECT * FROM partnerships WHERE thread_id = ?", (thread_id,))


def list_partnerships(guild_id: int, status: Optional[str] = None, limit: int = 25) -> list[sqlite3.Row]:
    if status:
        return _all(
            "SELECT * FROM partnerships WHERE guild_id = ? AND status = ? ORDER BY id DESC LIMIT ?",
            (guild_id, status, limit),
        )
    return _all("SELECT * FROM partnerships WHERE guild_id = ? ORDER BY id DESC LIMIT ?", (guild_id, limit))


def count_partnerships(guild_id: int, status: str) -> int:
    row = _one(
        "SELECT COUNT(*) AS c FROM partnerships WHERE guild_id = ? AND status = ?",
        (guild_id, status),
    )
    return int(row["c"]) if row else 0


def count_partnerships_since(guild_id: int, since: int) -> int:
    row = _one(
        "SELECT COUNT(*) AS c FROM partnerships "
        "WHERE guild_id = ? AND status = 'approved' AND resolved_at >= ?",
        (guild_id, since),
    )
    return int(row["c"]) if row else 0


# --------------------------------------------------------------------------- #
#  Points — weekly table + lifetime table, updated together
# --------------------------------------------------------------------------- #

def add_points(
    guild_id: int,
    user_id: int,
    delta: int,
    *,
    reason: str = "",
    actor_id: Optional[int] = None,
    pship_id: Optional[int] = None,
    partnerships: int = 0,
    approvals: int = 0,
    lifetime_too: bool = True,
) -> int:
    for table in ("points",) + (("lifetime",) if lifetime_too else ()):
        _q(f"INSERT OR IGNORE INTO {table} (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
        _q(
            f"UPDATE {table} SET points = points + ?, partnerships = partnerships + ?, "
            f"approvals = approvals + ? WHERE guild_id = ? AND user_id = ?",
            (delta, partnerships, approvals, guild_id, user_id),
        )
    _q(
        "INSERT INTO points_log (guild_id, user_id, delta, reason, actor_id, pship_id, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (guild_id, user_id, delta, reason, actor_id, pship_id, now()),
    )
    row = _one("SELECT points FROM points WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    return int(row["points"]) if row else 0


def partnership_point_ledger(pship_id: int) -> list[sqlite3.Row]:
    """Net points this partnership is currently responsible for, per user."""
    assert _conn is not None
    with _lock:
        return list(_conn.execute(
            "SELECT user_id, SUM(delta) AS net FROM points_log "
            " WHERE pship_id = ? GROUP BY user_id HAVING net != 0",
            (pship_id,),
        ))


def revoke_partnership_points(pship_id: int, actor_id: int) -> list[tuple[int, int, int]]:
    """
    Undo the points this partnership awarded — exactly, to the point.

    The amounts come from the bot's own ledger, never from a human typing a
    number. Running it twice is a no-op because the ledger nets to zero.
    Returns (user_id, amount_removed, new_total) per affected member.
    """
    row = get_partnership(pship_id)
    if row is None:
        return []

    out: list[tuple[int, int, int]] = []
    for entry in partnership_point_ledger(pship_id):
        user_id, net = int(entry["user_id"]), int(entry["net"])
        total = add_points(
            row["guild_id"],
            user_id,
            -net,
            reason=f"Partnership #{pship_id} revoked",
            actor_id=actor_id,
            pship_id=pship_id,
            partnerships=-1 if user_id == row["poster_id"] else 0,
            approvals=-1 if user_id == row["approver_id"] else 0,
        )
        out.append((user_id, net, total))
    return out


def _table(scope: str) -> str:
    return "lifetime" if scope == "lifetime" else "points"


def get_user_stats(guild_id: int, user_id: int, scope: str = "weekly") -> sqlite3.Row:
    t = _table(scope)
    row = _one(f"SELECT * FROM {t} WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    if row is None:
        _q(f"INSERT OR IGNORE INTO {t} (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
        row = _one(f"SELECT * FROM {t} WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    assert row is not None
    return row


def get_rank(guild_id: int, user_id: int, scope: str = "weekly") -> int:
    t = _table(scope)
    row = _one(
        f"SELECT COUNT(*) + 1 AS r FROM {t} WHERE guild_id = ? AND points > "
        f"(SELECT points FROM {t} WHERE guild_id = ? AND user_id = ?)",
        (guild_id, guild_id, user_id),
    )
    return int(row["r"]) if row else 1


def leaderboard(guild_id: int, limit: int = 10, offset: int = 0, scope: str = "weekly") -> list[sqlite3.Row]:
    t = _table(scope)
    return _all(
        f"SELECT * FROM {t} WHERE guild_id = ? AND points != 0 "
        f"ORDER BY points DESC, partnerships DESC, user_id ASC LIMIT ? OFFSET ?",
        (guild_id, limit, offset),
    )


def leaderboard_size(guild_id: int, scope: str = "weekly") -> int:
    t = _table(scope)
    row = _one(f"SELECT COUNT(*) AS c FROM {t} WHERE guild_id = ? AND points != 0", (guild_id,))
    return int(row["c"]) if row else 0


def guild_totals(guild_id: int, scope: str = "weekly") -> tuple[int, int, int]:
    """(points awarded, ranked members, approved partnerships)"""
    t = _table(scope)
    row = _one(
        f"SELECT COALESCE(SUM(points),0) AS p, COUNT(*) AS m FROM {t} WHERE guild_id = ? AND points > 0",
        (guild_id,),
    )
    if scope == "lifetime":
        approved = count_partnerships(guild_id, "approved")
    else:
        approved = count_partnerships_since(guild_id, week_started_at(guild_id))
    return (int(row["p"]), int(row["m"]), approved) if row else (0, 0, approved)


def reset_leaderboard(guild_id: int, scope: str = "weekly") -> int:
    t = _table(scope)
    row = _one(f"SELECT COUNT(*) AS c FROM {t} WHERE guild_id = ?", (guild_id,))
    n = int(row["c"]) if row else 0
    _q(f"DELETE FROM {t} WHERE guild_id = ?", (guild_id,))
    return n


def recent_history(guild_id: int, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
    return _all(
        "SELECT * FROM points_log WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
        (guild_id, user_id, limit),
    )


# --------------------------------------------------------------------------- #
#  Weekly cycle  (nothing is archived to disk - results are posted to Discord)
# --------------------------------------------------------------------------- #

def week_number(guild_id: int) -> int:
    return get_state_int(guild_id, "week_number", 1)


def week_started_at(guild_id: int) -> int:
    return get_state_int(guild_id, "week_started_at", 0)


def current_standings(guild_id: int) -> list[sqlite3.Row]:
    """This week's scorers, best first. Used for the results post, then wiped."""
    return _all(
        "SELECT * FROM points WHERE guild_id = ? AND points > 0 "
        "ORDER BY points DESC, partnerships DESC, user_id ASC",
        (guild_id,),
    )


def credit_week_win(guild_id: int, user_id: int) -> None:
    """One integer per winner - the only thing a finished week leaves behind."""
    _q("INSERT OR IGNORE INTO lifetime (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
    _q(
        "UPDATE lifetime SET weeks_won = weeks_won + 1 WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )


def weeks_won(guild_id: int, user_id: int) -> int:
    row = _one("SELECT weeks_won FROM lifetime WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
    return int(row["weeks_won"]) if row else 0


# --------------------------------------------------------------------------- #
#  Partner cooldown
# --------------------------------------------------------------------------- #

def active_cooldown(
    guild_id: int,
    dedupe_key: str,
    target_name: Optional[str],
    invite_code: Optional[str],
    hours: int,
) -> Optional[sqlite3.Row]:
    """
    The most recent approved partnership with this partner inside the cooldown
    window. Matched by target server id, invite code, or server name.
    """
    if hours <= 0:
        return None
    cutoff = now() - hours * 3600
    return _one(
        """
        SELECT * FROM partnerships
         WHERE guild_id = ?
           AND status = 'approved'
           AND resolved_at IS NOT NULL
           AND resolved_at >= ?
           AND (
                dedupe_key = ?
                OR (invite_code IS NOT NULL AND invite_code = ?)
                OR (target_name IS NOT NULL AND ? IS NOT NULL
                    AND LOWER(target_name) = LOWER(?))
           )
         ORDER BY resolved_at DESC
         LIMIT 1
        """,
        (guild_id, cutoff, dedupe_key, invite_code, target_name, target_name),
    )


# --------------------------------------------------------------------------- #
#  Housekeeping - keeps the database tiny on small cloud hosts
# --------------------------------------------------------------------------- #

def prune(guild_id: int, keep_days: int, keep_log_days: int = 30) -> tuple[int, int]:
    """Delete old resolved partnerships and old point-log rows. Returns counts."""
    removed_p = removed_l = 0
    if keep_days > 0:
        cutoff = now() - keep_days * 86400
        cur = _q(
            "DELETE FROM partnerships WHERE guild_id = ? AND status != 'pending' "
            "AND COALESCE(resolved_at, created_at) < ?",
            (guild_id, cutoff),
        )
        removed_p = cur.rowcount or 0
    if keep_log_days > 0:
        cutoff = now() - keep_log_days * 86400
        cur = _q("DELETE FROM points_log WHERE guild_id = ? AND created_at < ?", (guild_id, cutoff))
        removed_l = cur.rowcount or 0
    if removed_p or removed_l:
        with _lock:
            assert _conn is not None
            _conn.execute("VACUUM")
    return removed_p, removed_l


def db_size_bytes() -> int:
    try:
        return sum(
            os.path.getsize(DB_PATH + suffix)
            for suffix in ("", "-wal", "-shm")
            if os.path.exists(DB_PATH + suffix)
        )
    except OSError:
        return 0
