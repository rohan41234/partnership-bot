"""
Core partnership workflow: thread creation, proof tracking, approval, points.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord

import db
import utils

log = logging.getLogger("partnership.flow")


# --------------------------------------------------------------------------- #
#  Embeds
# --------------------------------------------------------------------------- #

def build_control_embed(guild: discord.Guild, pship, cfg) -> discord.Embed:
    has_proof = bool(pship["proof_msg_id"])
    status_key = pship["status"]
    if status_key == "pending" and has_proof:
        status_key = "proof"

    embed = discord.Embed(
        title=f"🤝 Partnership #{pship['id']}",
        colour=utils.status_color(pship["status"], has_proof),
        timestamp=discord.utils.utcnow(),
    )

    target = pship["target_name"] or "Unknown server"
    invite_url = f"https://discord.gg/{pship['invite_code']}" if pship["invite_code"] else "—"
    embed.add_field(name="Server", value=f"**{utils.truncate(target, 100)}**", inline=True)
    embed.add_field(name="Invite", value=invite_url, inline=True)
    embed.add_field(name="Status", value=utils.STATUS_LABEL.get(status_key, status_key), inline=False)

    embed.add_field(name="Posted by", value=f"<@{pship['poster_id']}>", inline=True)

    if pship["source_message_id"] and pship["source_channel_id"]:
        jump = (
            f"https://discord.com/channels/{guild.id}/"
            f"{pship['source_channel_id']}/{pship['source_message_id']}"
        )
        embed.add_field(name="Original message", value=f"[Jump]({jump})", inline=True)

    if has_proof and pship["proof_url"]:
        embed.set_thumbnail(url=pship["proof_url"])

    if pship["status"] == "approved":
        embed.add_field(name="Approved by", value=f"<@{pship['approver_id']}>", inline=True)
    elif pship["status"] == "rejected":
        embed.add_field(name="Rejected by", value=f"<@{pship['approver_id']}>", inline=True)
        if pship["reason"]:
            embed.add_field(name="Reason", value=utils.truncate(pship["reason"], 500), inline=False)

    if pship["status"] == "pending":
        if not has_proof:
            embed.description = (
                "**Next step —** the staff member who handled this partnership must post a "
                "**screenshot** in this thread showing our ad on their server.\n"
                "Once an image is attached, the **Approve** button unlocks for higher staff."
            )
        else:
            embed.description = (
                "**Proof received.** A higher staff member can now review the screenshot "
                "and press **Approve** or **Reject**."
            )

    footer = f"{utils.plural(cfg['poster_points'], 'point')} to staff · "
    footer += f"{utils.plural(cfg['approver_points'], 'point')} to approver"
    embed.set_footer(text=footer)
    return embed


# --------------------------------------------------------------------------- #
#  Thread creation
# --------------------------------------------------------------------------- #

async def create_partnership_thread(
    bot: discord.Client,
    message: discord.Message,
    cfg,
    code: str,
    target_guild_id: Optional[int],
    target_name: Optional[str],
) -> Optional[discord.Thread]:
    """Create the private thread for one detected invite and seed it."""
    import views

    guild = message.guild
    assert guild is not None

    parent_id = cfg["thread_parent_id"] or cfg["listen_channel_id"]
    parent = guild.get_channel(parent_id)
    if not isinstance(parent, discord.TextChannel):
        log.warning("Thread parent %s is not a text channel in guild %s", parent_id, guild.id)
        return None

    pship_id = db.create_partnership(
        guild_id=guild.id,
        dedupe_key=utils.dedupe_key_for(target_guild_id, code),
        invite_code=code,
        target_guild_id=target_guild_id,
        target_name=target_name,
        source_channel_id=message.channel.id,
        source_message_id=message.id,
        poster_id=message.author.id,
    )

    # --- the thread itself ------------------------------------------------- #
    try:
        thread = await parent.create_thread(
            name=utils.thread_name_for(target_name, code, pship_id),
            type=discord.ChannelType.private_thread,
            invitable=False,
            auto_archive_duration=cfg["auto_archive"],
            reason=f"Partnership #{pship_id} submitted by {message.author}",
        )
    except discord.Forbidden:
        log.warning("Missing permission to create private threads in %s", parent.id)
        db.update_partnership(pship_id, status="cancelled", reason="missing permissions")
        return None
    except discord.HTTPException as exc:
        log.warning("Failed to create thread: %s", exc)
        db.update_partnership(pship_id, status="cancelled", reason=str(exc))
        return None

    db.update_partnership(pship_id, thread_id=thread.id)

    # --- who can see it ----------------------------------------------------- #
    # A private thread is only visible to members that have been added to it.
    # (Anyone with Manage Threads can still see it — Discord gives them that,
    # and no bot can take it away.)
    try:
        await thread.add_user(message.author)
    except discord.HTTPException:
        pass

    # Only the approver role is added by default — nobody else. The staff role
    # is deliberately excluded: staff don't need to sit in every thread, only
    # the people who can actually approve it do.
    added = 0
    role_ids: list[int] = []
    if cfg["add_approver_role"] and cfg["approver_role_id"]:
        role_ids.append(cfg["approver_role_id"])
    if cfg["add_staff_role"] and cfg["staff_role_id"]:
        role_ids.append(cfg["staff_role_id"])

    seen: set[int] = {message.author.id}
    for rid in dict.fromkeys(role_ids):
        role = guild.get_role(rid)
        if role is None:
            continue
        for member in role.members:
            if added >= cfg["max_staff_added"]:
                break
            if member.id in seen or member.bot:
                continue
            seen.add(member.id)
            try:
                await thread.add_user(member)
                added += 1
            except discord.HTTPException:
                continue

    # --- seed message ------------------------------------------------------- #
    pship = db.get_partnership(pship_id)
    embed = build_control_embed(guild, pship, cfg)
    view = views.build_control_view(pship, cfg)

    # Who gets pinged. By default: the poster (they owe the screenshot) and the
    # approver role (they're the ones who have to act). The staff role is NOT
    # pinged — staff are still added to the thread, they just aren't notified.
    pings: list[str] = []
    if cfg["ping_poster"]:
        pings.append(f"<@{message.author.id}>")

    role_ids: list[int] = []
    if cfg["ping_staff_role"] and cfg["staff_role_id"]:
        role_ids.append(cfg["staff_role_id"])
    if cfg["ping_approver_role"] and cfg["approver_role_id"]:
        role_ids.append(cfg["approver_role_id"])
    for rid in dict.fromkeys(role_ids):          # dedupe, keep order
        pings.append(f"<@&{rid}>")

    allowed = discord.AllowedMentions(users=True, roles=True, everyone=False)
    control = await thread.send(
        " ".join(pings) if pings else None,
        embed=embed, view=view, allowed_mentions=allowed,
    )
    try:
        await control.pin()
    except discord.HTTPException:
        pass

    db.update_partnership(pship_id, control_msg_id=control.id)
    return thread


# --------------------------------------------------------------------------- #
#  Refreshing the control message
# --------------------------------------------------------------------------- #

async def refresh_control_message(bot: discord.Client, pship_id: int) -> None:
    import views

    pship = db.get_partnership(pship_id)
    if not pship or not pship["thread_id"] or not pship["control_msg_id"]:
        return
    guild = bot.get_guild(pship["guild_id"])
    if guild is None:
        return
    cfg = db.get_config(guild.id)

    thread = guild.get_thread(pship["thread_id"])
    if thread is None:
        try:
            thread = await bot.fetch_channel(pship["thread_id"])  # type: ignore[assignment]
        except discord.HTTPException:
            return

    try:
        msg = await thread.fetch_message(pship["control_msg_id"])
        await msg.edit(
            embed=build_control_embed(guild, pship, cfg),
            view=views.build_control_view(pship, cfg),
        )
    except discord.HTTPException:
        pass


# --------------------------------------------------------------------------- #
#  Logging channel
# --------------------------------------------------------------------------- #

async def send_log(
    bot: discord.Client,
    guild: discord.Guild,
    cfg,
    embed: discord.Embed,
    content: str | None = None,
) -> None:
    if not cfg["log_channel_id"]:
        return
    channel = guild.get_channel(cfg["log_channel_id"])
    if isinstance(channel, (discord.TextChannel, discord.Thread)):
        try:
            await channel.send(
                content=content,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            pass


async def delete_source_ad(bot: discord.Client, guild: discord.Guild, pship) -> bool:
    """Remove the original invite/ad message from the partnership channel."""
    if not (pship["source_channel_id"] and pship["source_message_id"]):
        return False
    channel = guild.get_channel(pship["source_channel_id"])
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return False
    try:
        msg = await channel.fetch_message(pship["source_message_id"])
        await msg.delete()
        return True
    except discord.NotFound:
        return True  # already gone
    except discord.Forbidden:
        log.warning("Missing Manage Messages — could not delete rejected ad in %s", channel.id)
        return False
    except discord.HTTPException:
        return False


async def delete_thread(bot: discord.Client, guild: discord.Guild, pship_id: int) -> bool:
    """Delete a partnership thread and forget its id so nothing retries."""
    pship = db.get_partnership(pship_id)
    if not pship or not pship["thread_id"]:
        return False
    thread_id = pship["thread_id"]

    # clear it first so on_thread_delete doesn't treat this as a cancellation
    db.update_partnership(pship_id, thread_id=None, control_msg_id=None)

    thread = guild.get_thread(thread_id)
    if thread is None:
        try:
            thread = await bot.fetch_channel(thread_id)  # type: ignore[assignment]
        except discord.NotFound:
            return True
        except discord.HTTPException:
            return False
    try:
        await thread.delete()
        return True
    except discord.NotFound:
        return True
    except discord.Forbidden:
        log.warning("Missing Manage Threads — could not delete thread %s", thread_id)
        return False
    except discord.HTTPException:
        return False


async def schedule_thread_delete(
    bot: discord.Client, guild: discord.Guild, pship_id: int, delay: int
) -> None:
    """Announce the countdown, wait, then delete. Safe to fire-and-forget."""
    pship = db.get_partnership(pship_id)
    if not pship or not pship["thread_id"]:
        return

    if delay > 0:
        thread = guild.get_thread(pship["thread_id"])
        if thread is not None:
            try:
                await thread.send(
                    f"🗑️ This thread will be deleted <t:{db.now() + delay}:R>."
                )
            except discord.HTTPException:
                pass
        await asyncio.sleep(delay)

    await delete_thread(bot, guild, pship_id)


async def bump_live_board(bot: discord.Client, guild: discord.Guild) -> None:
    """Push the live leaderboard immediately after points change."""
    cog = bot.get_cog("LiveBoardCog")
    if cog is None:
        return
    cfg = db.get_config(guild.id)
    if not (cfg["lb_enabled"] and cfg["lb_channel_id"]):
        return
    try:
        cog._last_hash.pop(guild.id, None)  # type: ignore[attr-defined]
        await cog.push(guild, cfg)  # type: ignore[attr-defined]
    except Exception:  # never let the board break an approval
        log.debug("live board push failed", exc_info=True)


# --------------------------------------------------------------------------- #
#  Button handlers
# --------------------------------------------------------------------------- #

async def handle_approve(interaction: discord.Interaction, pship, cfg) -> None:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return

    if not utils.is_approver(member, cfg):
        await interaction.response.send_message(
            "Only **higher staff** (the approver role) can approve partnerships.", ephemeral=True
        )
        return

    if pship["status"] != "pending":
        await interaction.response.send_message(
            f"This partnership is already **{pship['status']}**.", ephemeral=True
        )
        return

    if cfg["require_proof"] and not pship["proof_msg_id"]:
        await interaction.response.send_message(
            "No screenshot has been posted in this thread yet — approval is locked until proof is attached.",
            ephemeral=True,
        )
        return

    if member.id == pship["poster_id"]:
        await interaction.response.send_message(
            "You can't approve your own partnership. Another higher staff member must review it.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    guild = interaction.guild
    assert guild is not None
    pid = pship["id"]

    # Atomic — only one approver can win this, even on a simultaneous click.
    if not db.claim_partnership(pid, "approved", member.id):
        fresh = db.get_partnership(pid)
        await interaction.followup.send(
            f"Someone beat you to it — this is already "
            f"**{fresh['status'] if fresh else 'resolved'}**.",
            ephemeral=True,
        )
        return

    # Re-read: proof could have been deleted between the click and the claim.
    pship = db.get_partnership(pid) or pship

    # --- award points ------------------------------------------------------- #
    awarded: list[str] = []

    poster_total = db.add_points(
        guild.id,
        pship["poster_id"],
        cfg["poster_points"],
        reason=f"Partnership #{pid} approved",
        actor_id=member.id,
        pship_id=pid,
        partnerships=1,
    )
    awarded.append(f"<@{pship['poster_id']}> **+{cfg['poster_points']}** (total {poster_total})")

    if cfg["approver_points"]:
        approver_total = db.add_points(
            guild.id,
            member.id,
            cfg["approver_points"],
            reason=f"Approved partnership #{pid}",
            actor_id=member.id,
            pship_id=pid,
            approvals=1,
        )
        awarded.append(f"<@{member.id}> **+{cfg['approver_points']}** (total {approver_total})")

    await refresh_control_message(interaction.client, pid)

    result = discord.Embed(
        title="✅ Partnership approved",
        description="\n".join(awarded),
        colour=utils.COLOR_APPROVED,
        timestamp=discord.utils.utcnow(),
    )
    result.set_footer(text=f"Approved by {member.display_name}", icon_url=member.display_avatar.url)
    await interaction.followup.send(embed=result)

    log_embed = discord.Embed(
        title=f"✅ Partnership #{pid} approved",
        description=(
            f"**Server:** {pship['target_name'] or pship['invite_code']}\n"
            f"**Staff:** <@{pship['poster_id']}>\n"
            f"**Approved by:** {member.mention}\n"
            f"**Thread:** <#{pship['thread_id']}>"
        ),
        colour=utils.COLOR_APPROVED,
        timestamp=discord.utils.utcnow(),
    )
    await send_log(interaction.client, guild, cfg, log_embed)
    await bump_live_board(interaction.client, guild)

    # quota update for the staff member who earned it — posted before the
    # thread is scheduled for deletion so the in-thread copy still lands
    thread = interaction.channel if isinstance(interaction.channel, discord.Thread) else None
    await post_quota_update(interaction.client, guild, cfg, pship["poster_id"], thread)

    if cfg["delete_thread_on_approve"]:
        asyncio.create_task(
            schedule_thread_delete(interaction.client, guild, pid, cfg["delete_thread_after"])
        )


async def handle_reject(interaction: discord.Interaction, pship, cfg) -> None:
    import views

    member = interaction.user
    if not isinstance(member, discord.Member):
        return

    if not utils.is_approver(member, cfg):
        await interaction.response.send_message(
            "Only **higher staff** (the approver role) can reject partnerships.", ephemeral=True
        )
        return

    if pship["status"] != "pending":
        await interaction.response.send_message(
            f"This partnership is already **{pship['status']}**.", ephemeral=True
        )
        return

    await interaction.response.send_modal(views.RejectReasonModal(pship["id"]))


async def finish_reject(interaction: discord.Interaction, pship, cfg, reason: str) -> None:
    member = interaction.user
    # The modal is per-user, but re-check anyway: roles can change while it's open.
    if not (isinstance(member, discord.Member) and utils.is_approver(member, cfg)):
        await interaction.response.send_message(
            "Only **higher staff** can reject partnerships.", ephemeral=True
        )
        return

    await interaction.response.defer()
    pid = pship["id"]

    if not db.claim_partnership(pid, "rejected", member.id, reason):
        fresh = db.get_partnership(pid)
        await interaction.followup.send(
            f"Too late — this is already **{fresh['status'] if fresh else 'resolved'}**.",
            ephemeral=True,
        )
        return
    await refresh_control_message(interaction.client, pid)

    guild = interaction.guild

    # the rejected ad shouldn't stay up in the partnership channel
    ad_removed = False
    if guild and cfg["delete_ad_on_reject"]:
        ad_removed = await delete_source_ad(interaction.client, guild, pship)

    embed = discord.Embed(
        title="❌ Partnership rejected",
        description=f"**Reason:** {utils.truncate(reason, 1000)}\n\nNo points were awarded.",
        colour=utils.COLOR_REJECTED,
        timestamp=discord.utils.utcnow(),
    )
    if cfg["delete_ad_on_reject"]:
        embed.add_field(
            name="Original ad",
            value="🗑️ Removed from the partnership channel"
            if ad_removed
            else "⚠️ Couldn't delete it — I need **Manage Messages** there",
            inline=False,
        )
    embed.set_footer(
        text=f"Rejected by {interaction.user.display_name}",
        icon_url=interaction.user.display_avatar.url,
    )
    await interaction.followup.send(f"<@{pship['poster_id']}>", embed=embed)

    if guild:
        log_embed = discord.Embed(
            title=f"❌ Partnership #{pid} rejected",
            description=(
                f"**Server:** {pship['target_name'] or pship['invite_code']}\n"
                f"**Staff:** <@{pship['poster_id']}>\n"
                f"**Rejected by:** {interaction.user.mention}\n"
                f"**Reason:** {utils.truncate(reason, 500)}\n"
                f"**Original ad:** {'deleted' if ad_removed else 'still in the channel'}"
            ),
            colour=utils.COLOR_REJECTED,
            timestamp=discord.utils.utcnow(),
        )
        # the poster is pinged here because the thread is about to disappear
        await send_log(
            interaction.client, guild, cfg, log_embed, content=f"<@{pship['poster_id']}>"
        )

        if cfg["delete_thread_on_reject"]:
            asyncio.create_task(
                schedule_thread_delete(interaction.client, guild, pid, cfg["delete_thread_after"])
            )


# --------------------------------------------------------------------------- #
#  Proof handling
# --------------------------------------------------------------------------- #

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def message_has_image(message: discord.Message, attachments_only: bool = False) -> Optional[str]:
    """
    Return the URL of the first image in the message, if any.

    With `attachments_only` (the default in config) a pasted link does NOT
    count — proof must be a real upload. Otherwise anyone could satisfy the
    proof requirement by linking any image on the internet, including the
    screenshot from somebody else's already-approved partnership.
    """
    for att in message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            return att.url
        if att.filename.lower().endswith(IMAGE_EXTS):
            return att.url
    if attachments_only:
        return None
    for emb in message.embeds:
        if emb.image and emb.image.url:
            return emb.image.url
        if emb.thumbnail and emb.thumbnail.url:
            return emb.thumbnail.url
    return None


async def handle_proof(bot: discord.Client, message: discord.Message, pship, cfg) -> None:
    url = message_has_image(message, attachments_only=bool(cfg["proof_attachment_only"]))
    if not url:
        return
    if pship["status"] != "pending":
        return

    member = message.author
    allowed_ids = {pship["poster_id"]}
    if message.author.id not in allowed_ids and not (
        isinstance(member, discord.Member) and utils.is_staff(member, cfg)
    ):
        return

    first_proof = not pship["proof_msg_id"]
    db.update_partnership(pship["id"], proof_msg_id=message.id, proof_url=url)

    try:
        await message.add_reaction("📸")
    except discord.HTTPException:
        pass

    await refresh_control_message(bot, pship["id"])

    if first_proof:
        mention = f"<@&{cfg['approver_role_id']}>" if cfg["approver_role_id"] else "Higher staff"
        try:
            await message.channel.send(
                f"{mention} — proof has been submitted by {message.author.mention}. "
                "Please review the screenshot and use the **Approve** / **Reject** buttons above.",
                allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
            )
        except discord.HTTPException:
            pass


async def handle_proof_deleted(bot: discord.Client, pship, cfg) -> None:
    """
    The screenshot was deleted. Re-lock approval and say so out loud.

    Without this, posting an image and immediately deleting it leaves the
    Approve button unlocked with nothing left to review.
    """
    pid = pship["id"]
    if not db.clear_proof(pid, pship["proof_msg_id"]):
        return  # already resolved, or a different message

    await refresh_control_message(bot, pid)

    guild = bot.get_guild(pship["guild_id"])
    if guild is None or not pship["thread_id"]:
        return
    thread = guild.get_thread(pship["thread_id"])
    if thread is None:
        return
    try:
        await thread.send(
            embed=discord.Embed(
                title="⚠️ Proof removed",
                description=(
                    f"The screenshot for this partnership was deleted, so **Approve** "
                    f"is locked again.\n<@{pship['poster_id']}> — please re-upload it."
                ),
                colour=utils.COLOR_PROOF,
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    except discord.HTTPException:
        pass

    if guild:
        await send_log(
            bot, guild, cfg,
            discord.Embed(
                title=f"⚠️ Proof deleted on partnership #{pid}",
                description=(
                    f"**Poster:** <@{pship['poster_id']}>\n"
                    "Approval has been re-locked."
                ),
                colour=utils.COLOR_PROOF,
                timestamp=discord.utils.utcnow(),
            ),
        )


# --------------------------------------------------------------------------- #
#  Weekly quota
# --------------------------------------------------------------------------- #

def quota_progress(guild_id: int, user_id: int, cfg) -> tuple[int, int, int]:
    """(done, target, remaining) for this member's current week."""
    stats = db.get_user_stats(guild_id, user_id, "weekly")
    done = int(stats["points"] if cfg["quota_metric"] == "points" else stats["partnerships"])
    target = int(cfg["quota_target"])
    return done, target, max(0, target - done)


