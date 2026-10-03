"""
Offline sanity tests — no Discord connection required.

Run:  python -m tests.test_bot
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp()
MAIN_DB = os.path.join(TMP, "test.db")
os.environ["DB_PATH"] = MAIN_DB

CONFIG_TEXT = """
guild_id = 1
enabled = true
[channels]
partnership = 10
threads = 11
logs = 12
leaderboard = 13
weekly_results = 14
quota = 15
[roles]
staff = 20
approver = 30
weekly_ping = 40
[points]
staff = 3
approver = 1
[proof]
required = true
attachment_only = true
[threads]
auto_archive_minutes = 10080
add_staff = true
max_members_added = 40
[duplicates]
hide_after_seconds = 15
delete_duplicate_message = false
[leaderboard]
enabled = true
interval_seconds = 60
top = 10
[weekly_reset]
enabled = true
day = "monday"
time = "00:00"
timezone = "Asia/Dhaka"
top = 10
[quota]
enabled = true
target = 5
count = "partnerships"

[antiping]
enabled = true
scope = "partnership"
block_here = true
block_role_pings = false
delete_message = true
notice_hide_after_seconds = 15
exempt_approvers = true
exempt_users = [777, 888, "nope", 777]
[on_decision]
delete_thread_on_approve = true
delete_thread_on_reject = true
delete_thread_after_seconds = 15
delete_ad_on_reject = true
[cooldown]
enabled = true
hours = 24
delete_message = true
notice_hide_after_seconds = 20
[storage]
keep_partnership_days = 90
keep_point_log_days = 30
"""
CONFIG_FILE = os.path.join(TMP, "config.toml")
open(CONFIG_FILE, "w").write(CONFIG_TEXT)
os.environ["CONFIG_PATH"] = CONFIG_FILE

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import utils  # noqa: E402

config.CONFIG_PATH = CONFIG_FILE
config.load(CONFIG_FILE)

PASS, FAIL = 0, 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  \033[32mPASS\033[0m  {label}")
    else:
        FAIL += 1
        print(f"  \033[31mFAIL\033[0m  {label} {detail}")


# --------------------------------------------------------------------------- #
print("\n[1] Invite link detection")

cases = {
    "join us https://discord.gg/AbCd1234 pls": ["AbCd1234"],
    "discord.gg/test1 and discord.gg/test2": ["test1", "test2"],
    "https://discord.com/invite/hello-world": ["hello-world"],
    "http://www.discordapp.com/invite/xyz789": ["xyz789"],
    "dsc.gg/mycoolserver": ["mycoolserver"],
    "**Partner:** <https://discord.gg/Spaced> — great server!": ["Spaced"],
    "no link here at all": [],
    "discord.gg/dupe discord.gg/dupe": ["dupe"],
    "visit example.com/invite/nope": [],
}
for text, expected in cases.items():
    got = utils.extract_invite_codes(text)
    check(f"{text[:44]!r}", got == expected, f"→ got {got}, expected {expected}")

check(
    "dedupe prefers target guild id",
    utils.dedupe_key_for(999, "abc") == "guild:999"
    and utils.dedupe_key_for(None, "AbC") == "code:abc",
)

# --------------------------------------------------------------------------- #
print("\n[2] Config file")

cfg = config.get()
check("guild id parsed", cfg["guild_id"] == 1)
check("channels parsed", cfg["listen_channel_id"] == 10 and cfg["thread_parent_id"] == 11)
check("leaderboard channel", cfg["lb_channel_id"] == 13)
check("weekly channel", cfg["weekly_channel_id"] == 14)
check("roles parsed", cfg["staff_role_id"] == 20 and cfg["approver_role_id"] == 30)
check("points parsed", cfg["poster_points"] == 3 and cfg["approver_points"] == 1)
check("proof required", cfg["require_proof"] == 1)
check("weekly schedule", cfg["weekly_day"] == "monday" and cfg["weekly_hour"] == 0)
check("timezone kept", cfg["weekly_tz"] == "Asia/Dhaka")
check("cooldown parsed", cfg["cooldown_enabled"] == 1 and cfg["cooldown_hours"] == 24)
check("antiping parsed", cfg["antiping_enabled"] == 1 and cfg["antiping_scope"] == "partnership")
check("antiping here", cfg["antiping_here"] == 1 and cfg["antiping_roles"] == 0)
check("antiping exempts approvers", cfg["antiping_exempt_approvers"] == 1)
check("antiping exempts owner by default", cfg["antiping_exempt_owner"] == 1)
check("antiping does not exempt admins by default", cfg["antiping_exempt_admins"] == 0)
check("antiping exempt_users parsed + deduped", cfg["antiping_exempt_users"] == (777, 888))
check("thread deletion parsed", cfg["delete_thread_on_approve"] == 1 and cfg["delete_thread_on_reject"] == 1)
check("grace period parsed", cfg["delete_thread_after"] == 15)
check("ad deletion parsed", cfg["delete_ad_on_reject"] == 1)
check("storage parsed", cfg["keep_partnership_days"] == 90 and cfg["keep_log_days"] == 30)
check("config is ready", cfg.ready is True)
check("nothing missing", cfg.missing() == [])
check("db.get_config returns the file config", db.get_config(1)["staff_role_id"] == 20)

# threads = 0 should fall back to the partnership channel
fallback = config._build({"channels": {"partnership": 99, "threads": 0}}, "x", 0)
check("threads falls back to partnership channel", fallback["thread_parent_id"] == 99)

bad = config._build(
    {"weekly_reset": {"day": "funday", "time": "99:99", "timezone": "Mars/Olympus"}}, "x", 0
)
check("bad weekday corrected", bad["weekly_day"] == "monday")
check("bad time corrected", bad["weekly_time"] == "00:00")
check("bad timezone corrected", bad["weekly_tz"] == "UTC")
check("bad values produce warnings", len(bad.warnings) >= 3)

empty = config._build({}, "x", 0)
check("empty config reports what's missing", len(empty.missing()) == 3)
check("staff role is not listed as required",
      not any("staff" in m for m in empty.missing()))

# --- the staff role is optional: approver-only setups must work ---------- #
_noStaff = config._build(
    {
        "guild_id": 1,
        "channels": {"partnership": 2},
        "roles": {"approver": 3},
    },
    "x",
    0,
)
check("approver-only config has no staff role", _noStaff["staff_role_id"] == 0)
check("approver-only config is ready", _noStaff.ready is True)
check("approver-only config missing nothing", _noStaff.missing() == [])
check("approver-only config passes db.is_configured", db.is_configured(_noStaff) is True)
check("still not ready without an approver",
      config._build({"guild_id": 1, "channels": {"partnership": 2}}, "x", 0).ready is False)


class _NoStaffMember:
    def __init__(self, role_ids):
        self.roles = [types.SimpleNamespace(id=r) for r in role_ids]
        self.guild_permissions = types.SimpleNamespace(manage_guild=False)


check("approver counts as staff when no staff role exists",
      utils.is_staff(_NoStaffMember([3]), _noStaff) is True)
check("random member is still not staff",
      utils.is_staff(_NoStaffMember([99]), _noStaff) is False)
check("approver still passes is_approver",
      utils.is_approver(_NoStaffMember([3]), _noStaff) is True)
check("defaults applied", empty["poster_points"] == 2 and empty["lb_interval"] == 60)

bare = config._build({}, "x", 0)
check("default: owner exempt from ping filter", bare["antiping_exempt_owner"] == 1)
check("default: admins NOT exempt", bare["antiping_exempt_admins"] == 0)
check("default: approvers NOT exempt", bare["antiping_exempt_approvers"] == 0)
check("default: no exempt users", bare["antiping_exempt_users"] == ())
junk = config._build({"antiping": {"exempt_users": 999}}, "x", 0)
check("exempt_users accepts a bare int", junk["antiping_exempt_users"] == (999,))
junk2 = config._build({"antiping": {"exempt_users": ["0", -5, "abc"]}}, "x", 0)
check("exempt_users drops junk and zero", junk2["antiping_exempt_users"] == ())

scope_all = config._build({"antiping": {"scope": "ALL"}}, "x", 0)
check("antiping scope accepts ALL", scope_all["antiping_scope"] == "all")
scope_bad = config._build({"antiping": {"scope": "wat"}}, "x", 0)
check("bad antiping scope falls back", scope_bad["antiping_scope"] == "partnership")

no_log = config._build({"on_decision": {"delete_thread_on_approve": True}}, "x", 0)
check("warns when deleting threads with no log channel",
      any("logs is 0" in w for w in no_log.warnings))
instant = config._build({"on_decision": {"delete_thread_after_seconds": 0}}, "x", 0)
check("0 grace period allowed", instant["delete_thread_after"] == 0)
keepers = config._build(
    {"on_decision": {"delete_thread_on_approve": False, "delete_thread_on_reject": False,
                     "delete_ad_on_reject": False}}, "x", 0)
check("deletion can be turned off",
      keepers["delete_thread_on_approve"] == 0 and keepers["delete_ad_on_reject"] == 0)

zero_cd = config._build({"cooldown": {"enabled": True, "hours": 0}}, "x", 0)
check("cooldown hours 0 disables it", zero_cd["cooldown_enabled"] == 0)
check("cooldown 0 warns", any("cooldown" in w for w in zero_cd.warnings))

clamped = config._build({"leaderboard": {"interval_seconds": 5, "top": 99}}, "x", 0)
check("interval clamped to 30", clamped["lb_interval"] == 30)
check("top clamped to 15", clamped["lb_top_n"] == 15)

try:
    config.load(os.path.join(TMP, "nope.toml"))
    check("missing file raises", False)
except config.ConfigError:
    check("missing file raises ConfigError", True)

broken = os.path.join(TMP, "broken.toml")
open(broken, "w").write("guild_id = = 5")
try:
    config.load(broken)
    check("bad TOML raises", False)
except config.ConfigError:
    check("bad TOML raises ConfigError", True)
config.load(CONFIG_FILE)

# --------------------------------------------------------------------------- #
print("\n[3] Database")

db.connect()
G, POSTER, APPROVER, CO = 1, 100, 200, 300

pid = db.create_partnership(
    guild_id=G, dedupe_key="guild:555", invite_code="abc",
    target_guild_id=555, target_name="Cool Server",
    source_channel_id=10, source_message_id=11, poster_id=POSTER,
)
check("partnership created", pid == 1)
check("found as open duplicate", db.find_open_partnership(G, "guild:555") is not None)
check("different key is not a duplicate", db.find_open_partnership(G, "guild:666") is None)

db.update_partnership(pid, thread_id=77, proof_msg_id=88, proof_url="http://x/y.png")
p_row = db.get_partnership(pid)
check("proof recorded", p_row["proof_msg_id"] == 88 and p_row["thread_id"] == 77)
check("lookup by thread", db.get_partnership_by_thread(77)["id"] == pid)

db.set_state(G, "demo", 42)
check("state round-trips", db.get_state_int(G, "demo") == 42)
check("state default", db.get_state_int(G, "nope", 7) == 7)
db.clear_state(G, "demo")
check("state cleared", db.get_state_int(G, "demo", -1) == -1)

# --------------------------------------------------------------------------- #
print("\n[3] Points & leaderboard")

db.update_partnership(pid, status="approved", approver_id=APPROVER, resolved_at=db.now())
db.add_points(G, POSTER, 3, reason="approved", pship_id=pid, partnerships=1)
db.add_points(G, CO, 3, reason="second staff member", pship_id=pid, partnerships=1)
db.add_points(G, APPROVER, 1, reason="approval", pship_id=pid, approvals=1)

check("poster points", db.get_user_stats(G, POSTER)["points"] == 3)
check("lifetime mirrors weekly", db.get_user_stats(G, POSTER, "lifetime")["points"] == 3)
check("approver points", db.get_user_stats(G, APPROVER)["points"] == 1)
check("partnership counter", db.get_user_stats(G, POSTER)["partnerships"] == 1)
check("approval counter", db.get_user_stats(G, APPROVER)["approvals"] == 1)

db.add_points(G, POSTER, 10, reason="bonus")
lb = db.leaderboard(G, 10)
check("leaderboard ordered", [r["user_id"] for r in lb] == [POSTER, CO, APPROVER], f"→ {[r['user_id'] for r in lb]}")
check("rank #1", db.get_rank(G, POSTER) == 1)
check("rank #3", db.get_rank(G, APPROVER) == 3)

db.add_points(G, POSTER, -5, reason="penalty")
check("points can be removed", db.get_user_stats(G, POSTER)["points"] == 8)
check("history logged", len(db.recent_history(G, POSTER, 10)) == 3)

check("duplicate blocked while approved", db.find_open_partnership(G, "guild:555") is not None)
db.update_partnership(pid, status="cancelled")
check("cancelled frees the dedupe key", db.find_open_partnership(G, "guild:555") is None)

check("guild isolation", db.leaderboard_size(2) == 0)
life_before = db.get_user_stats(G, POSTER, "lifetime")["points"]
n = db.reset_leaderboard(G, "weekly")
check("weekly reset wipes weekly", n == 3 and db.leaderboard_size(G) == 0)
check("weekly reset keeps lifetime", db.get_user_stats(G, POSTER, "lifetime")["points"] == life_before)
db.reset_leaderboard(G, "lifetime")

# --------------------------------------------------------------------------- #
print("\n[4] Cogs, commands and buttons load")


async def load_everything():
    import views

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    bot.add_dynamic_items(views.ApproveButton, views.RejectButton)
    for ext in (
        "cogs.admin_cog", "cogs.partnership_cog", "cogs.leaderboard_cog",
        "cogs.liveboard_cog", "cogs.weekly_cog",
    ):
        await bot.load_extension(ext)
    return bot


async def load_and_quiesce():
    b = await load_everything()
    # the ticker can't run without a real connection - stop it for the test
    for cog_name in ("LiveBoardCog", "WeeklyCog"):
        cog = b.get_cog(cog_name)
        if cog is not None:
            cog.ticker.cancel()
    return b


bot = asyncio.run(load_and_quiesce())

names = set()
for cmd in bot.tree.get_commands():
    names.add(cmd.name)
    if isinstance(cmd, discord.app_commands.Group):
        for sub in cmd.commands:
            names.add(f"{cmd.name} {sub.name}")

expected_cmds = [
    "diagnose", "reloadconfig", "settings", "fixpings",
    "partnership list", "partnership info",
    "partnership close", "partnership add",
    "leaderboard", "points",
    "liveboard refresh", "liveboard preview",
    "week status", "week reset",
    "partnership cooldowns",
]
removed_week_cmds = ["week history", "week show"]
removed_cmds = ["setup", "config view", "config channels", "liveboard set", "liveboard off"]
for name in expected_cmds:
    check(f"/{name}", name in names)

for name in removed_cmds + removed_week_cmds:
    check(f"/{name} removed", name not in names)
check("no duplicate command names", len(names) >= len(expected_cmds))

# button custom_ids / dynamic templates
import views  # noqa: E402

fake_cfg = db.get_config()
fake_pship = db.get_partnership(pid)
view = views.build_control_view(fake_pship, fake_cfg)
ids = [c.custom_id for c in view.children]
check("approve button id", f"pship:approve:{pid}" in ids, f"→ {ids}")
check("reject button id", f"pship:reject:{pid}" in ids)

check("approve template matches", views.ApproveButton.__discord_ui_compiled_template__.match(f"pship:approve:{pid}") is not None)

# approve must be locked when proof is required but missing
pid2 = db.create_partnership(
    guild_id=G, dedupe_key="code:zzz", invite_code="zzz", poster_id=POSTER,
    source_channel_id=1, source_message_id=2,
)
view2 = views.build_control_view(db.get_partnership(pid2), db.get_config())
approve_btn = next(c for c in view2.children if "approve" in c.custom_id)
check("approve locked without proof", approve_btn.item.disabled is True)

db.update_partnership(pid2, proof_msg_id=5)
view3 = views.build_control_view(db.get_partnership(pid2), db.get_config())
approve_btn3 = next(c for c in view3.children if "approve" in c.custom_id)
check("approve unlocked with proof", approve_btn3.item.disabled is False)

config.get().values["require_proof"] = 0
pid3 = db.create_partnership(
    guild_id=G, dedupe_key="code:qqq", invite_code="qqq", poster_id=POSTER,
    source_channel_id=1, source_message_id=2,
)
view4 = views.build_control_view(db.get_partnership(pid3), db.get_config())
check(
    "approve unlocked when proof not required",
    next(c for c in view4.children if "approve" in c.custom_id).item.disabled is False,
)
db.update_partnership(pid3, status="approved")
view5 = views.build_control_view(db.get_partnership(pid3), db.get_config())
check(
    "all buttons disabled once resolved",
    all(c.item.disabled for c in view5.children),
)
config.get().values["require_proof"] = 1

# --------------------------------------------------------------------------- #
print("\n[5] Duplicate ownership rules")

from cogs.partnership_cog import PartnershipCog  # noqa: E402

owns = PartnershipCog._owns

dup_id = db.create_partnership(
    guild_id=G, dedupe_key="guild:4242", invite_code="dup", target_guild_id=4242,
    target_name="Dup Server", poster_id=POSTER, source_channel_id=1, source_message_id=2,
)
db.update_partnership(dup_id, thread_id=4321)
row = db.get_partnership(dup_id)

check("original poster owns it", owns(row, POSTER) is True)
check("random staff does NOT own it", owns(row, 999) is False)
check("approver does NOT own it", owns(row, APPROVER) is False)

row = db.get_partnership(dup_id)
check("someone else does not own it", owns(row, CO) is False)
check("still not owned by a stranger", owns(row, 999) is False)

cfg_now = db.get_config()
check("dup hide_after from file", cfg_now["dup_notice_delete"] == 15)
_frac = config._build({"points": {"staff": 1, "approver": 0.2}}, "x", 0)
check("fractional points truncate to int", _frac["approver_points"] == 0)
check("fractional points produce a warning",
      any("fractional" in w for w in _frac.warnings))
check("whole-number points warn about nothing",
      not any("fractional" in w for w in
              config._build({"points": {"staff": 5, "approver": 1}}, "x", 0).warnings))

check("dup delete on by default", config._build({}, "x", 0)["dup_delete_message"] == 1)
check("dup delete can be switched off", config._build(
    {"duplicates": {"delete_duplicate_message": False}}, "x", 0)["dup_delete_message"] == 0)


def _will_delete(foreign, created, flag):
    """Mirror of the guard in partnership_cog._react_and_report."""
    return bool(foreign and flag and not created)


check("foreign duplicate is deleted", _will_delete(["a"], [], 1) is True)
check("own duplicate is never deleted", _will_delete([], [], 1) is False)
check("mixed message with a new link is kept", _will_delete(["a"], ["new"], 1) is False)
check("nothing deleted when the flag is off", _will_delete(["a"], [], 0) is False)
check("notice is not a reply when the message is being deleted",
      (not _will_delete(["a"], [], 1)) is False)
forever = config._build({"duplicates": {"hide_after_seconds": 0}}, "x", 0)
check("hide_after 0 allowed (never delete)", forever["dup_notice_delete"] == 0)


# --------------------------------------------------------------------------- #
print("\n[6] Live leaderboard rendering")

from cogs import liveboard_cog as lbc  # noqa: E402


class FakeMember:
    def __init__(self, uid, name):
        self.id, self.display_name = uid, name


class FakeGuild2:
    id = G
    name = "Test Server"
    icon = None

    def get_member(self, uid):
        return FakeMember(uid, {POSTER: "Rafi", CO: "Shanto", APPROVER: "Head"}.get(uid, f"U{uid}"))


check("bar empty at zero", lbc._bar(0, 10) == lbc.BAR_EMPTY * lbc.BAR_WIDTH)
check("bar full at top", lbc._bar(10, 10) == lbc.BAR_FULL * lbc.BAR_WIDTH)
check("bar half", lbc._bar(5, 10).count(lbc.BAR_FULL) == lbc.BAR_WIDTH // 2)
check("bar safe when top is 0", len(lbc._bar(0, 0)) == lbc.BAR_WIDTH)
check("rank icons", lbc._rank_icon(0) == "🥇" and lbc._rank_icon(3) == "④")

g2 = FakeGuild2()
empty = lbc.render_leaderboard(g2, 10, live=False)
check("empty board renders", "No points this week yet" in empty.description)

db.add_points(G, POSTER, 25, reason="x", partnerships=8)
db.add_points(G, CO, 14, reason="x", partnerships=5)
db.add_points(G, APPROVER, 6, reason="x", approvals=6)
for i in range(4, 12):
    db.add_points(G, 1000 + i, 12 - i, reason="x", partnerships=1)

board = lbc.render_leaderboard(g2, 10, live=False)
check("podium shows top scorer", "Rafi" in board.description)
check("podium has medals", "🥇" in board.description and "🥈" in board.description)
check("bars rendered", lbc.BAR_FULL in board.description)
check("overflow list added", any(f.value and "④" in f.value for f in board.fields))
check("stat strip present", any(f.name == "Total points" for f in board.fields))
check("embed within discord limits", len(board) < 6000, f"→ {len(board)}")
check("description within limit", len(board.description) <= 4096)

live = lbc.render_leaderboard(g2, 10, live=True)
check("live footer", "live board" in live.footer.text)
check("refresh note", any("Refreshes every" in (f.value or "") for f in live.fields))
check("week strip on live board", any("Week" in (f.value or "") for f in live.fields))

fp1 = lbc._fingerprint(G, 10)
check("fingerprint stable", fp1 == lbc._fingerprint(G, 10))
db.add_points(G, POSTER, 1, reason="x")
check("fingerprint changes on new points", fp1 != lbc._fingerprint(G, 10))

totals = db.guild_totals(G)
check("totals computed", totals[0] > 0 and totals[1] >= 11, f"→ {totals}")



# --------------------------------------------------------------------------- #
print("\n[7] Weekly reset")

from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from cogs import weekly_cog as wk  # noqa: E402

cfgw = config.get()
tz = ZoneInfo(cfgw["weekly_tz"])

# Wed 2026-10-07 13:00 Dhaka -> next Monday 00:00 Dhaka
wed = int(datetime(2026, 10, 7, 13, 0, tzinfo=tz).timestamp())
nxt = wk.next_reset_after(wed, cfgw)
dt = datetime.fromtimestamp(nxt, tz)
check("next reset is a Monday", dt.weekday() == 0, f"-> {dt}")
check("next reset at 00:00", (dt.hour, dt.minute) == (0, 0), f"-> {dt}")
check("next reset is 2026-10-12", dt.date().isoformat() == "2026-10-12", f"-> {dt.date()}")
check("next reset is in the future", nxt > wed)

# exactly ON the reset moment -> must roll to the following week, never loop
exact = int(datetime(2026, 10, 12, 0, 0, tzinfo=tz).timestamp())
nxt2 = wk.next_reset_after(exact, cfgw)
check("reset moment rolls forward 7 days", nxt2 - exact == 7 * 86400, f"-> {(nxt2 - exact) / 86400}d")

one_min_before = exact - 60
check(
    "one minute before fires the same day",
    wk.next_reset_after(one_min_before, cfgw) == exact,
)

friday_cfg = config._build(
    {"weekly_reset": {"day": "friday", "time": "18:30", "timezone": "Asia/Dhaka"}}, "x", 0
)
fdt = datetime.fromtimestamp(wk.next_reset_after(wed, friday_cfg), tz)
check("custom day honoured", fdt.weekday() == 4, f"-> {fdt}")
check("custom time honoured", (fdt.hour, fdt.minute) == (18, 30), f"-> {fdt}")

# schedule bootstrapping
db.clear_state(G, "next_reset_at")
db.clear_state(G, "week_started_at")
boot = wk.ensure_schedule(G, cfgw)
check("schedule bootstrapped", boot > db.now())
check("week start recorded", db.get_state_int(G, "week_started_at", 0) > 0)
check("ensure_schedule is stable", wk.ensure_schedule(G, cfgw) == boot)

# --- a full week cycle, with nothing written to disk --------------------- #
db.reset_leaderboard(G, "weekly")
db.reset_leaderboard(G, "lifetime")
db.add_points(G, POSTER, 20, reason="w", partnerships=6)
db.add_points(G, CO, 11, reason="w", partnerships=3)
db.add_points(G, APPROVER, 4, reason="w", approvals=4)

check("no archive tables exist", "weekly_archive" not in db.SCHEMA and "CREATE TABLE IF NOT EXISTS weeks" not in db.SCHEMA)
check("only 5 tables", db.SCHEMA.count("CREATE TABLE") == 5, f"-> {db.SCHEMA.count('CREATE TABLE')}")

rows_now = db.current_standings(G)
check("standings read live", [r["user_id"] for r in rows_now] == [POSTER, CO, APPROVER])
check("week number starts at 1", db.week_number(G) == 1)

results = wk.render_weekly_results(g2, db.week_number(G), db.now() - 604800, db.now(), rows_now, cfgw)
check("results title", "WEEK 1 RESULTS" in results.title)
check("winner crowned", "👑" in results.description and "Rafi" in results.description)
check("standings field", any(f.name == "Final standings" for f in results.fields))
check("totals computed from live rows", any(f.value == "**35**" for f in results.fields))
check("results within limits", len(results) < 6000)

empty_week = wk.render_weekly_results(g2, 2, db.now() - 100, db.now(), [], cfgw)
check("empty week renders", "No points were earned" in empty_week.description)

# simulate the reset: credit the winner, bump the counter, wipe
db.credit_week_win(G, POSTER)
db.set_state(G, "week_number", db.week_number(G) + 1)
life_before = db.get_user_stats(G, POSTER, "lifetime")["points"]
db.reset_leaderboard(G, "weekly")

check("weeks_won incremented", db.weeks_won(G, POSTER) == 1)
check("weekly wiped", db.leaderboard_size(G, "weekly") == 0)
check("lifetime survives", db.get_user_stats(G, POSTER, "lifetime")["points"] == life_before)
check("week number advanced", db.week_number(G) == 2)
check("nothing archived to disk", not hasattr(db, "archive_week") and not hasattr(db, "week_standings"))

# --------------------------------------------------------------------------- #
print("\n[8] Partner cooldown")

CD_HOURS = 24
db._q("DELETE FROM partnerships WHERE guild_id = ?", (G,))

cd_id = db.create_partnership(
    guild_id=G, dedupe_key="guild:777", invite_code="abc123",
    target_guild_id=777, target_name="Gaming Hub",
    source_channel_id=10, source_message_id=1, poster_id=POSTER,
)
db.update_partnership(cd_id, status="approved", resolved_at=db.now() - 3600)  # 1h ago

hit = db.active_cooldown(G, "guild:777", "Gaming Hub", "abc123", CD_HOURS)
check("cooldown matches by server id", hit is not None and hit["id"] == cd_id)
check(
    "cooldown matches a DIFFERENT invite code for the same server",
    db.active_cooldown(G, "guild:777", None, "zzzzz", CD_HOURS) is not None,
)
check(
    "cooldown matches by server name when id is unknown",
    db.active_cooldown(G, "code:unknown", "gaming hub", "unknown", CD_HOURS) is not None,
)
check(
    "cooldown matches by invite code alone",
    db.active_cooldown(G, "code:abc123", None, "abc123", CD_HOURS) is not None,
)
check(
    "unrelated server is not on cooldown",
    db.active_cooldown(G, "guild:888", "Other Place", "qqq", CD_HOURS) is None,
)

ready_at = int(hit["resolved_at"]) + CD_HOURS * 3600
check("23h remaining", 22 * 3600 < ready_at - db.now() <= 23 * 3600)

db.update_partnership(cd_id, resolved_at=db.now() - 25 * 3600)
check(
    "cooldown expires after 24h",
    db.active_cooldown(G, "guild:777", "Gaming Hub", "abc123", CD_HOURS) is None,
)

db.update_partnership(cd_id, resolved_at=db.now() - 3600, status="rejected")
check(
    "rejected partnerships do not start a cooldown",
    db.active_cooldown(G, "guild:777", "Gaming Hub", "abc123", CD_HOURS) is None,
)
db.update_partnership(cd_id, status="approved")
check("hours=0 disables matching", db.active_cooldown(G, "guild:777", "Gaming Hub", "abc123", 0) is None)

check("humanize 23h", utils.humanize_seconds(23 * 3600 + 59) == "23h")
check("humanize 1d 2h", utils.humanize_seconds(26 * 3600) == "1d 2h")
check("humanize minutes", utils.humanize_seconds(90 * 60) == "1h 30m")
check("humanize seconds", utils.humanize_seconds(45) == "45s")
check("humanize zero", utils.humanize_seconds(-5) == "0s")

# --------------------------------------------------------------------------- #
print("\n[9] Proof reminder logic")

import flow  # noqa: E402
from cogs.partnership_cog import PartnershipCog as PC  # noqa: E402


class FakeAttachment:
    def __init__(self, ct="image/png", fn="shot.png"):
        self.content_type, self.filename, self.url = ct, fn, "http://cdn/shot.png"


class FakeMsg:
    def __init__(self, author_id, attachments=()):
        self.author = type("A", (), {"id": author_id, "bot": False})()
        self.attachments = list(attachments)
        self.embeds = []


check("image detected", flow.message_has_image(FakeMsg(1, [FakeAttachment()])) is not None)
check("text only -> no image", flow.message_has_image(FakeMsg(1)) is None)
check(
    "non-image attachment ignored",
    flow.message_has_image(FakeMsg(1, [FakeAttachment("application/pdf", "doc.pdf")])) is None,
)
check(
    "image detected by extension when content_type missing",
    flow.message_has_image(FakeMsg(1, [FakeAttachment(None, "proof.JPG")])) is not None,
)

nag_pid = db.create_partnership(
    guild_id=G, dedupe_key="code:nag", invite_code="nag", poster_id=POSTER,
    source_channel_id=1, source_message_id=1, target_name="Nag Server",
)
nag_row = db.get_partnership(nag_pid)
check("nag while proof missing", nag_row["proof_msg_id"] is None and nag_row["status"] == "pending")

db.update_partnership(nag_pid, proof_msg_id=999)
nag_row = db.get_partnership(nag_pid)
check("no nag once proof exists", bool(nag_row["proof_msg_id"]) is True)

db.update_partnership(nag_pid, status="approved")
check("no nag once resolved", db.get_partnership(nag_pid)["status"] != "pending")

check("nag tracker exists", isinstance(PC(bot)._nags, dict))

# --------------------------------------------------------------------------- #
print("\n[10] Thread + ad deletion on decision")

check("delete_thread helper exists", callable(flow.delete_thread))
check("delete_source_ad helper exists", callable(flow.delete_source_ad))
check("schedule_thread_delete helper exists", callable(flow.schedule_thread_delete))

# an APPROVED partnership that loses its thread must keep its status,
# otherwise deleting the thread would silently cancel the cooldown
keep_id = db.create_partnership(
    guild_id=G, dedupe_key="guild:9001", invite_code="keep", target_guild_id=9001,
    target_name="Keeper", source_channel_id=1, source_message_id=2, poster_id=POSTER,
)
db.update_partnership(keep_id, thread_id=55555, status="approved", resolved_at=db.now() - 60)
check("cooldown active before deletion",
      db.active_cooldown(G, "guild:9001", "Keeper", "keep", 24) is not None)

# simulate what delete_thread does to the row
db.update_partnership(keep_id, thread_id=None, control_msg_id=None)
after = db.get_partnership(keep_id)
check("thread id cleared", after["thread_id"] is None)
check("status still approved after thread deletion", after["status"] == "approved")
check("cooldown SURVIVES thread deletion",
      db.active_cooldown(G, "guild:9001", "Keeper", "keep", 24) is not None)
check("deleted thread no longer resolves", db.get_partnership_by_thread(55555) is None)

# a PENDING partnership losing its thread is still cancelled, freeing the key
pend_id = db.create_partnership(
    guild_id=G, dedupe_key="guild:9002", invite_code="pend", target_guild_id=9002,
    target_name="Pending", source_channel_id=1, source_message_id=3, poster_id=POSTER,
)
db.update_partnership(pend_id, thread_id=66666)
check("pending is an open duplicate", db.find_open_partnership(G, "guild:9002") is not None)
db.update_partnership(pend_id, status="cancelled", reason="thread deleted", thread_id=None)
check("cancelled frees the dedupe key", db.find_open_partnership(G, "guild:9002") is None)
check("cancelled starts no cooldown",
      db.active_cooldown(G, "guild:9002", "Pending", "pend", 24) is None)

# the source ad reference survives for the rejection flow
rej_id = db.create_partnership(
    guild_id=G, dedupe_key="code:rej", invite_code="rej", poster_id=POSTER,
    source_channel_id=4242, source_message_id=7777, target_name="Rejected Co",
)
rej = db.get_partnership(rej_id)
check("source message tracked for ad deletion",
      rej["source_channel_id"] == 4242 and rej["source_message_id"] == 7777)
db.update_partnership(rej_id, status="rejected", reason="bad proof", resolved_at=db.now())
check("rejection recorded", db.get_partnership(rej_id)["status"] == "rejected")
check("rejected starts no cooldown",
      db.active_cooldown(G, "code:rej", "Rejected Co", "rej", 24) is None)

# sweep should pick up decided partnerships whose thread outlived the grace window
stale_id = db.create_partnership(
    guild_id=G, dedupe_key="code:stale", invite_code="stale", poster_id=POSTER,
    source_channel_id=1, source_message_id=9,
)
db.update_partnership(stale_id, thread_id=88888, status="approved", resolved_at=db.now() - 600)
stale_rows = [
    r for r in db.list_partnerships(G, "approved", 25)
    if r["thread_id"] and r["resolved_at"] and db.now() - r["resolved_at"] > 75
]
check("sweep finds stale threads", any(r["id"] == stale_id for r in stale_rows))

# --------------------------------------------------------------------------- #
print("\n[11] Mass-ping filter")

ping_cases = {
    "hey @everyone check this out": "everyone",
    "@everyone": "everyone",
    "yo @here quick": "here",
    "partner with us @EVERYONE": "everyone",
    "line one\n@everyone": "everyone",
    "nothing to see": None,
    "@everyonee is not a ping": None,
    "@heres not a ping": None,
    # Discord fires the ping even mid-word, so we deliberately match it too
    "email me at a@everyone.com": "everyone",
    "`@everyone` inside code": None,
    "```\n@everyone\n```": None,
    "\\@everyone escaped": None,
    "discord.gg/abc normal ad": None,
}
for text, expected in ping_cases.items():
    got = utils.find_mass_ping(text)
    check(f"ping: {text[:38]!r}", got == expected, f"-> got {got}, expected {expected}")

check("@here ignored when disabled", utils.find_mass_ping("yo @here", include_here=False) is None)
check("@everyone still caught when here disabled",
      utils.find_mass_ping("yo @everyone", include_here=False) == "everyone")
check("code stripping", "@everyone" not in utils.strip_code("`@everyone`"))
check("text outside code survives", "ping" in utils.strip_code("ping `@everyone`"))

check("filter method exists", callable(PC(bot)._check_mass_ping))
check("scope helper exists", callable(PC(bot)._in_scope))

# --- who is allowed to mass ping ---------------------------------------- #
class _Perms:
    def __init__(self, admin=False, manage_guild=False):
        self.administrator = admin
        self.manage_guild = manage_guild


class _FakeGuild:
    def __init__(self, owner_id):
        self.id = 1
        self.owner_id = owner_id


class _FakeMember:
    def __init__(self, uid, admin=False, roles=()):
        self.id = uid
        self._perms = _Perms(admin=admin, manage_guild=admin)
        self._roles = roles

    @property
    def guild_permissions(self):
        return self._perms

    @property
    def roles(self):
        return [type("R", (), {"id": r})() for r in self._roles]


class _FakeMsg:
    def __init__(self, author, owner_id=1000):
        self.author = author
        self.guild = _FakeGuild(owner_id)


def _cfgwith(**over):
    base = dict(cfg.values)
    base.update(over)
    return config.Config(path="x", mtime=0, raw={}, values=base)


OWNER, ADMIN, APPROVER, RANDOM = 1000, 1001, 1002, 1003
owner_m = _FakeMember(OWNER)
admin_m = _FakeMember(ADMIN, admin=True)
appr_m = _FakeMember(APPROVER, roles=(cfg["approver_role_id"],))
rand_m = _FakeMember(RANDOM)

strict = _cfgwith(antiping_exempt_owner=1, antiping_exempt_admins=0,
                  antiping_exempt_approvers=0, antiping_exempt_users=())
ex = PC._ping_exempt
check("owner is exempt", ex(_FakeMsg(owner_m), strict) is True)
check("admin is NOT exempt", ex(_FakeMsg(admin_m), strict) is False)
check("approver is NOT exempt", ex(_FakeMsg(appr_m), strict) is False)
check("random member is NOT exempt", ex(_FakeMsg(rand_m), strict) is False)

loose = _cfgwith(antiping_exempt_owner=1, antiping_exempt_admins=1,
                 antiping_exempt_approvers=1, antiping_exempt_users=(RANDOM,))
check("admin exempt when enabled", ex(_FakeMsg(admin_m), loose) is True)
check("approver exempt when enabled", ex(_FakeMsg(appr_m), loose) is True)
check("listed user exempt", ex(_FakeMsg(rand_m), loose) is True)

noone = _cfgwith(antiping_exempt_owner=0, antiping_exempt_admins=0,
                 antiping_exempt_approvers=0, antiping_exempt_users=())
check("owner filtered when exempt_owner off", ex(_FakeMsg(owner_m), noone) is False)

# --- the bot can apply the permission fix itself ------------------------- #
from cogs import admin_cog as ac  # noqa: E402

check("apply_ping_lock exists", callable(ac.apply_ping_lock))
check("fix button exists", issubclass(ac.FixPingsButton, discord.ui.View))

ok_embed = ac._fix_embed(["#partnerships — ✅ locked"], [], server_wide=False)
check("fix embed green on success", ok_embed.colour.value == utils.COLOR_APPROVED)
check("fix embed lists applied", any(f.name == "✅ Applied" for f in ok_embed.fields))
check("fix embed hints server_wide", "server_wide" in (ok_embed.footer.text or ""))

bad_embed = ac._fix_embed([], ["#partnerships — I need **Manage Permissions**"], server_wide=True)
check("fix embed red on failure", bad_embed.colour.value == utils.COLOR_REJECTED)
check("fix embed shows manual steps", any(f.name == "Fix it by hand" for f in bad_embed.fields))
check("no server_wide hint when already server wide", bad_embed.footer.text is None)

# --------------------------------------------------------------------------- #
print("\n[12] Storage housekeeping")

before = db.db_size_bytes()
check("db size reported", before > 0)

old_id = db.create_partnership(
    guild_id=G, dedupe_key="code:old", invite_code="old", poster_id=POSTER,
    source_channel_id=1, source_message_id=1,
)
db._q("UPDATE partnerships SET status='approved', resolved_at=? WHERE id=?",
      (db.now() - 200 * 86400, old_id))
pending_id = db.create_partnership(
    guild_id=G, dedupe_key="code:keepme", invite_code="keepme", poster_id=POSTER,
    source_channel_id=1, source_message_id=1,
)
removed_p, removed_l = db.prune(G, 90, 30)
check("old record pruned", db.get_partnership(old_id) is None)
check("pending record kept", db.get_partnership(pending_id) is not None)
check("prune reports a count", removed_p >= 1)
check("prune with 0 keeps everything", db.prune(G, 0, 0) == (0, 0))

# --------------------------------------------------------------------------- #
print("\n[13] Embed rendering")
import flow  # noqa: E402


class FakeGuild:
    id = G
    icon = None


emb_pid = db.create_partnership(
    guild_id=G, dedupe_key="code:emb", invite_code="emb", poster_id=POSTER,
    source_channel_id=1, source_message_id=2, target_name="Embed Server",
)
embed = flow.build_control_embed(FakeGuild(), db.get_partnership(emb_pid), db.get_config())
check("embed builds", embed.title == f"🤝 Partnership #{emb_pid}")
check("embed has fields", len(embed.fields) >= 4)
check("status label present", any("Status" == f.name for f in embed.fields))

# --------------------------------------------------------------------------- #
print("\n[14] Loophole regressions")


class _Att:
    def __init__(self, filename, ctype=None):
        self.filename = filename
        self.content_type = ctype
        self.url = f"https://cdn.example/{filename}"


class _EmbImg:
    def __init__(self, url):
        self.url = url


class _Emb:
    def __init__(self, url):
        self.image = _EmbImg(url)
        self.thumbnail = None


class _ProofMsg:
    def __init__(self, atts=(), embs=()):
        self.attachments = list(atts)
        self.embeds = list(embs)


# --- proof can't be a pasted link when attachment_only is on ------------- #
upload = _ProofMsg(atts=[_Att("shot.png", "image/png")])
pasted = _ProofMsg(embs=[_Emb("https://i.imgur.com/stolen.png")])
check("real upload counts as proof",
      flow.message_has_image(upload, attachments_only=True) is not None)
check("pasted link REJECTED when attachment_only",
      flow.message_has_image(pasted, attachments_only=True) is None)
check("pasted link allowed when attachment_only off",
      flow.message_has_image(pasted, attachments_only=False) is not None)
check("non-image attachment ignored",
      flow.message_has_image(_ProofMsg(atts=[_Att("ad.txt", "text/plain")]),
                             attachments_only=True) is None)
check("attachment_only defaults on", db.get_config()["proof_attachment_only"] == 1)

# --- double approve / approve-after-reject races ------------------------- #
race_pid = db.create_partnership(
    guild_id=G, dedupe_key="code:race", invite_code="race", poster_id=POSTER,
    source_channel_id=1, source_message_id=2, target_name="Race Server",
)
check("first claim wins", db.claim_partnership(race_pid, "approved", APPROVER) is True)
check("second claim LOSES", db.claim_partnership(race_pid, "approved", 999) is False)
check("reject can't steal an approved one",
      db.claim_partnership(race_pid, "rejected", 999) is False)
check("status survives the losing claim",
      db.get_partnership(race_pid)["status"] == "approved")
check("winner recorded once",
      db.get_partnership(race_pid)["approver_id"] == APPROVER)

rej_pid = db.create_partnership(
    guild_id=G, dedupe_key="code:race2", invite_code="race2", poster_id=POSTER,
    source_channel_id=1, source_message_id=2,
)
check("reject claim wins first", db.claim_partnership(rej_pid, "rejected", APPROVER, "bad") is True)
check("double reject blocked", db.claim_partnership(rej_pid, "rejected", APPROVER, "bad") is False)
check("reason stored", db.get_partnership(rej_pid)["reason"] == "bad")

# --- deleting the screenshot re-locks approval --------------------------- #
pf_pid = db.create_partnership(
    guild_id=G, dedupe_key="code:proof", invite_code="proof", poster_id=POSTER,
    source_channel_id=1, source_message_id=2,
)
db.update_partnership(pf_pid, proof_msg_id=5555, proof_url="https://cdn/x.png")
check("proof findable by message id", db.get_partnership_by_proof(5555)["id"] == pf_pid)
check("unrelated delete ignored", db.clear_proof(pf_pid, 4444) is False)
check("proof still set after unrelated delete",
      db.get_partnership(pf_pid)["proof_msg_id"] == 5555)
check("deleting the proof clears it", db.clear_proof(pf_pid, 5555) is True)
check("proof url cleared", db.get_partnership(pf_pid)["proof_url"] is None)
check("approve re-locks without proof",
      views.build_control_view(db.get_partnership(pf_pid), db.get_config()).children[0].item.disabled)
check("clearing twice is a no-op", db.clear_proof(pf_pid, 5555) is False)

# --- nobody can hand out points by hand --------------------------------- #
_cmds = set()
for _c in bot.tree.walk_commands():
    _cmds.add(_c.qualified_name)
check("no /pointsadmin group", not any(c.startswith("pointsadmin") for c in _cmds),
      f"found: {[c for c in _cmds if c.startswith('pointsadmin')]}")
check("/partnership add can't name someone else",
      "poster" not in {
          p.name for c in bot.tree.walk_commands()
          if c.qualified_name == "partnership add"
          for p in getattr(c, "parameters", ())
      })
check("/partnership revoke exists", "partnership revoke" in _cmds)

# --- revoke reverses exactly what was awarded, from the ledger ---------- #
rv_pid = db.create_partnership(
    guild_id=G, dedupe_key="code:revoke", invite_code="revoke", poster_id=POSTER,
    source_channel_id=1, source_message_id=2, target_name="Revoke Server",
)
db.claim_partnership(rv_pid, "approved", APPROVER)
before_poster = db.get_user_stats(G, POSTER)["points"]
before_appr = db.get_user_stats(G, APPROVER)["points"]
_rv_count_before = db.get_user_stats(G, POSTER)["partnerships"]
db.add_points(G, POSTER, 2, reason="approved", actor_id=APPROVER, pship_id=rv_pid, partnerships=1)
db.add_points(G, APPROVER, 1, reason="approved", actor_id=APPROVER, pship_id=rv_pid, approvals=1)
check("points landed", db.get_user_stats(G, POSTER)["points"] == before_poster + 2)

rows = db.revoke_partnership_points(rv_pid, APPROVER)
check("revoke touched both members", len(rows) == 2)
check("poster back to before", db.get_user_stats(G, POSTER)["points"] == before_poster)
check("approver back to before", db.get_user_stats(G, APPROVER)["points"] == before_appr)
check("revoke is idempotent", db.revoke_partnership_points(rv_pid, APPROVER) == [])
check("still back to before after double revoke",
      db.get_user_stats(G, POSTER)["points"] == before_poster)
check("partnership counter decremented too",
      db.get_user_stats(G, POSTER)["partnerships"] == _rv_count_before)
check("ledger nets to zero", db.partnership_point_ledger(rv_pid) == [])

# revoking frees the partner from cooldown
db.update_partnership(rv_pid, status="revoked")
check("revoked partner is off cooldown",
      db.active_cooldown(G, "code:revoke", "Revoke Server", "revoke", 24) is None)

# --- who gets ADDED to the private thread -------------------------------- #
check("approver role added by default", cfg["add_approver_role"] == 1)
check("staff role NOT added by default", cfg["add_staff_role"] == 0)
check("member cap parsed", cfg["max_staff_added"] == 40)


def _added_roles(c):
    """Mirror of the role list flow.create_partnership_thread walks."""
    rids = []
    if c["add_approver_role"] and c["approver_role_id"]:
        rids.append(c["approver_role_id"])
    if c["add_staff_role"] and c["staff_role_id"]:
        rids.append(c["staff_role_id"])
    return list(dict.fromkeys(rids))


check("only the approver role is walked", _added_roles(cfg) == [cfg["approver_role_id"]])
_both = config.Config(path="x", mtime=0, raw={}, values={**cfg.values, "add_staff_role": 1})
check("staff role joins the list when enabled",
      _added_roles(_both) == [cfg["approver_role_id"], cfg["staff_role_id"]])
_dupe = config.Config(path="x", mtime=0, raw={}, values={
    **cfg.values, "add_staff_role": 1, "staff_role_id": cfg["approver_role_id"]})
check("same role not walked twice", len(_added_roles(_dupe)) == 1)
_nobody = config.Config(path="x", mtime=0, raw={}, values={
    **cfg.values, "add_approver_role": 0, "add_staff_role": 0})
check("nobody added when both are off", _added_roles(_nobody) == [])

# --- who gets pinged when a thread opens --------------------------------- #
check("poster pinged by default", cfg["ping_poster"] == 1)
check("staff role NOT pinged by default", cfg["ping_staff_role"] == 0)
check("approver role pinged by default", cfg["ping_approver_role"] == 1)


def _ping_line(c, poster_id=999):
    """Mirror of the ping assembly in flow.create_partnership_thread."""
    out = []
    if c["ping_poster"]:
        out.append(f"<@{poster_id}>")
    rids = []
    if c["ping_staff_role"] and c["staff_role_id"]:
        rids.append(c["staff_role_id"])
    if c["ping_approver_role"] and c["approver_role_id"]:
        rids.append(c["approver_role_id"])
    out += [f"<@&{r}>" for r in dict.fromkeys(rids)]
    return " ".join(out)


_line = _ping_line(cfg)
check("ping line has the poster", "<@999>" in _line)
check("ping line has the approver role", f"<@&{cfg['approver_role_id']}>" in _line)
check("ping line has NO staff role", f"<@&{cfg['staff_role_id']}>" not in _line)

_same = config.Config(path="x", mtime=0, raw={}, values={
    **cfg.values, "ping_staff_role": 1, "approver_role_id": cfg["staff_role_id"]})
check("same role isn't pinged twice", _ping_line(_same).count(f"<@&{cfg['staff_role_id']}>") == 1)

_none = config.Config(path="x", mtime=0, raw={}, values={
    **cfg.values, "ping_poster": 0, "ping_staff_role": 0, "ping_approver_role": 0})
check("all pings off produces an empty line", _ping_line(_none) == "")

# --- weekly quota -------------------------------------------------------- #
check("quota channel parsed", cfg["quota_channel_id"] == 15)
check("quota target parsed", cfg["quota_target"] == 5)
check("quota metric default", cfg["quota_metric"] == "partnerships")
_qm = config._build({"quota": {"count": "POINTS"}}, "x", 0)
check("quota metric accepts points", _qm["quota_metric"] == "points")
_qb = config._build({"quota": {"count": "bananas"}}, "x", 0)
check("bad quota metric falls back", _qb["quota_metric"] == "partnerships")
_qoff = config._build({"channels": {"quota": 0}, "quota": {"enabled": True}}, "x", 0)
check("quota disables itself with no channel", _qoff["quota_enabled"] == 0)
_qzero = config._build({"channels": {"quota": 9}, "quota": {"target": 0}}, "x", 0)
check("quota target 0 disables it", _qzero["quota_enabled"] == 0)

check("progress bar empty", utils.progress_bar(0, 5) == "░" * 10)
check("progress bar full", utils.progress_bar(5, 5) == "█" * 10)
check("progress bar half", utils.progress_bar(5, 10).count("█") == 5)
check("progress bar never overflows", len(utils.progress_bar(99, 5)) == 10)
check("progress bar caps at full", utils.progress_bar(99, 5) == "█" * 10)
check("progress bar survives 0 target", len(utils.progress_bar(3, 0)) == 10)

QUSER = 7777
for _ in range(3):
    db.add_points(G, QUSER, 2, reason="quota test", pship_id=None, partnerships=1)
done, target, left = flow.quota_progress(G, QUSER, cfg)
check("quota counts partnerships", done == 3)
check("quota target returned", target == 5)
check("quota remaining", left == 2)

_pts_cfg = config.Config(path="x", mtime=0, raw={},
                         values={**cfg.values, "quota_metric": "points"})
done_p, _, left_p = flow.quota_progress(G, QUSER, _pts_cfg)
check("quota can count points instead", done_p == 6)
check("quota overshoot clamps to 0 remaining", left_p == 0)

emb = flow.build_quota_embed(QUSER, 3, 5, cfg)
check("quota embed shows progress", "3/5" in (emb.fields[0].name or ""))
check("quota embed says how many left", "2 partnerships" in (emb.description or ""))
check("quota embed is pending colour", emb.colour.value == utils.COLOR_PENDING)

done_emb = flow.build_quota_embed(QUSER, 5, 5, cfg)
check("complete embed celebrates", "complete" in (done_emb.description or "").lower())
check("complete embed is green", done_emb.colour.value == utils.COLOR_APPROVED)
over_emb = flow.build_quota_embed(QUSER, 8, 5, cfg)
check("overshoot embed reports the extra", "**3** over" in (over_emb.description or ""))

check("singular wording", "1 partnership left" in (flow.build_quota_embed(QUSER, 4, 5, cfg).description or "")
      or "1 partnership" in (flow.build_quota_embed(QUSER, 4, 5, cfg).description or ""))
check("/quota check registered", "quota check" in {c.qualified_name for c in bot.tree.walk_commands()})
check("/quota list registered", "quota list" in {c.qualified_name for c in bot.tree.walk_commands()})

# --- no dead keys in the shipped template -------------------------------- #
import tomllib  # noqa: E402

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_tmpl = tomllib.load(open(os.path.join(_root, "config.example.toml"), "rb"))
_src = open(os.path.join(_root, "config.py")).read()


def _walk(d, pre=""):
    for k, v in d.items():
        key = f"{pre}{k}"
        if isinstance(v, dict):
            yield from _walk(v, key + ".")
        else:
            yield key


_dead = [k for k in _walk(_tmpl) if f'"{k}"' not in _src]
check("template has no keys the code ignores", _dead == [], f"dead: {_dead}")


# --------------------------------------------------------------------------- #
print(f"\n{'=' * 52}")
print(f"  {PASS} passed, {FAIL} failed")
print(f"{'=' * 52}\n")
sys.exit(1 if FAIL else 0)
