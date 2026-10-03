"""/diagnose and /reloadconfig — the only admin commands left.

Everything else is configured in config.toml.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
import db
import utils

log = logging.getLogger("partnership.admin")


async def apply_ping_lock(guild: discord.Guild, cfg, server_wide: bool = False) -> tuple[list[str], list[str]]:
    """
    Deny "Mention @everyone, @here, and All Roles" to @everyone.

    Channel overwrites are applied to every channel the bot manages. Optionally
    the server-wide @everyone role permission is turned off too.
    Returns (done, failed) as human-readable lines.
    """
    done: list[str] = []
    failed: list[str] = []
    everyone = guild.default_role

    targets = [
        ("partnership", cfg["listen_channel_id"]),
        ("threads", cfg["thread_parent_id"]),
        ("leaderboard", cfg["lb_channel_id"]),
        ("weekly results", cfg["weekly_channel_id"]),
        ("quota", cfg["quota_channel_id"]),
        ("logs", cfg["log_channel_id"]),
    ]

    seen: set[int] = set()
    for label, cid in targets:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        channel = guild.get_channel(cid)
        if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
            continue

        if not channel.permissions_for(guild.me).manage_permissions:
            failed.append(f"{channel.mention} — I need **Manage Permissions** there")
            continue

        current = channel.overwrites_for(everyone)
        if current.mention_everyone is False:
            done.append(f"{channel.mention} — already locked")
            continue

        current.mention_everyone = False
        try:
            await channel.set_permissions(
                everyone, overwrite=current, reason="Partnership bot: block mass pings"
            )
            done.append(f"{channel.mention} — ✅ locked")
        except discord.Forbidden:
            failed.append(f"{channel.mention} — Discord refused (my role may be too low)")
        except discord.HTTPException as exc:
            failed.append(f"{channel.mention} — {exc}")

    if server_wide:
        if everyone.permissions.mention_everyone:
            if not guild.me.guild_permissions.manage_roles:
                failed.append("Server-wide — I need the **Manage Roles** permission")
            else:
                perms = everyone.permissions
                perms.update(mention_everyone=False)
                try:
                    await everyone.edit(
                        permissions=perms, reason="Partnership bot: block mass pings server-wide"
                    )
                    done.append("**Server-wide** — ✅ `@everyone` can no longer mass-ping anywhere")
                except discord.Forbidden:
                    failed.append("Server-wide — Discord refused (my role may be too low)")
                except discord.HTTPException as exc:
                    failed.append(f"Server-wide — {exc}")
        else:
            done.append("**Server-wide** — already off")

    return done, failed


def _exempt_summary(cfg) -> str:
    """Human-readable list of who the mass-ping filter ignores."""
    who = []
    if cfg["antiping_exempt_owner"]:
        who.append("owner")
    if cfg["antiping_exempt_admins"]:
        who.append("admins")
    if cfg["antiping_exempt_approvers"]:
        who.append("approvers")
    extra = len(cfg["antiping_exempt_users"])
    if extra:
        who.append(f"{extra} user{'s' if extra != 1 else ''}")
    return (" · exempt: " + ", ".join(who)) if who else " · no exemptions"


class FixPingsButton(discord.ui.View):
    """'Fix it for me' button attached to /diagnose."""

    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id

    @discord.ui.button(label="Lock @everyone pings for me", emoji="🔒", style=discord.ButtonStyle.primary)
    async def fix(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your button.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        cfg = db.get_config()
        done, failed = await apply_ping_lock(interaction.guild, cfg, server_wide=False)
        button.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass
        await interaction.followup.send(
            embed=_fix_embed(done, failed, server_wide=False), ephemeral=True
        )


def _fix_embed(done: list[str], failed: list[str], server_wide: bool) -> discord.Embed:
    embed = discord.Embed(
        title="🔒 Mass-ping lockdown",
        colour=utils.COLOR_REJECTED if failed else utils.COLOR_APPROVED,
        description=(
            "`Mention @everyone, @here, and All Roles` is now denied to `@everyone`.\n"
            "Discord will refuse the ping itself — nobody gets notified."
        ),
    )
    if done:
        embed.add_field(name="✅ Applied", value="\n".join(f"• {d}" for d in done)[:1024], inline=False)
    if failed:
        embed.add_field(
            name="❌ Couldn't apply",
            value="\n".join(f"• {f}" for f in failed)[:1024],
            inline=False,
        )
        embed.add_field(
            name="Fix it by hand",
            value=(
                "Channel → **Edit Channel** → **Permissions** → `@everyone` → set\n"
                "**Mention @everyone, @here, and All Roles** to ✗"
            ),
            inline=False,
        )
    if not server_wide:
        embed.set_footer(text="Run /fixpings server_wide:True to block it in every channel")
    return embed


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="fixpings", description="Deny @everyone the permission to mass-ping"
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        server_wide="Also turn the permission off on the @everyone role for the whole server"
    )
    async def fixpings(self, interaction: discord.Interaction, server_wide: bool = False):
        guild = interaction.guild
        assert guild is not None
        await interaction.response.defer(ephemeral=True)
        cfg = db.get_config()
        done, failed = await apply_ping_lock(guild, cfg, server_wide=server_wide)
        if not done and not failed:
            await interaction.followup.send(
                "Nothing to do — no channels are configured yet in **config.toml**.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=_fix_embed(done, failed, server_wide), ephemeral=True
        )

    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="reloadconfig", description="Re-read config.toml without restarting the bot"
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def reloadconfig(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            cfg = config.load()
        except config.ConfigError as exc:
            await interaction.followup.send(f"❌ **Could not load config.toml**\n```\n{exc}\n```", ephemeral=True)
            return
        except Exception as exc:  # noqa: BLE001
            await interaction.followup.send(f"❌ Unexpected error:\n```\n{exc}\n```", ephemeral=True)
            return

        lines = ["✅ **config.toml reloaded.**"]
        missing = cfg.missing()
        if missing:
            lines.append("\n⚠️ Still missing: " + ", ".join(missing))
        if cfg.warnings:
            lines.append("\n**Warnings:**")
            lines += [f"• {w}" for w in cfg.warnings]
        lines.append("\nRun `/diagnose` for a full check.")
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # ------------------------------------------------------------------ #
    @app_commands.command(name="diagnose", description="Check config.toml, permissions and intents")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def diagnose(self, interaction: discord.Interaction):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config()
        me = guild.me

        issues: list[str] = []
        notes: list[str] = []
        ping_hole = False

        # --- config file -------------------------------------------------- #
        for m in cfg.missing():
            issues.append(f"config.toml: {m} is not set")
        for w in cfg.warnings:
            notes.append(f"config.toml: {w}")

        if cfg["guild_id"] and cfg["guild_id"] != guild.id:
            issues.append(
                f"`guild_id` in config.toml is **{cfg['guild_id']}**, but this server is "
                f"**{guild.id}** — the bot will ignore this server"
            )

        # --- channels ------------------------------------------------------ #
        def chan(cid):
            return guild.get_channel(cid) if cid else None

        listen = chan(cfg["listen_channel_id"])
        parent = chan(cfg["thread_parent_id"])
        board = chan(cfg["lb_channel_id"])
        weekly = chan(cfg["weekly_channel_id"])
        quota = chan(cfg["quota_channel_id"])
        logs = chan(cfg["log_channel_id"])

        if cfg["listen_channel_id"] and not listen:
            issues.append(f"`[channels] partnership` = {cfg['listen_channel_id']} — channel not found")
        elif listen:
            p = listen.permissions_for(me)
            if not p.view_channel:
                issues.append(f"I can't see {listen.mention}")
            elif not p.read_message_history:
                issues.append(f"I can't read history in {listen.mention}")
            else:
                notes.append(f"Listening in {listen.mention}")
            if not p.add_reactions:
                notes.append(f"No **Add Reactions** in {listen.mention} (minor)")

        if isinstance(parent, discord.TextChannel):
            p = parent.permissions_for(me)
            missing = [
                n for n, ok in (
                    ("Create Private Threads", p.create_private_threads),
                    ("Send Messages in Threads", p.send_messages_in_threads),
                ) if not ok
            ]
            if missing:
                issues.append(f"In {parent.mention} I'm missing **{', '.join(missing)}**")
            else:
                notes.append(f"Can open private threads in {parent.mention}")
        elif cfg["thread_parent_id"] and parent is None:
            issues.append(f"`[channels] threads` = {cfg['thread_parent_id']} — channel not found")
        elif parent is not None:
            issues.append("`[channels] threads` must be a normal text channel")

        for key, ch, cid in (
            ("leaderboard", board, cfg["lb_channel_id"]),
            ("weekly_results", weekly, cfg["weekly_channel_id"]),
            ("quota", quota, cfg["quota_channel_id"]),
            ("logs", logs, cfg["log_channel_id"]),
        ):
            if cid and ch is None:
                issues.append(f"`[channels] {key}` = {cid} — channel not found")
            elif isinstance(ch, discord.TextChannel):
                p = ch.permissions_for(me)
                bad = [
                    n for n, ok in (
                        ("Send Messages", p.send_messages),
                        ("Embed Links", p.embed_links),
                        ("Read Message History", p.read_message_history),
                    ) if not ok
                ]
                if bad:
                    issues.append(f"In {ch.mention} I'm missing **{', '.join(bad)}**")
                else:
                    notes.append(f"{key} → {ch.mention}")

        # --- roles ---------------------------------------------------------- #
        staff = guild.get_role(cfg["staff_role_id"]) if cfg["staff_role_id"] else None
        approver = guild.get_role(cfg["approver_role_id"]) if cfg["approver_role_id"] else None
        if cfg["staff_role_id"] and not staff:
            issues.append(f"`[roles] staff` = {cfg['staff_role_id']} — role not found")
        elif staff:
            notes.append(f"Staff {staff.mention} ({len(staff.members)} members)")
        else:
            notes.append("Staff role not set — approvers are treated as staff")
        if cfg["approver_role_id"] and not approver:
            issues.append(f"`[roles] approver` = {cfg['approver_role_id']} — role not found")
        elif approver:
            notes.append(f"Approver {approver.mention} ({len(approver.members)} members)")

        # --- mass-ping protection ------------------------------------------- #
        if cfg["antiping_enabled"] and listen:
            everyone_perms = listen.permissions_for(guild.default_role)
            if everyone_perms.mention_everyone:
                ping_hole = True
                issues.append(
                    f"**@everyone can still ping @everyone in {listen.mention}.** "
                    "I can only delete the message *after* the notification goes out. "
                    "Use the button below (or `/fixpings`) and I'll deny the permission."
                )
            else:
                notes.append(f"Mass pings are blocked by permissions in {listen.mention} ✅")
            mine = listen.permissions_for(me)
            if not mine.manage_messages:
                issues.append(
                    f"No **Manage Messages** in {listen.mention} — I can't delete mass pings, "
                    "rejected ads, or cooldown reposts"
                )

        # --- intents -------------------------------------------------------- #
        if not self.bot.intents.message_content:
            issues.append("**Message Content intent is OFF** — the bot cannot read invite links")
        if not self.bot.intents.members:
            issues.append("**Server Members intent is OFF** — approvers can't be added to private threads")

        # --- weekly ---------------------------------------------------------- #
        if cfg["weekly_enabled"]:
            nxt = db.get_state_int(guild.id, "next_reset_at", 0)
            notes.append(
                f"Weekly reset: {cfg['weekly_day'].capitalize()} {cfg['weekly_time']} "
                f"{cfg['weekly_tz']}" + (f" · next <t:{nxt}:R>" if nxt else "")
            )
        else:
            notes.append("Weekly reset is **disabled**")

        embed = discord.Embed(
            title="🩺 Diagnostics",
            colour=utils.COLOR_REJECTED if issues else utils.COLOR_APPROVED,
            description=f"Config file: `{cfg.path}`",
        )
        embed.add_field(
            name=f"❌ Problems ({len(issues)})" if issues else "✅ No problems found",
            value="\n".join(f"• {i}" for i in issues)[:1024] if issues else "Everything checks out.",
            inline=False,
        )
        if notes:
            embed.add_field(name="Details", value="\n".join(f"• {n}" for n in notes)[:1024], inline=False)
        embed.set_footer(text="Edit config.toml then run /reloadconfig")

        view = FixPingsButton(interaction.user.id) if ping_hole else None
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # ------------------------------------------------------------------ #
    @app_commands.command(name="settings", description="Show the currently loaded settings")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config()

        def ch(cid):
            c = guild.get_channel(cid) if cid else None
            return c.mention if c else ("*off*" if not cid else f"*missing ({cid})*")

        def ro(rid):
            r = guild.get_role(rid) if rid else None
            return r.mention if r else ("*off*" if not rid else f"*missing ({rid})*")

        embed = discord.Embed(
            title="⚙️ Loaded settings",
            description=f"Read from `{cfg.path}` — edit that file, then `/reloadconfig`.",
            colour=utils.COLOR_APPROVED if cfg.ready else utils.COLOR_REJECTED,
        )
        embed.add_field(name="Partnership channel", value=ch(cfg["listen_channel_id"]), inline=True)
        embed.add_field(name="Threads in", value=ch(cfg["thread_parent_id"]), inline=True)
        embed.add_field(name="Audit logs", value=ch(cfg["log_channel_id"]), inline=True)
        embed.add_field(name="Live leaderboard", value=ch(cfg["lb_channel_id"]), inline=True)
        embed.add_field(name="Weekly results", value=ch(cfg["weekly_channel_id"]), inline=True)
        embed.add_field(name="Quota", value=ch(cfg["quota_channel_id"]), inline=True)
        embed.add_field(
            name="Staff role",
            value=ro(cfg["staff_role_id"]) if cfg["staff_role_id"] else "*not set (optional)*",
            inline=True,
        )
        embed.add_field(name="Approver role", value=ro(cfg["approver_role_id"]), inline=True)
        embed.add_field(name="Weekly ping", value=ro(cfg["weekly_ping_role_id"]), inline=True)
        embed.add_field(
            name="Points",
            value=f"staff **{cfg['poster_points']}** · approver **{cfg['approver_points']}**",
            inline=True,
        )
        embed.add_field(
            name="Proof", value="required" if cfg["require_proof"] else "optional", inline=True
        )
        embed.add_field(
            name="Board refresh",
            value=f"{cfg['lb_interval']}s · top {cfg['lb_top_n']}" if cfg["lb_enabled"] else "*off*",
            inline=True,
        )
        embed.add_field(
            name="Weekly quota",
            value=(
                f"**{cfg['quota_target']}** {cfg['quota_metric']}/week"
                + (" · pings" if cfg["quota_ping"] else "")
                if cfg["quota_enabled"] else "*off*"
            ),
            inline=True,
        )
        embed.add_field(
            name="Mass-ping filter",
            value=(
                f"{cfg['antiping_scope']} scope"
                + (" · @here too" if cfg["antiping_here"] else "")
                + _exempt_summary(cfg)
                if cfg["antiping_enabled"] else "*off*"
            ),
            inline=True,
        )
        embed.add_field(
            name="Cooldown",
            value=f"{cfg['cooldown_hours']}h per partner" if cfg["cooldown_enabled"] else "*off*",
            inline=True,
        )
        embed.add_field(
            name="On decision",
            value=(
                ("delete thread" if cfg["delete_thread_on_approve"] else "keep thread")
                + f" after {cfg['delete_thread_after']}s"
                + (" · delete rejected ad" if cfg["delete_ad_on_reject"] else "")
            ),
            inline=True,
        )
        embed.add_field(
            name="Weekly reset",
            value=(
                f"{cfg['weekly_day'].capitalize()} {cfg['weekly_time']} `{cfg['weekly_tz']}`"
                if cfg["weekly_enabled"] else "*off*"
            ),
            inline=False,
        )
        if cfg.warnings:
            embed.add_field(
                name="⚠️ Warnings",
                value="\n".join(f"• {w}" for w in cfg.warnings)[:1024],
                inline=False,
            )
        await interaction.response.send_message(
            embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
