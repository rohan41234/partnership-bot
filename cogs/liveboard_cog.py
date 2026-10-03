"""
Live leaderboard — one message in a channel that keeps refreshing itself.

Design goals:
  • looks good (podium, bars, medals, stat strip)
  • cheap (only edits when the standings actually changed)
  • safe (per-guild interval, minimum 30s, survives the message being deleted)
"""

from __future__ import annotations

import hashlib
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db
import utils

log = logging.getLogger("partnership.liveboard")

TICK_SECONDS = 15  # how often we look for guilds that are due an update

# Blocks used for the score bars
BAR_FULL = "█"
BAR_EMPTY = "░"
BAR_WIDTH = 14

PODIUM = ("🥇", "🥈", "🥉")
RANKS = ("④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫", "⑬", "⑭", "⑮")


def _rank_icon(i: int) -> str:
    if i < 3:
        return PODIUM[i]
    if i - 3 < len(RANKS):
        return RANKS[i - 3]
    return f"`{i + 1:>2}`"


def _bar(value: int, top: int) -> str:
    if top <= 0:
        return BAR_EMPTY * BAR_WIDTH
    filled = max(1, round(BAR_WIDTH * value / top)) if value > 0 else 0
    return BAR_FULL * filled + BAR_EMPTY * (BAR_WIDTH - filled)


