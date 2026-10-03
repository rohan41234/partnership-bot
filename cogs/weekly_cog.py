"""
Weekly leaderboard reset.

On the configured day/time the bot:
  1. freezes the current standings into the archive
  2. posts a results embed to [channels] weekly_results
  3. zeroes the weekly scores (lifetime totals are untouched)

If the bot was offline at reset time it catches up on the next start.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import db
import utils

log = logging.getLogger("partnership.weekly")

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TICK_SECONDS = 30

PODIUM = ("🥇", "🥈", "🥉")


def next_reset_after(ts: int, cfg) -> int:
    """Timestamp of the next configured reset strictly after `ts`."""
    tz = ZoneInfo(cfg["weekly_tz"])
    base = datetime.fromtimestamp(ts, tz)
    target = DAYS.index(cfg["weekly_day"])

    candidate = base.replace(
        hour=cfg["weekly_hour"], minute=cfg["weekly_minute"], second=0, microsecond=0
    )
    candidate += timedelta(days=(target - candidate.weekday()) % 7)
    if candidate <= base:
        candidate += timedelta(days=7)
    return int(candidate.timestamp())


def ensure_schedule(guild_id: int, cfg) -> int:
    """Make sure the reset clock exists; returns the next reset timestamp."""
    nxt = db.get_state_int(guild_id, "next_reset_at", 0)
    if not nxt:
        now = db.now()
        if not db.get_state_int(guild_id, "week_started_at", 0):
            db.set_state(guild_id, "week_started_at", now)
        nxt = next_reset_after(now, cfg)
        db.set_state(guild_id, "next_reset_at", nxt)
    return nxt


def render_weekly_results(
    guild: discord.Guild, number: int, started: int, ended: int, rows, cfg
) -> discord.Embed:
    """The 'week is over' post. Built from live data — nothing is read from disk."""
    embed = discord.Embed(
        title=f"📅  WEEK {number} RESULTS",
        colour=0xF1C40F,
        timestamp=discord.utils.utcnow(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    period = f"<t:{started}:D> → <t:{ended}:D>"

    if not rows:
        embed.description = f"{period}\n\n```\n   No points were earned this week\n```"
        embed.set_footer(text=f"{guild.name} · scores reset to 0")
        return embed

    winner_id = rows[0]["user_id"]
    winner = guild.get_member(winner_id)
    winner_name = winner.display_name if winner else f"User {winner_id}"
    wins = db.weeks_won(guild.id, winner_id)

    embed.description = (
        f"{period}\n\n"
        f"### 👑  {utils.truncate(winner_name, 32)}\n"
        f"**{rows[0]['points']} points** · {rows[0]['partnerships']} partnerships"
        + (f" · 🏅 {utils.plural(wins, 'weekly win')}" if wins > 1 else "")
    )

    top = rows[: cfg["weekly_top"]]
    lines = []
    for i, r in enumerate(top):
        member = guild.get_member(r["user_id"])
        name = member.display_name if member else f"User {r['user_id']}"
        icon = PODIUM[i] if i < 3 else f"`{i + 1:>2}`"
        lines.append(
            f"{icon} **{utils.truncate(name, 24)}** — `{r['points']} pts` "
            f"· {r['partnerships']}🤝 · {r['approvals']}✅"
        )
    embed.add_field(name="Final standings", value="\n".join(lines), inline=False)

    if len(rows) > len(top):
        embed.add_field(
            name="\u200b",
            value=f"*…and {utils.plural(len(rows) - len(top), 'other member')} also scored.*",
            inline=False,
        )

    embed.add_field(name="Total points", value=f"**{sum(r['points'] for r in rows):,}**", inline=True)
    embed.add_field(
        name="Partnerships", value=f"**{sum(r['partnerships'] for r in rows):,}**", inline=True
    )
    embed.add_field(name="Staff scored", value=f"**{len(rows)}**", inline=True)

    nxt = db.get_state_int(guild.id, "next_reset_at", 0)
    embed.add_field(
        name="\u200b",
        value=(
            "🔄 Weekly scores are now **back to zero** — good luck this week!\n"
            + (f"⏰ Next reset <t:{nxt}:R> (<t:{nxt}:f>)" if nxt else "")
        ),
        inline=False,
    )
    embed.set_footer(text=f"{guild.name} · all-time totals are unaffected")
    return embed


class WeeklyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.ticker.start()

    async def cog_unload(self):
        self.ticker.cancel()

    # ------------------------------------------------------------------ #
    #  Scheduler
    # ------------------------------------------------------------------ #

    @tasks.loop(seconds=TICK_SECONDS)
    async def ticker(self):
        cfg = db.get_config()
        if not cfg["guild_id"]:
            return
        guild = self.bot.get_guild(cfg["guild_id"])
        if guild is None:
            return

        await self._sweep_threads(guild, cfg)
        await self._maybe_prune(guild, cfg)

        nxt = ensure_schedule(guild.id, cfg)
        if not cfg["weekly_enabled"]:
            return
        if db.now() < nxt:
            return

        try:
            await self.do_reset(guild, cfg, manual=False)
        except Exception:
            log.exception("Weekly reset failed")
            # don't get stuck retrying every 30s
            db.set_state(guild.id, "next_reset_at", next_reset_after(db.now(), cfg))

    async def _sweep_threads(self, guild: discord.Guild, cfg) -> None:
        """
        Delete threads of already-decided partnerships that are still hanging
        around — e.g. the bot restarted during the grace period.
        """
        if not (cfg["delete_thread_on_approve"] or cfg["delete_thread_on_reject"]):
            return

        import flow

        grace = cfg["delete_thread_after"] + 60
        wanted = []
        if cfg["delete_thread_on_approve"]:
            wanted.append("approved")
        if cfg["delete_thread_on_reject"]:
            wanted.append("rejected")

        for status in wanted:
            for row in db.list_partnerships(guild.id, status, 25):
                if not row["thread_id"] or not row["resolved_at"]:
                    continue
                if db.now() - int(row["resolved_at"]) < grace:
                    continue
                await flow.delete_thread(self.bot, guild, row["id"])

    async def _maybe_prune(self, guild: discord.Guild, cfg) -> None:
        """Once a day, drop old records so the database stays small."""
        last = db.get_state_int(guild.id, "last_prune_at", 0)
        if db.now() - last < 86400:
            return
        db.set_state(guild.id, "last_prune_at", db.now())

        keep = cfg["keep_partnership_days"]
        # never prune inside the cooldown window
        if keep and cfg["cooldown_enabled"]:
            keep = max(keep, (cfg["cooldown_hours"] // 24) + 1)
        removed_p, removed_l = db.prune(guild.id, keep, cfg["keep_log_days"])
        if removed_p or removed_l:
            log.info(
                "Pruned %d partnership records and %d log rows (db now %.0f KB)",
                removed_p, removed_l, db.db_size_bytes() / 1024,
            )

    @ticker.before_loop
    async def before_ticker(self):
        await self.bot.wait_until_ready()

    @ticker.error
    async def ticker_error(self, exc: BaseException):
        log.exception("Weekly ticker crashed, restarting", exc_info=exc)
        if not self.ticker.is_running():
            self.ticker.start()

    # ------------------------------------------------------------------ #
    #  The reset itself
    # ------------------------------------------------------------------ #

    async def do_reset(self, guild: discord.Guild, cfg, manual: bool = False) -> tuple[int, int]:
        """Post the results, then wipe. Nothing is written to disk."""
        ended = db.now()
        started = db.get_state_int(guild.id, "week_started_at", 0) or (ended - 7 * 86400)
        number = db.week_number(guild.id)

        rows = db.current_standings(guild.id)

        # the only thing a finished week leaves behind: the winner's counter
        if rows:
            db.credit_week_win(guild.id, int(rows[0]["user_id"]))

        # roll the clock forward before announcing so the embed shows the new date
        db.set_state(guild.id, "week_started_at", ended)
        db.set_state(guild.id, "week_number", number + 1)
        db.set_state(guild.id, "next_reset_at", next_reset_after(ended, cfg))

        posted = False
        if cfg["weekly_channel_id"]:
            channel = guild.get_channel(cfg["weekly_channel_id"])
            if isinstance(channel, (discord.TextChannel, discord.Thread)):
                embed = render_weekly_results(guild, number, started, ended, rows, cfg)
                content = f"<@&{cfg['weekly_ping_role_id']}>" if cfg["weekly_ping_role_id"] else None
                try:
                    await channel.send(
                        content=content,
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(roles=True, everyone=False),
                    )
                    posted = True
                except discord.HTTPException as exc:
                    log.warning("Could not post weekly results: %s", exc)
            else:
                log.warning("weekly_results channel %s not found", cfg["weekly_channel_id"])

        if not posted and rows:
            log.warning(
                "Week %s results could not be posted — %d members' scores were still reset",
                number, len(rows),
            )

        db.reset_leaderboard(guild.id, "weekly")
        log.info("Week %s finished for guild %s (%d scored)", number, guild.id, len(rows))

        import flow

        await flow.bump_live_board(self.bot, guild)
        return number, len(rows)

    # ------------------------------------------------------------------ #
    #  /week
    # ------------------------------------------------------------------ #

    group = app_commands.Group(name="week", description="Weekly leaderboard cycle", guild_only=True)

    @group.command(name="status", description="When does the leaderboard reset?")
    async def status(self, interaction: discord.Interaction):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config()
        nxt = ensure_schedule(guild.id, cfg)
        started = db.get_state_int(guild.id, "week_started_at", 0)
        number = db.week_number(guild.id)
        total, ranked, approved = db.guild_totals(guild.id, "weekly")
        size_kb = db.db_size_bytes() / 1024

        embed = discord.Embed(
            title=f"📅 Week {number}",
            colour=utils.COLOR_PENDING if cfg["weekly_enabled"] else utils.COLOR_NEUTRAL,
        )
        embed.add_field(name="Started", value=f"<t:{started}:f>" if started else "—", inline=True)
        if cfg["weekly_enabled"]:
            embed.add_field(name="Resets", value=f"<t:{nxt}:R>\n<t:{nxt}:f>", inline=True)
        else:
            embed.add_field(name="Resets", value="*disabled in config.toml*", inline=True)
        embed.add_field(
            name="Schedule",
            value=f"{cfg['weekly_day'].capitalize()} {cfg['weekly_time']}\n`{cfg['weekly_tz']}`",
            inline=True,
        )
        embed.add_field(name="Points so far", value=f"**{total:,}**", inline=True)
        embed.add_field(name="Partnerships", value=f"**{approved:,}**", inline=True)
        embed.add_field(name="Staff scored", value=f"**{ranked:,}**", inline=True)

        ch = guild.get_channel(cfg["weekly_channel_id"]) if cfg["weekly_channel_id"] else None
        embed.add_field(
            name="Results posted to",
            value=(ch.mention if ch else "*not configured*")
            + f"\n*Standings aren't stored — they're posted here, then wiped. "
            f"Database is {size_kb:.0f} KB.*",
            inline=False,
        )
        await interaction.response.send_message(embed=embed)

    @group.command(name="reset", description="Force the weekly reset right now (admin)")
    @app_commands.default_permissions(manage_guild=True)
    async def reset(self, interaction: discord.Interaction):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config()

        class Confirm(discord.ui.View):
            def __init__(self, cog):
                super().__init__(timeout=60)
                self.cog = cog
                self.author_id = interaction.user.id

            @discord.ui.button(label="Reset now", style=discord.ButtonStyle.danger, emoji="📅")
            async def go(self, i: discord.Interaction, b: discord.ui.Button):
                if i.user.id != self.author_id:
                    await i.response.send_message("Not your confirmation.", ephemeral=True)
                    return
                await i.response.edit_message(content="Running the weekly reset…", view=None)
                number, scored = await self.cog.do_reset(guild, cfg, manual=True)
                await i.followup.send(
                    f"✅ Week **{number}** archived — {utils.plural(scored, 'member')} scored. "
                    "Weekly points are back to zero.",
                    ephemeral=True,
                )

            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, i: discord.Interaction, b: discord.ui.Button):
                await i.response.edit_message(content="Cancelled.", view=None)

        total, ranked, _ = db.guild_totals(guild.id, "weekly")
        await interaction.response.send_message(
            f"⚠️ This ends the current week early.\n"
            f"**{ranked}** members with **{total}** points will be archived and reset to 0.\n"
            "Lifetime totals are kept. Continue?",
            view=Confirm(self),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WeeklyCog(bot))
