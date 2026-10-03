"""
Loads config.toml.

The whole bot is configured from that one file — there are no setup slash
commands. Edit the file, then either restart the bot or run /reloadconfig.

Settings are exposed with dictionary access (cfg["staff_role_id"]) so the rest
of the codebase reads the same way everywhere.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

log = logging.getLogger("partnership.config")

CONFIG_PATH = os.getenv("CONFIG_PATH", "config.toml")

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class ConfigError(Exception):
    pass


def _get(data: dict, path: str, default: Any = None) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _int(data: dict, path: str, default: int = 0) -> int:
    val = _get(data, path, default)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _bool(data: dict, path: str, default: bool) -> bool:
    val = _get(data, path, default)
    return bool(val) if isinstance(val, bool) else default


def _id_list(data: dict, path: str) -> tuple[int, ...]:
    """A TOML array of Discord IDs -> tuple of ints. Junk entries are dropped."""
    val = _get(data, path, None)
    if val is None:
        return ()
    if not isinstance(val, (list, tuple)):
        val = [val]
    out: list[int] = []
    for item in val:
        try:
            num = int(item)
        except (TypeError, ValueError):
            continue
        if num > 0 and num not in out:
            out.append(num)
    return tuple(out)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


@dataclass
class Config:
    path: str
    mtime: float
    raw: dict
    values: dict
    warnings: list[str] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        try:
            return self.values[key]
        except KeyError as exc:
            raise KeyError(f"Unknown setting {key!r}") from exc

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.values

    @property
    def ready(self) -> bool:
        return bool(
            self["guild_id"]
            and self["listen_channel_id"]
            and self["approver_role_id"]
        )

    def missing(self) -> list[str]:
        problems = []
        if not self["guild_id"]:
            problems.append("`guild_id` (top of config.toml)")
        if not self["listen_channel_id"]:
            problems.append("`[channels] partnership`")
        if not self["approver_role_id"]:
            problems.append("`[roles] approver`")
        return problems


def _build(data: dict, path: str, mtime: float) -> Config:
    warnings: list[str] = []

    listen = _int(data, "channels.partnership")
    parent = _int(data, "channels.threads") or listen

    weekly_day = str(_get(data, "weekly_reset.day", "monday")).strip().lower()
    if weekly_day not in DAYS:
        warnings.append(f"[weekly_reset] day = {weekly_day!r} is not a weekday name; using 'monday'")
        weekly_day = "monday"

    weekly_time = str(_get(data, "weekly_reset.time", "00:00")).strip()
    try:
        hh, mm = (int(x) for x in weekly_time.split(":", 1))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except (ValueError, TypeError):
        warnings.append(f"[weekly_reset] time = {weekly_time!r} is not HH:MM; using '00:00'")
        hh, mm = 0, 0
        weekly_time = "00:00"

    tz = str(_get(data, "weekly_reset.timezone", "UTC")).strip() or "UTC"
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
    except Exception:
        warnings.append(f"[weekly_reset] timezone = {tz!r} is not a valid tz name; using 'UTC'")
        tz = "UTC"

    archive = _int(data, "threads.auto_archive_minutes", 10080)
    if archive not in (60, 1440, 4320, 10080):
        warnings.append(
            f"[threads] auto_archive_minutes = {archive} must be 60, 1440, 4320 or 10080; using 10080"
        )
        archive = 10080

    values = {
        "guild_id": _int(data, "guild_id"),
        "enabled": int(_bool(data, "enabled", True)),

        # channels
        "listen_channel_id": listen,
        "thread_parent_id": parent,
        "log_channel_id": _int(data, "channels.logs"),
        "lb_channel_id": _int(data, "channels.leaderboard"),
        "weekly_channel_id": _int(data, "channels.weekly_results"),
        "quota_channel_id": _int(data, "channels.quota"),

        # roles
        "staff_role_id": _int(data, "roles.staff"),
        "approver_role_id": _int(data, "roles.approver"),
        "weekly_ping_role_id": _int(data, "roles.weekly_ping"),

        # points
        "poster_points": _clamp(_int(data, "points.staff", 2), 0, 1000),
        "approver_points": _clamp(_int(data, "points.approver", 1), 0, 1000),

        # proof
        "require_proof": int(_bool(data, "proof.required", True)),
        "proof_attachment_only": int(_bool(data, "proof.attachment_only", True)),

        # threads
        "auto_archive": archive,
        # who actually gets put INTO the private thread
        "add_staff_role": int(_bool(data, "threads.add_staff_role", False)),
        "add_approver_role": int(_bool(data, "threads.add_approver_role", True)),
        "max_staff_added": _clamp(_int(data, "threads.max_members_added", 40), 1, 100),
        # who gets pinged in the thread when it opens
        "ping_poster": int(_bool(data, "threads.ping_poster", True)),
        "ping_staff_role": int(_bool(data, "threads.ping_staff_role", False)),
        "ping_approver_role": int(_bool(data, "threads.ping_approver_role", True)),

        # duplicates
        "dup_notice_delete": _clamp(_int(data, "duplicates.hide_after_seconds", 15), 0, 300),
        "dup_delete_message": int(_bool(data, "duplicates.delete_duplicate_message", True)),

        # live leaderboard
        "lb_enabled": int(_bool(data, "leaderboard.enabled", True)),
        "lb_interval": _clamp(_int(data, "leaderboard.interval_seconds", 60), 30, 3600),
        "lb_top_n": _clamp(_int(data, "leaderboard.top", 10), 3, 15),

        # weekly reset
        "weekly_enabled": int(_bool(data, "weekly_reset.enabled", True)),
        "weekly_day": weekly_day,
        "weekly_time": weekly_time,
        "weekly_hour": hh,
        "weekly_minute": mm,
        "weekly_tz": tz,
        "weekly_top": _clamp(_int(data, "weekly_reset.top", 10), 3, 25),

        # what happens when a partnership is approved / rejected
        "delete_thread_on_approve": int(_bool(data, "on_decision.delete_thread_on_approve", True)),
        "delete_thread_on_reject": int(_bool(data, "on_decision.delete_thread_on_reject", True)),
        "delete_thread_after": _clamp(_int(data, "on_decision.delete_thread_after_seconds", 15), 0, 3600),
        "delete_ad_on_reject": int(_bool(data, "on_decision.delete_ad_on_reject", True)),

        # weekly quota
        "quota_enabled": int(_bool(data, "quota.enabled", True)),
        "quota_target": _clamp(_int(data, "quota.target", 5), 0, 1000),
        "quota_metric": (
            "points" if str(_get(data, "quota.count", "partnerships")).lower() == "points"
            else "partnerships"
        ),
        "quota_ping": int(_bool(data, "quota.ping_member", True)),
        "quota_announce_done": int(_bool(data, "quota.announce_complete", True)),
        "quota_in_thread": int(_bool(data, "quota.also_post_in_thread", False)),

        # anti mass-ping
        "antiping_enabled": int(_bool(data, "antiping.enabled", True)),
        "antiping_scope": (
            "all" if str(_get(data, "antiping.scope", "partnership")).lower() == "all"
            else "partnership"
        ),
        "antiping_here": int(_bool(data, "antiping.block_here", True)),
        "antiping_roles": int(_bool(data, "antiping.block_role_pings", False)),
        "antiping_delete": int(_bool(data, "antiping.delete_message", True)),
        "antiping_notice_delete": _clamp(_int(data, "antiping.notice_hide_after_seconds", 15), 0, 300),
        # who the filter leaves alone. Default: the server owner only.
        "antiping_exempt_owner": int(_bool(data, "antiping.exempt_owner", True)),
        "antiping_exempt_admins": int(_bool(data, "antiping.exempt_admins", False)),
        "antiping_exempt_approvers": int(_bool(data, "antiping.exempt_approvers", False)),
        "antiping_exempt_users": _id_list(data, "antiping.exempt_users"),

        # partner cooldown
        "cooldown_enabled": int(_bool(data, "cooldown.enabled", True)),
        "cooldown_hours": _clamp(_int(data, "cooldown.hours", 24), 0, 8760),
        "cooldown_delete": int(_bool(data, "cooldown.delete_message", True)),
        "cooldown_notice_delete": _clamp(_int(data, "cooldown.notice_hide_after_seconds", 20), 0, 300),

        # storage housekeeping
        "keep_partnership_days": _clamp(_int(data, "storage.keep_partnership_days", 90), 0, 3650),
        "keep_log_days": _clamp(_int(data, "storage.keep_point_log_days", 30), 0, 3650),
    }

    if values["lb_enabled"] and not values["lb_channel_id"]:
        warnings.append("[leaderboard] enabled = true but [channels] leaderboard is 0 — live board is off")
        values["lb_enabled"] = 0
    if (
        (values["delete_thread_on_approve"] or values["delete_thread_on_reject"])
        and not values["log_channel_id"]
    ):
        warnings.append(
            "[on_decision] threads get deleted but [channels] logs is 0 — "
            "set a log channel or you'll keep no record of approvals/rejections"
        )
    if values["cooldown_enabled"] and values["cooldown_hours"] == 0:
        warnings.append("[cooldown] hours = 0 disables the cooldown even though enabled = true")
        values["cooldown_enabled"] = 0
    if values["weekly_enabled"] and not values["weekly_channel_id"]:
        warnings.append(
            "[weekly_reset] enabled = true but [channels] weekly_results is 0 — "
            "the reset will still run, results just won't be posted anywhere"
        )

    if values["quota_enabled"] and not values["quota_channel_id"]:
        warnings.append(
            "[quota] enabled = true but [channels] quota is 0 — progress messages are off"
        )
        values["quota_enabled"] = 0
    if values["quota_enabled"] and values["quota_target"] == 0:
        warnings.append("[quota] target = 0 means there is nothing to hit; quota is off")
        values["quota_enabled"] = 0

    if not values["guild_id"]:
        warnings.append(
            "guild_id = 0 — the bot will act in EVERY server it's invited to. "
            "Set your server's ID so a stranger can't add it and use your config."
        )
    if values["require_proof"] and not values["proof_attachment_only"]:
        warnings.append(
            "[proof] attachment_only = false — a pasted image LINK counts as proof, "
            "so anyone can satisfy it with someone else's screenshot"
        )
    if values["poster_points"] < 0 or values["approver_points"] < 0:
        warnings.append("[points] negative values will subtract points on approval")

    # Points are stored as integers. 0.2 would quietly become 0, so say so.
    for key in ("staff", "approver"):
        raw_pts = _get(data, f"points.{key}")
        if isinstance(raw_pts, float):
            warnings.append(
                f"[points] {key} = {raw_pts} — fractional points aren't supported, "
                f"this is being used as {int(raw_pts)}. Scale both values up instead "
                f"(1 and 0.2 is the same ratio as 5 and 1)."
            )

    return Config(path=path, mtime=mtime, raw=data, values=values, warnings=warnings)


_current: Optional[Config] = None


def load(path: str | None = None) -> Config:
    """Read config.toml from disk and make it the active configuration."""
    global _current
    path = path or CONFIG_PATH

    if not os.path.exists(path):
        raise ConfigError(
            f"{path} not found.\n"
            f"Copy config.example.toml to {path} and fill in your IDs."
        )

    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML:\n  {exc}") from exc

    cfg = _build(data, path, os.path.getmtime(path))
    _current = cfg
    for w in cfg.warnings:
        log.warning("config: %s", w)
    return cfg


def get() -> Config:
    if _current is None:
        return load()
    return _current


def changed_on_disk() -> bool:
    cfg = _current
    if cfg is None:
        return True
    try:
        return os.path.getmtime(cfg.path) != cfg.mtime
    except OSError:
        return False


def reload_if_changed() -> Optional[Config]:
    """Re-read the file only when its timestamp moved. Returns the new config."""
    if changed_on_disk():
        return load()
    return None
