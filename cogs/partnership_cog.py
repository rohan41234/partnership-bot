"""Invite detection, duplicate checking, thread creation, proof watching."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
import flow
import utils

log = logging.getLogger("partnership.cog")



class PartnershipCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}
        # thread_id -> id of the last "post the screenshot" reminder, so we can
        # replace it instead of stacking them up
        self._nags: dict[int, int] = {}

    def _lock_for(self, guild_id: int) -> asyncio.Lock:
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]

    # ------------------------------------------------------------------ #
    #  Listener
    # ------------------------------------------------------------------ #

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        cfg = db.get_config()
        if cfg["guild_id"] and message.guild.id != cfg["guild_id"]:
            return

        # --- mass-ping filter runs before everything else ---------------- #
        if await self._check_mass_ping(message, cfg):
            return

        # --- proof posted inside one of our threads --------------------- #
        if isinstance(message.channel, discord.Thread):
            pship = db.get_partnership_by_thread(message.channel.id)
            if pship:
                await self._handle_thread_message(message, pship, cfg)
            return

        # --- invite posted in the partnership channel ------------------- #
        if not cfg["enabled"] or message.channel.id != cfg["listen_channel_id"]:
            return
        if not db.is_configured(cfg):
            return

        codes = utils.extract_invite_codes(message.content)
        if not codes:
            # also scan embeds (link previews / forwarded content)
            for emb in message.embeds:
                for blob in (emb.description, emb.url, getattr(emb.author, "url", None)):
                    if blob:
                        codes.extend(utils.extract_invite_codes(str(blob)))
            codes = list(dict.fromkeys(codes))
        if not codes:
            return

        async with self._lock_for(message.guild.id):
            # Resolve every link first so the cooldown gate can run before we
            # create anything or ping anybody.
            resolved = []
            for code in codes[:5]:  # safety cap: 5 links per message
                target_id, target_name = await self._resolve_invite(code)
                if target_id == message.guild.id:
                    continue  # our own server
                resolved.append((code, target_id, target_name))

            if not resolved:
                return

            if await self._check_cooldown(message, cfg, resolved):
                return

            created, duplicates, failed = [], [], []

            for code, target_id, target_name in resolved:
                key = utils.dedupe_key_for(target_id, code)
                existing = db.find_open_partnership(message.guild.id, key)
                if existing and await self._thread_alive(message.guild, existing):
                    duplicates.append((existing, target_name or code))
                    continue

                thread = await flow.create_partnership_thread(
                    self.bot, message, cfg, code, target_id, target_name
                )
                if thread:
                    created.append(thread)
                else:
                    failed.append(code)

            await self._react_and_report(message, created, duplicates, failed)

    # ------------------------------------------------------------------ #
    #  Mass-ping filter
    # ------------------------------------------------------------------ #

    def _in_scope(self, message: discord.Message, cfg) -> bool:
        if cfg["antiping_scope"] == "all":
            return True
        channel = message.channel
        if channel.id == cfg["listen_channel_id"]:
            return True
        if isinstance(channel, discord.Thread):
            if channel.parent_id in (cfg["listen_channel_id"], cfg["thread_parent_id"]):
                return True
            if db.get_partnership_by_thread(channel.id) is not None:
                return True
        return False

    @staticmethod
    def _ping_exempt(message: discord.Message, cfg) -> bool:
        """Who is allowed to use @everyone / @here.

        Nobody is exempt by default except the server owner. Admins and
        approvers are NOT exempt unless the config says so, so a rogue
        moderator still gets their mass ping deleted.
        """
        author = message.author
        guild = message.guild

        if guild is not None and cfg["antiping_exempt_owner"]:
            if author.id == guild.owner_id:
                return True

        if author.id in cfg["antiping_exempt_users"]:
            return True

        perms = getattr(author, "guild_permissions", None)
        if perms is not None:  # a Member, not a plain User / webhook
            if cfg["antiping_exempt_admins"] and perms.administrator:
                return True
            if cfg["antiping_exempt_approvers"] and utils.is_approver(author, cfg):
                return True

        return False

    async def _check_mass_ping(self, message: discord.Message, cfg) -> bool:
        """True if the message was an illegal mass ping and has been handled."""
        if not cfg["antiping_enabled"] or not self._in_scope(message, cfg):
            return False

        if self._ping_exempt(message, cfg):
            return False

        kind = utils.find_mass_ping(message.content, include_here=bool(cfg["antiping_here"]))

        # message.mention_everyone is True only when the ping actually fired
        really_pinged = bool(message.mention_everyone)
        if not kind and really_pinged:
            kind = "everyone"

        if not kind and cfg["antiping_roles"] and message.role_mentions:
            allowed = {cfg["staff_role_id"], cfg["approver_role_id"], cfg["weekly_ping_role_id"]}
            if any(r.id not in allowed for r in message.role_mentions):
                kind = "role"

        if not kind:
            return False

        deleted = False
        if cfg["antiping_delete"]:
            try:
                await message.delete()
                deleted = True
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                deleted = False

        label = {"everyone": "@everyone", "here": "@here", "role": "a role ping"}[kind]
        embed = discord.Embed(
            title="🚫 Mass ping removed",
            description=(
                f"{message.author.mention}, **{label}** isn't allowed here.\n"
                "Post your partnership ad without it."
            ),
            colour=utils.COLOR_REJECTED,
        )
        if really_pinged:
            embed.add_field(
                name="⚠️ The ping already went out",
                value=(
                    "Discord delivered that notification before I could react — I can only "
                    "delete the message. Remove **Mention @everyone, @here, and All Roles** "
                    "from the `@everyone` role so Discord blocks it at the source."
                ),
                inline=False,
            )
        if not deleted and cfg["antiping_delete"]:
            embed.set_footer(text="I couldn't delete it — I need Manage Messages here")

        hide = cfg["antiping_notice_delete"]
        try:
            await message.channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                delete_after=hide if hide > 0 else None,
            )
        except discord.HTTPException:
            pass

        log.info(
            "Blocked %s from %s in guild %s (ping fired: %s, deleted: %s)",
            label, message.author.id, message.guild.id, really_pinged, deleted,
        )
        return True

    # ------------------------------------------------------------------ #
    #  Inside a partnership thread
    # ------------------------------------------------------------------ #

    async def _handle_thread_message(self, message: discord.Message, pship, cfg) -> None:
        had_proof = bool(pship["proof_msg_id"])
        is_image = flow.message_has_image(message) is not None

        if is_image:
            await flow.handle_proof(self.bot, message, pship, cfg)
            # proof is in - clear the reminder and never nag again
            await self._clear_nag(message.channel)
            return

        # Already have the screenshot? Then stay quiet, whatever they post.
        if had_proof or pship["status"] != "pending":
            return
        if not cfg["require_proof"]:
            return

        # Only nag the people who owe us the screenshot.
        if message.author.id != pship["poster_id"]:
            return

        await self._nag(message, pship)

    async def _nag(self, message: discord.Message, pship) -> None:
        """Ask for the screenshot, replacing the previous reminder."""
        thread = message.channel
        await self._clear_nag(thread)

        embed = discord.Embed(
            description=(
                f"📸 {message.author.mention} — please upload a **screenshot** showing our ad "
                f"posted on **{utils.truncate(pship['target_name'] or 'their server', 60)}**.\n"
                "Attach it as an image in this thread. The **Approve** button stays locked "
                "until then."
            ),
            colour=utils.COLOR_PROOF,
        )
        try:
            sent = await thread.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            self._nags[thread.id] = sent.id
        except discord.HTTPException:
            pass

    async def _clear_nag(self, thread) -> None:
        msg_id = self._nags.pop(getattr(thread, "id", 0), None)
        if not msg_id:
            return
        try:
            old = await thread.fetch_message(msg_id)
            await old.delete()
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ #
    #  Partner cooldown
    # ------------------------------------------------------------------ #

    async def _check_cooldown(self, message: discord.Message, cfg, resolved) -> bool:
        """
        True if this message hit a cooldown (and was handled).
        Deletion happens first so the message is gone as fast as possible.
        """
        if not cfg["cooldown_enabled"]:
            return False

        hit = None
        for code, target_id, target_name in resolved:
            key = utils.dedupe_key_for(target_id, code)
            row = db.active_cooldown(
                message.guild.id, key, target_name, code, cfg["cooldown_hours"]
            )
            if row is not None:
                hit = (row, target_name or row["target_name"] or code)
                break
        if hit is None:
            return False

        row, name = hit

        # 1. delete immediately - before anything else
        deleted = False
        if cfg["cooldown_delete"]:
            try:
                await message.delete()
                deleted = True
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                deleted = False

        # 2. then explain
        ready_at = int(row["resolved_at"]) + cfg["cooldown_hours"] * 3600
        remaining = max(0, ready_at - db.now())

        embed = discord.Embed(
            title="⏳ Partner on cooldown",
            description=(
                f"**{utils.truncate(name, 60)}** was already partnered "
                f"<t:{int(row['resolved_at'])}:R>.\n\n"
                f"🕒 You can partner with them again **<t:{ready_at}:R>** "
                f"(<t:{ready_at}:f>)\n"
                f"⏱️ Time left: **{utils.humanize_seconds(remaining)}**"
            ),
            colour=utils.COLOR_REJECTED,
        )
        embed.set_author(
            name=str(message.author), icon_url=message.author.display_avatar.url
        )
        footer = f"Cooldown: {cfg['cooldown_hours']}h per partner"
        if not deleted and cfg["cooldown_delete"]:
            footer += " · I couldn't delete the message — missing Manage Messages"
        embed.set_footer(text=footer)

        hide = cfg["cooldown_notice_delete"]
        try:
            await message.channel.send(
                message.author.mention,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                delete_after=hide if hide > 0 else None,
            )
        except discord.HTTPException:
            pass

        log.info(
            "Cooldown hit in guild %s by %s for %s (%ds left)",
            message.guild.id, message.author.id, name, remaining,
        )
        return True

    async def _resolve_invite(self, code: str) -> tuple[Optional[int], Optional[str]]:
        """Look up an invite so we can dedupe by server instead of by code."""
        try:
            invite = await self.bot.fetch_invite(code, with_counts=False, with_expiration=False)
        except (discord.NotFound, discord.HTTPException):
            return None, None
        guild = invite.guild
        if guild is None:
            return None, None
        return guild.id, guild.name

    async def _thread_alive(self, guild: discord.Guild, pship) -> bool:
        """True if the stored thread still exists (so a duplicate is real)."""
        tid = pship["thread_id"]
        if not tid:
            return False
        if guild.get_thread(tid):
            return True
        try:
            ch = await self.bot.fetch_channel(tid)
            return isinstance(ch, discord.Thread)
        except discord.NotFound:
            # Only a pending partnership is cancelled by losing its thread.
            # Approved ones keep their status so the cooldown still applies.
            if pship["status"] == "pending":
                db.update_partnership(pship["id"], status="cancelled", reason="thread deleted")
            db.update_partnership(pship["id"], thread_id=None)
            return False
        except discord.HTTPException:
            return True

    # ------------------------------------------------------------------ #
    #  Duplicate / failure feedback
    # ------------------------------------------------------------------ #

    async def _react_and_report(self, message, created, duplicates, failed):
        cfg = db.get_config(message.guild.id)

        try:
            if created:
                await message.add_reaction("🤝")
            if duplicates:
                await message.add_reaction("♻️")
            if failed:
                await message.add_reaction("⚠️")
        except discord.HTTPException:
            pass

        if not duplicates and not failed:
            return

        # Split duplicates into "this is yours" and "this is someone else's".
        owned, foreign = [], []
        for existing, name in duplicates:
            if self._owns(existing, message.author.id):
                owned.append((existing, name))
            else:
                foreign.append((existing, name))

        lines: list[str] = []

        # Only the original poster ever sees the thread link.
        for existing, name in owned:
            lines.append(
                f"♻️ You already have an open partnership for **{utils.truncate(name, 60)}** "
                f"— **#{existing['id']}** ({existing['status']}).\n"
                f"➡️ Continue in your existing thread: <#{existing['thread_id']}>"
            )

        # Everyone else gets told it exists, with no link and no thread id.
        for existing, name in foreign:
            lines.append(
                f"♻️ **{utils.truncate(name, 60)}** is already being handled by another "
                f"staff member (partnership **#{existing['id']}**).\n"
                f"🔒 That thread is private, so you can't open or view it. "
                f"If you think this is a mistake, ask higher staff to check "
                f"`/partnership info id:{existing['id']}`."
            )

        for code in failed:
            lines.append(f"⚠️ Couldn't open a thread for `{code}` — ask an admin to run `/config check`.")

        # Decide this BEFORE posting, so the notice isn't a reply to a message
        # we're about to delete (that leaves an "original message was deleted"
        # stub in the channel).
        will_delete = bool(foreign and cfg["dup_delete_message"] and not created)

        if lines:
            await self._public_notice(message, cfg, lines, reply=not will_delete)

        # Optionally clean the duplicate link out of the channel.
        if will_delete:
            try:
                await message.delete()
            except discord.HTTPException:
                pass

    @staticmethod
    def _owns(pship, user_id: int) -> bool:
        """True if this user posted the partnership."""
        return user_id == pship["poster_id"]

    async def _public_notice(
        self, message: discord.Message, cfg, lines: list[str], reply: bool = True
    ) -> None:
        """
        Post the 'already open' notice publicly in the channel, as a reply to the
        duplicate message so it's obvious who it's for.

        reply=False sends it as a plain channel message instead — used when the
        duplicate is about to be deleted, since replying to a deleted message
        leaves a broken reference in the channel.

        hide_after = 0 keeps the notice permanently; anything else self-deletes.
        """
        hide_after = int(cfg["dup_notice_delete"] or 0)
        delete_after = hide_after if hide_after > 0 else None

        embed = discord.Embed(
            title="♻️ Partnership already open",
            description="\n\n".join(lines),
            colour=utils.COLOR_PROOF,
        )
        embed.set_author(
            name=str(message.author),
            icon_url=message.author.display_avatar.url,
        )
        if delete_after:
            embed.set_footer(text=f"This message disappears in {delete_after}s")

        mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)
        if not reply:
            try:
                await message.channel.send(
                    message.author.mention,
                    embed=embed,
                    allowed_mentions=mentions,
                    delete_after=delete_after,
                )
            except discord.HTTPException:
                pass
            return

        try:
            await message.reply(
                content=message.author.mention,
                embed=embed,
                mention_author=True,
                allowed_mentions=mentions,
                delete_after=delete_after,
            )
        except discord.HTTPException:
            try:
                await message.channel.send(
                    message.author.mention,
                    embed=embed,
                    allowed_mentions=mentions,
                    delete_after=delete_after,
                )
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Someone deleted a message — if it was the proof, re-lock approval."""
        if payload.guild_id is None:
            return
        pship = db.get_partnership_by_proof(payload.message_id)
        if pship is None or pship["status"] != "pending":
            return
        cfg = db.get_config(payload.guild_id)
        await flow.handle_proof_deleted(self.bot, pship, cfg)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        pship = db.get_partnership_by_thread(thread.id)
        if pship and pship["status"] == "pending":
            db.update_partnership(
                pship["id"], status="cancelled", reason="thread deleted", resolved_at=db.now()
            )

    # ------------------------------------------------------------------ #
    #  /partnership commands
    # ------------------------------------------------------------------ #

    group = app_commands.Group(
        name="partnership",
        description="Manage partnership submissions",
        guild_only=True,
    )

    @group.command(name="list", description="List partnership submissions")
    @app_commands.describe(status="Filter by status", limit="How many to show (default 10)")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Pending", value="pending"),
            app_commands.Choice(name="Approved", value="approved"),
            app_commands.Choice(name="Rejected", value="rejected"),
            app_commands.Choice(name="Cancelled", value="cancelled"),
            app_commands.Choice(name="All", value="all"),
        ]
    )
    async def list_cmd(
        self,
        interaction: discord.Interaction,
        status: app_commands.Choice[str] | None = None,
        limit: app_commands.Range[int, 1, 25] = 10,
    ):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        if not utils.is_staff(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message("Staff only.", ephemeral=True)
            return

        key = status.value if status else "pending"
        rows = db.list_partnerships(guild.id, None if key == "all" else key, limit)

        if not rows:
            await interaction.response.send_message(
                f"No **{key}** partnerships found.", ephemeral=True
            )
            return

        lines = []
        for r in rows:
            icon = {"pending": "⏳", "approved": "✅", "rejected": "❌", "cancelled": "🚫"}.get(
                r["status"], "•"
            )
            name = utils.truncate(r["target_name"] or r["invite_code"] or "?", 32)
            thread = f"<#{r['thread_id']}>" if r["thread_id"] else "*no thread*"
            proof = "📸" if r["proof_msg_id"] else "—"
            lines.append(
                f"{icon} **#{r['id']}** {name} · <@{r['poster_id']}> · {proof} · {thread} "
                f"· <t:{r['created_at']}:R>"
            )

        embed = discord.Embed(
            title=f"Partnerships — {key}",
            description="\n".join(lines),
            colour=utils.COLOR_NEUTRAL,
        )
        embed.set_footer(
            text=f"{db.count_partnerships(guild.id, 'pending')} pending · "
            f"{db.count_partnerships(guild.id, 'approved')} approved"
        )
        await interaction.response.send_message(
            embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @group.command(name="info", description="Show details of one partnership")
    async def info(self, interaction: discord.Interaction, id: int):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        pship = db.get_partnership(id)
        if not pship or pship["guild_id"] != guild.id:
            await interaction.response.send_message("No partnership with that id.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=flow.build_control_embed(guild, pship, cfg), ephemeral=True
        )

    @group.command(
        name="revoke",
        description="Undo a wrongly-approved partnership and take its points back",
    )
    @app_commands.describe(id="Partnership number", reason="Why it's being undone")
    async def revoke(self, interaction: discord.Interaction, id: int, reason: str = "Approved in error"):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        if not utils.is_approver(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message("Higher staff only.", ephemeral=True)
            return

        pship = db.get_partnership(id)
        if not pship or pship["guild_id"] != guild.id:
            await interaction.response.send_message("Partnership not found.", ephemeral=True)
            return
        if pship["status"] != "approved":
            await interaction.response.send_message(
                f"**#{id}** is **{pship['status']}**, not approved — there's nothing to take back.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # amounts come from the bot's own ledger, not from anyone's keyboard
        reversed_rows = db.revoke_partnership_points(id, interaction.user.id)
        db.update_partnership(id, status="revoked", reason=reason, resolved_at=db.now())

        if reversed_rows:
            lines = [f"<@{uid}> **−{amt}** (now {total})" for uid, amt, total in reversed_rows]
        else:
            lines = ["*No points were on this partnership.*"]

        embed = discord.Embed(
            title=f"↩️ Partnership #{id} revoked",
            description=(
                f"**Server:** {pship['target_name'] or pship['invite_code']}\n"
                f"**Reason:** {utils.truncate(reason, 300)}\n\n" + "\n".join(lines)
            ),
            colour=utils.COLOR_REJECTED,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=f"Revoked by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed)

        await flow.send_log(self.bot, guild, cfg, embed)
        await flow.bump_live_board(self.bot, guild)
        await flow.refresh_control_message(self.bot, id)

    @group.command(name="close", description="Cancel a partnership and archive its thread")
    async def close(self, interaction: discord.Interaction, id: int | None = None, reason: str = "Closed by staff"):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        if not utils.is_approver(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message("Higher staff only.", ephemeral=True)
            return

        if id is None:
            if not isinstance(interaction.channel, discord.Thread):
                await interaction.response.send_message(
                    "Give me an `id` or run this inside a partnership thread.", ephemeral=True
                )
                return
            pship = db.get_partnership_by_thread(interaction.channel.id)
        else:
            pship = db.get_partnership(id)

        if not pship or pship["guild_id"] != guild.id:
            await interaction.response.send_message("Partnership not found.", ephemeral=True)
            return

        db.update_partnership(
            pship["id"], status="cancelled", reason=reason, resolved_at=db.now(),
            approver_id=interaction.user.id,
        )
        await flow.refresh_control_message(self.bot, pship["id"])
        await interaction.response.send_message(
            f"🚫 Partnership **#{pship['id']}** cancelled — *{utils.truncate(reason, 200)}*"
        )

        if pship["thread_id"]:
            thread = guild.get_thread(pship["thread_id"])
            if thread:
                try:
                    await thread.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass

    @group.command(name="cooldowns", description="Partners currently on cooldown")
    async def cooldowns(self, interaction: discord.Interaction):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config()
        if not utils.is_staff(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message("Staff only.", ephemeral=True)
            return
        if not cfg["cooldown_enabled"]:
            await interaction.response.send_message(
                "Cooldowns are disabled in **config.toml**.", ephemeral=True
            )
            return

        window = db.now() - cfg["cooldown_hours"] * 3600
        rows = [
            r for r in db.list_partnerships(guild.id, "approved", 50)
            if r["resolved_at"] and r["resolved_at"] >= window
        ]
        if not rows:
            await interaction.response.send_message(
                f"✅ No partners are on cooldown right now "
                f"(window: {cfg['cooldown_hours']}h).",
                ephemeral=True,
            )
            return

        seen, lines = set(), []
        for r in rows:
            key = r["dedupe_key"]
            if key in seen:
                continue
            seen.add(key)
            ready = int(r["resolved_at"]) + cfg["cooldown_hours"] * 3600
            name = utils.truncate(r["target_name"] or r["invite_code"] or "?", 34)
            lines.append(f"• **{name}** — free <t:{ready}:R> *(by <@{r['poster_id']}>)*")

        embed = discord.Embed(
            title=f"⏳ Partners on cooldown ({len(lines)})",
            description="\n".join(lines[:25]),
            colour=utils.COLOR_PROOF,
        )
        embed.set_footer(text=f"Cooldown: {cfg['cooldown_hours']}h after approval")
        await interaction.response.send_message(
            embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @group.command(name="add", description="Manually open a partnership thread for an invite link")
    @app_commands.describe(invite="Invite link or code")
    async def add(self, interaction: discord.Interaction, invite: str):
        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        if not utils.is_staff(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message("Staff only.", ephemeral=True)
            return
        if not db.is_configured(cfg):
            await interaction.response.send_message(
                "Run `/setup` first.", ephemeral=True
            )
            return

        codes = utils.extract_invite_codes(invite) or [invite.strip().split("/")[-1]]
        code = codes[0]
        await interaction.response.defer(ephemeral=True)

        target_id, target_name = await self._resolve_invite(code)
        key = utils.dedupe_key_for(target_id, code)
        existing = db.find_open_partnership(guild.id, key)
        if existing and await self._thread_alive(guild, existing):
            await interaction.followup.send(
                f"♻️ Already open: **#{existing['id']}** → <#{existing['thread_id']}>", ephemeral=True
            )
            return

        # Build a lightweight stand-in message so flow can reuse its logic.
        class _Stub:
            pass

        stub = _Stub()
        stub.guild = guild
        # you are always the poster — credit can't be handed to someone else
        stub.author = interaction.user
        stub.channel = interaction.channel
        stub.id = interaction.id

        thread = await flow.create_partnership_thread(
            self.bot, stub, cfg, code, target_id, target_name  # type: ignore[arg-type]
        )
        if thread:
            await interaction.followup.send(f"✅ Opened {thread.mention}", ephemeral=True)
        else:
            await interaction.followup.send(
                "❌ Couldn't create the thread — run `/config check`.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(PartnershipCog(bot))