def render_leaderboard(
    guild: discord.Guild, top_n: int = 10, live: bool = True, scope: str = "weekly"
) -> discord.Embed:
    """Build the pretty leaderboard embed."""
    rows = db.leaderboard(guild.id, top_n, scope=scope)
    total_points, ranked, approved = db.guild_totals(guild.id, scope)
    lifetime = scope == "lifetime"

    title = "🏆  ALL-TIME LEADERBOARD" if lifetime else "🏆  WEEKLY LEADERBOARD"
    embed = discord.Embed(
        title=title,
        colour=0x9B59B6 if lifetime else 0xF1C40F,
        timestamp=discord.utils.utcnow(),
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    if not rows:
        embed.description = (
            "```\n"
            "      No points this week yet\n"
            "```\n"
            "Approve a partnership and the board fills up automatically."
        )
        if live:
            embed.description += "\n" + _week_line(guild)
        embed.set_footer(text=guild.name)
        return embed

    top_score = rows[0]["points"]

    # ---- podium ---------------------------------------------------------- #
    podium_lines = []
    for i, r in enumerate(rows[:3]):
        member = guild.get_member(r["user_id"])
        name = member.display_name if member else f"User {r['user_id']}"
        podium_lines.append(
            f"{_rank_icon(i)}  **{utils.truncate(name, 24)}** — `{r['points']} pts`\n"
            f"　　`{_bar(r['points'], top_score)}`  {r['partnerships']}🤝 · {r['approvals']}✅"
        )

    embed.description = "\n".join(podium_lines) if podium_lines else ""

    # ---- the rest -------------------------------------------------------- #
    rest = rows[3:]
    if rest:
        lines = []
        for i, r in enumerate(rest, start=3):
            member = guild.get_member(r["user_id"])
            name = member.display_name if member else f"User {r['user_id']}"
            lines.append(
                f"{_rank_icon(i)} `{r['points']:>4}` · **{utils.truncate(name, 22)}** "
                f"· {r['partnerships']}🤝"
            )
        embed.add_field(name="\u200b", value="\n".join(lines), inline=False)

    # ---- stat strip ------------------------------------------------------ #
    embed.add_field(name="Total points", value=f"**{total_points:,}**", inline=True)
    embed.add_field(name="Partnerships", value=f"**{approved:,}**", inline=True)
    embed.add_field(name="Ranked staff", value=f"**{ranked:,}**", inline=True)

    if live:
        cfg = db.get_config()
        embed.add_field(
            name="\u200b",
            value=f"{_week_line(guild)}\n🔄 Refreshes every **{cfg['lb_interval']}s**",
            inline=False,
        )
        embed.set_footer(text=f"{guild.name} · live board")
    else:
        embed.set_footer(text=guild.name)

    return embed


def _week_line(guild: discord.Guild) -> str:
    """'Week 4 · resets in 3 days' strip for the live board."""
    cfg = db.get_config()
    number = db.week_number(guild.id)
    if not cfg["weekly_enabled"]:
        return f"📅 **Week {number}**"
    nxt = db.get_state_int(guild.id, "next_reset_at", 0)
    if not nxt:
        return f"📅 **Week {number}**"
    return f"📅 **Week {number}** · resets <t:{nxt}:R>"


def _fingerprint(guild_id: int, top_n: int) -> str:
    """Hash of the standings so we only edit when something really changed."""
    rows = db.leaderboard(guild_id, top_n)
    blob = "|".join(f"{r['user_id']}:{r['points']}:{r['partnerships']}:{r['approvals']}" for r in rows)
    blob += f"|{db.guild_totals(guild_id)}|{db.week_number(guild_id)}"
    return hashlib.md5(blob.encode()).hexdigest()


class LiveBoardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_update: dict[int, float] = {}
        self._last_hash: dict[int, str] = {}

    async def cog_load(self):
        self.ticker.start()

    async def cog_unload(self):
        self.ticker.cancel()

    # ------------------------------------------------------------------ #
    #  The loop
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=TICK_SECONDS)
    async def ticker(self):
        now = time.time()
        cfg = db.get_config()
        gid = cfg["guild_id"]
        if not (gid and cfg["lb_enabled"] and cfg["lb_channel_id"]):
            return

        interval = max(30, int(cfg["lb_interval"] or 60))
        if now - self._last_update.get(gid, 0) < interval:
            return
        self._last_update[gid] = now

        guild = self.bot.get_guild(gid)
        if guild is None:
            return

        # skip the API call entirely when nothing moved
        fp = _fingerprint(gid, cfg["lb_top_n"])
        if self._last_hash.get(gid) == fp:
            return

        try:
            ok = await self.push(guild, cfg)
        except Exception:
            log.exception("Live board update failed for guild %s", gid)
            return
        if ok:
            self._last_hash[gid] = fp

    @ticker.before_loop
    async def before_ticker(self):
        await self.bot.wait_until_ready()

    @ticker.error
    async def ticker_error(self, exc: BaseException):
        # Never let the loop die silently - log it and start again.
        log.exception("Live board ticker crashed, restarting", exc_info=exc)
        if not self.ticker.is_running():
            self.ticker.start()

    # ------------------------------------------------------------------ #
    #  Posting / editing
    # ------------------------------------------------------------------ #

    async def push(self, guild: discord.Guild, cfg=None) -> bool:
        """Edit the live message, re-posting it if it has gone missing."""
        cfg = cfg or db.get_config(guild.id)
        channel = guild.get_channel(cfg["lb_channel_id"]) if cfg["lb_channel_id"] else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False

        embed = render_leaderboard(guild, cfg["lb_top_n"], live=True, scope="weekly")

        message_id = db.get_state_int(guild.id, "lb_message_id", 0)
        if message_id:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=embed, content=None)
                return True
            except discord.NotFound:
                pass  # deleted -> fall through and repost
            except discord.Forbidden:
                log.warning("No permission to edit live board in guild %s", guild.id)
                return False
            except discord.HTTPException:
                return False

        try:
            msg = await channel.send(embed=embed)
            db.set_state(guild.id, "lb_message_id", msg.id)
            try:
                await msg.pin()
            except discord.HTTPException:
                pass
            return True
        except discord.HTTPException as exc:
            log.warning("Could not post live board: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    #  /config leaderboard
    # ------------------------------------------------------------------ #

    group = app_commands.Group(
        name="liveboard",
        description="The auto-updating leaderboard message",
        guild_only=True,
    )

    @group.command(name="refresh", description="Force an immediate refresh")
    async def refresh(self, interaction: discord.Interaction):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        if not utils.is_staff(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message(
                "Staff only — the board refreshes itself anyway.", ephemeral=True
            )
            return
        if not cfg["lb_channel_id"]:
            await interaction.response.send_message(
                "No live board configured — set `[channels] leaderboard` in **config.toml**.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        self._last_hash.pop(guild.id, None)
        ok = await self.push(guild)
        await interaction.followup.send(
            "🔄 Refreshed." if ok else "❌ Couldn't update the board.", ephemeral=True
        )

    @group.command(name="preview", description="See what the live board looks like right now")
    async def preview(self, interaction: discord.Interaction):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        await interaction.response.send_message(
            embed=render_leaderboard(guild, cfg["lb_top_n"], live=False), ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LiveBoardCog(bot))
