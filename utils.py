"""Shared helpers: invite parsing, permission checks, embed builders."""

from __future__ import annotations

import re
from typing import Optional, Sequence

import discord

# --------------------------------------------------------------------------- #
#  Invite detection
# --------------------------------------------------------------------------- #

# Matches discord.gg/x, discord.com/invite/x, dsc.gg/x, invite.gg/x, .io/.me/.li
INVITE_RE = re.compile(
    r"(?:https?://)?"
    r"(?:www\.)?"
    r"(?:"
    r"discord(?:app)?\.com/invite|"
    r"discord\.(?:gg|io|me|li)|"
    r"dsc\.gg|"
    r"invite\.gg|"
    r"discord\.gg"
    r")"
    r"/+([a-zA-Z0-9\-_]{2,64})",
    re.IGNORECASE,
)

# Things that look like codes but never are
_BAD_CODES = {"invite", "http", "https", "www"}


def extract_invite_codes(text: str) -> list[str]:
    """Return every unique invite code in `text`, preserving order."""
    if not text:
        return []
    seen: list[str] = []
    for match in INVITE_RE.finditer(text):
        code = match.group(1)
        if code.lower() in _BAD_CODES:
            continue
        if code not in seen:
            seen.append(code)
    return seen


def dedupe_key_for(target_guild_id: Optional[int], code: str) -> str:
    """
    Prefer the target server id so two different invite codes pointing at the
    same server are treated as one partnership. Fall back to the raw code.
    """
    if target_guild_id:
        return f"guild:{target_guild_id}"
    return f"code:{code.lower()}"


# --------------------------------------------------------------------------- #
#  Mass-ping detection
# --------------------------------------------------------------------------- #

# Matches a real @everyone / @here, but NOT escaped (\@everyone) or inline-code
# forms, and not words like "@everyonee".
EVERYONE_RE = re.compile(r"(?<!\\)@everyone\b", re.IGNORECASE)
HERE_RE = re.compile(r"(?<!\\)@here\b", re.IGNORECASE)
_CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def strip_code(text: str) -> str:
    """Remove code blocks/spans — pings inside them don't notify anyone."""
    return _CODE_RE.sub(" ", text or "")


def find_mass_ping(text: str, include_here: bool = True) -> Optional[str]:
    """Return 'everyone' / 'here' if the text contains a live mass ping."""
    clean = strip_code(text)
    if EVERYONE_RE.search(clean):
        return "everyone"
    if include_here and HERE_RE.search(clean):
        return "here"
    return None


# --------------------------------------------------------------------------- #
#  Permission helpers
# --------------------------------------------------------------------------- #

def has_role(member: discord.Member, role_id: Optional[int]) -> bool:
    roles = getattr(member, "roles", None)
    if not role_id or roles is None:
        return False
    return any(r.id == role_id for r in roles)


def is_staff(member: discord.Member, cfg) -> bool:
    return (
        has_role(member, cfg["staff_role_id"])
        or has_role(member, cfg["approver_role_id"])
        or member.guild_permissions.manage_guild
    )


def is_approver(member: discord.Member, cfg) -> bool:
    return has_role(member, cfg["approver_role_id"]) or member.guild_permissions.manage_guild


# --------------------------------------------------------------------------- #
#  Formatting
# --------------------------------------------------------------------------- #

COLOR_PENDING = 0x5865F2   # blurple
COLOR_PROOF = 0xFEE75C     # yellow
COLOR_APPROVED = 0x57F287  # green
COLOR_REJECTED = 0xED4245  # red
COLOR_NEUTRAL = 0x2B2D31   # dark

STATUS_LABEL = {
    "pending": "⏳ Waiting for proof",
    "proof": "🟡 Proof submitted — awaiting approval",
    "approved": "✅ Approved",
    "rejected": "❌ Rejected",
    "cancelled": "🚫 Cancelled",
    "revoked": "↩️ Revoked — points taken back",
}


def status_color(status: str, has_proof: bool = False) -> int:
    if status == "approved":
        return COLOR_APPROVED
    if status in ("rejected", "cancelled", "revoked"):
        return COLOR_REJECTED
    if has_proof:
        return COLOR_PROOF
    return COLOR_PENDING


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def thread_name_for(target_name: Optional[str], code: str, pship_id: int) -> str:
    base = target_name or code
    return truncate(f"🤝 {base}", 90)


def medal(index: int) -> str:
    return {0: "🥇", 1: "🥈", 2: "🥉"}.get(index, f"`#{index + 1}`")


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def chunk(seq: Sequence, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def humanize_seconds(seconds: int) -> str:
    """90061 -> '1d 1h 1m'. Always returns something readable."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes and not days:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "under a minute"


def progress_bar(done: int, target: int, width: int = 10) -> str:
    """A text progress bar that renders identically on every device."""
    if target <= 0:
        return "─" * width
    filled = min(width, int(round(width * min(done, target) / target)))
    return "█" * filled + "░" * (width - filled)
