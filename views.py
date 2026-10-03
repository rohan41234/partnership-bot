"""
Persistent buttons attached to each partnership thread.

These use discord.ui.DynamicItem so the buttons keep working after the bot
restarts (the partnership id is encoded in the button's custom_id).
"""

from __future__ import annotations

import re

import discord

import db


class _Base(discord.ui.DynamicItem[discord.ui.Button], template=r"^$"):
    """Shared plumbing for the partnership buttons."""

    def __init__(self, button: discord.ui.Button, pship_id: int):
        super().__init__(button)
        self.pship_id = pship_id

    async def _load(self, interaction: discord.Interaction):
        """Fetch the partnership row + config, or complain to the user."""
        pship = db.get_partnership(self.pship_id)
        if pship is None:
            await interaction.response.send_message(
                "This partnership no longer exists in the database.", ephemeral=True
            )
            return None, None
        cfg = db.get_config(interaction.guild_id)
        return pship, cfg


class ApproveButton(_Base, template=r"pship:approve:(?P<pid>[0-9]+)"):
    def __init__(self, pship_id: int, disabled: bool = False):
        super().__init__(
            discord.ui.Button(
                label="Approve",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"pship:approve:{pship_id}",
                disabled=disabled,
            ),
            pship_id,
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /):
        return cls(int(match["pid"]))

    async def callback(self, interaction: discord.Interaction):
        import flow

        pship, cfg = await self._load(interaction)
        if pship is None:
            return
        await flow.handle_approve(interaction, pship, cfg)


class RejectButton(_Base, template=r"pship:reject:(?P<pid>[0-9]+)"):
    def __init__(self, pship_id: int, disabled: bool = False):
        super().__init__(
            discord.ui.Button(
                label="Reject",
                emoji="❌",
                style=discord.ButtonStyle.danger,
                custom_id=f"pship:reject:{pship_id}",
                disabled=disabled,
            ),
            pship_id,
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /):
        return cls(int(match["pid"]))

    async def callback(self, interaction: discord.Interaction):
        import flow

        pship, cfg = await self._load(interaction)
        if pship is None:
            return
        await flow.handle_reject(interaction, pship, cfg)


class RejectReasonModal(discord.ui.Modal, title="Reject partnership"):
    reason = discord.ui.TextInput(
        label="Reason",
        placeholder="e.g. screenshot unreadable / ad not found on their server",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=400,
    )

    def __init__(self, pship_id: int):
        super().__init__()
        self.pship_id = pship_id

    async def on_submit(self, interaction: discord.Interaction):
        import flow

        pship = db.get_partnership(self.pship_id)
        cfg = db.get_config(interaction.guild_id)
        if pship is None:
            await interaction.response.send_message("Partnership not found.", ephemeral=True)
            return
        await flow.finish_reject(interaction, pship, cfg, str(self.reason))


def build_control_view(pship, cfg) -> discord.ui.View:
    """Build the button row that matches the partnership's current state."""
    view = discord.ui.View(timeout=None)
    resolved = pship["status"] in ("approved", "rejected", "cancelled")

    needs_proof = bool(cfg["require_proof"]) and not pship["proof_msg_id"]
    view.add_item(ApproveButton(pship["id"], disabled=resolved or needs_proof))
    view.add_item(RejectButton(pship["id"], disabled=resolved))
    return view