def build_quota_embed(member_id: int, done: int, target: int, cfg) -> discord.Embed:
    """The message posted in the quota channel after every approval."""
    remaining = max(0, target - done)
    unit = "point" if cfg["quota_metric"] == "points" else "partnership"
    complete = remaining == 0

    if complete:
        headline = f"🎉 **Weekly quota complete!** {utils.plural(done, unit)} this week."
        tail = (
            "Everything from here is extra — it still counts toward the leaderboard."
            if done == target else
            f"That's **{done - target}** over the target."
        )
    else:
        headline = f"✅ Partnership approved — **{done}/{target}** this week."
        tail = f"**{utils.plural(remaining, unit)}** left to hit quota."

    embed = discord.Embed(
        description=f"{headline}\n{tail}",
        colour=utils.COLOR_APPROVED if complete else utils.COLOR_PENDING,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name=f"Progress  ·  {done}/{target}",
        value=f"`{utils.progress_bar(done, target)}`  {min(100, int(done / target * 100)) if target else 100}%",
        inline=False,
    )
    return embed


async def post_quota_update(
    bot: discord.Client, guild: discord.Guild, cfg, member_id: int,
    thread: discord.Thread | None = None,
) -> None:
    """Tell the quota channel where this staff member now stands. Never raises."""
    if not (cfg["quota_enabled"] and cfg["quota_channel_id"]):
        return

    channel = guild.get_channel(cfg["quota_channel_id"])
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        log.warning("quota channel %s not found in guild %s", cfg["quota_channel_id"], guild.id)
        return

    done, target, remaining = quota_progress(guild.id, member_id, cfg)
    if remaining == 0 and not cfg["quota_announce_done"]:
        return

    embed = build_quota_embed(member_id, done, target, cfg)
    member = guild.get_member(member_id)
    if member:
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)

    content = f"<@{member_id}>" if cfg["quota_ping"] else None
    try:
        await channel.send(
            content=content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=bool(cfg["quota_ping"]),
                                                     roles=False, everyone=False),
        )
    except discord.HTTPException as exc:
        log.warning("Could not post quota update: %s", exc)

    if cfg["quota_in_thread"] and thread is not None:
        try:
            await thread.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
