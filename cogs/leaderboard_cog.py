"""Points, leaderboard and manual point adjustments."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import db
import utils

PAGE_SIZE = 10


class LeaderboardView(discord.ui.View):
    """Prev/Next paging for /leaderboard (10 minute timeout)."""

    def __init__(self, guild: discord.Guild, page: int = 0, scope: str = "weekly"):
        super().__init__(timeout=600)
        self.guild = guild
        self.page = page
        self.scope = scope
        self._sync()

    def _sync(self):
        total = db.leaderboard_size(self.guild.id, self.scope)
        self.max_page = max(0, (total - 1) // PAGE_SIZE)
        self.prev.disabled = self.page <= 0
        self.next.disabled = self.page >= self.max_page

    def embed(self) -> discord.Embed:
        rows = db.leaderboard(self.guild.id, PAGE_SIZE, self.page * PAGE_SIZE, scope=self.scope)
        total = db.leaderboard_size(self.guild.id, self.scope)
        lifetime = self.scope == "lifetime"

        if not rows:
            return discord.Embed(
                title="🏆 All-time leaderboard" if lifetime else "🏆 Weekly leaderboard",
                description="No points have been awarded yet.",
                colour=utils.COLOR_NEUTRAL,
            )

        lines = []
        for i, r in enumerate(rows):
            rank = self.page * PAGE_SIZE + i
            member = self.guild.get_member(r["user_id"])
            name = member.display_name if member else f"User {r['user_id']}"
            extra = ""
            if lifetime and "weeks_won" in r.keys() and r["weeks_won"]:
                extra = f" · 👑{r['weeks_won']}"
            lines.append(
                f"{utils.medal(rank)} **{utils.truncate(name, 28)}** — "
                f"**{r['points']}** pts "
                f"· {r['partnerships']}🤝 · {r['approvals']}✅{extra}"
            )

        embed = discord.Embed(
            title="🏆 All-time leaderboard" if lifetime else "🏆 Weekly leaderboard",
            description="\n".join(lines),
            colour=0x9B59B6 if lifetime else 0xF1C40F,
        )
        scope_note = "all time" if lifetime else f"week {db.week_number(self.guild.id)}"
        embed.set_footer(
            text=f"Page {self.page + 1}/{self.max_page + 1} · "
            f"{utils.plural(total, 'member')} ranked · {scope_note}"
        )
        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        return embed

    @discord.ui.button(label="Prev", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Next", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.max_page, self.page + 1)
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="leaderboard", description="Top partnership point earners")
    @app_commands.guild_only()
    @app_commands.describe(
        scope="This week's scores (default) or all-time totals",
        private="Only show the leaderboard to you",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="This week", value="weekly"),
            app_commands.Choice(name="All time", value="lifetime"),
        ]
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        scope: app_commands.Choice[str] | None = None,
        private: bool = False,
    ):
        guild = interaction.guild
        assert guild is not None
        view = LeaderboardView(guild, scope=scope.value if scope else "weekly")
        await interaction.response.send_message(
            embed=view.embed(), view=view, ephemeral=private
        )

    @app_commands.command(name="points", description="Show a member's partnership points")
    @app_commands.guild_only()
    async def points(self, interaction: discord.Interaction, user: discord.Member | None = None):
        guild = interaction.guild
        assert guild is not None
        target = user or interaction.user
        stats = db.get_user_stats(guild.id, target.id)
        life = db.get_user_stats(guild.id, target.id, "lifetime")
        rank = db.get_rank(guild.id, target.id)
        history = db.recent_history(guild.id, target.id, 5)

        embed = discord.Embed(
            title=f"📊 {target.display_name}",
            colour=target.colour if target.colour.value else utils.COLOR_NEUTRAL,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="This week", value=f"**{stats['points']}** pts", inline=True)
        embed.add_field(name="Rank", value=f"#{rank}" if stats["points"] else "—", inline=True)
        embed.add_field(name="Partnerships", value=str(stats["partnerships"]), inline=True)
        embed.add_field(name="All time", value=f"**{life['points']}** pts", inline=True)
        embed.add_field(
            name="Weeks won",
            value=f"👑 {life['weeks_won']}" if life["weeks_won"] else "—",
            inline=True,
        )
        embed.add_field(name="Total partnerships", value=str(life["partnerships"]), inline=True)

        if history:
            lines = [
                f"`{h['delta']:+d}` {utils.truncate(h['reason'] or 'adjustment', 44)} "
                f"· <t:{h['created_at']}:R>"
                for h in history
            ]
            embed.add_field(name="Recent activity", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed)

    # ------------------------------------------------------------------ #
    #  /quota
    # ------------------------------------------------------------------ #

    quota = app_commands.Group(
        name="quota",
        description="Weekly partnership quota",
        guild_only=True,
    )

    @quota.command(name="check", description="How far through the weekly quota you are")
    async def quota_check(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ):
        import flow

        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        if not cfg["quota_target"]:
            await interaction.response.send_message(
                "No weekly quota is set — add `[quota] target` to **config.toml**.",
                ephemeral=True,
            )
            return

        target_member = user or interaction.user
        done, target, remaining = flow.quota_progress(guild.id, target_member.id, cfg)
        unit = "point" if cfg["quota_metric"] == "points" else "partnership"

        embed = discord.Embed(
            title="🎯 Weekly quota",
            description=(
                f"**Done:** {done}/{target}\n"
                + ("**✅ Quota complete.**" if remaining == 0
                   else f"**{utils.plural(remaining, unit)}** to go.")
            ),
            colour=utils.COLOR_APPROVED if remaining == 0 else utils.COLOR_PENDING,
        )
        embed.add_field(
            name="Progress",
            value=f"`{utils.progress_bar(done, target)}`  "
                  f"{min(100, int(done / target * 100)) if target else 100}%",
            inline=False,
        )
        embed.set_author(
            name=target_member.display_name, icon_url=target_member.display_avatar.url
        )
        embed.set_footer(text="Resets with the weekly leaderboard")
        await interaction.response.send_message(embed=embed, ephemeral=user is None)

    @quota.command(name="list", description="Who has and hasn't hit quota this week")
    async def quota_list(self, interaction: discord.Interaction):
        import flow

        guild = interaction.guild
        assert guild is not None
        cfg = db.get_config(guild.id)
        if not utils.is_staff(interaction.user, cfg):  # type: ignore[arg-type]
            await interaction.response.send_message("Staff only.", ephemeral=True)
            return
        if not cfg["quota_target"]:
            await interaction.response.send_message(
                "No weekly quota is set — add `[quota] target` to **config.toml**.",
                ephemeral=True,
            )
            return

        # Staff role is optional — fall back to the approver role when it's unset.
        rid = cfg["staff_role_id"] or cfg["approver_role_id"]
        role = guild.get_role(rid) if rid else None
        if role is None:
            await interaction.response.send_message(
                "No usable role in **config.toml** — set `[roles] approver` (or `staff`).",
                ephemeral=True,
            )
            return

        done_rows, behind_rows = [], []
        for member in sorted(role.members, key=lambda m: m.display_name.lower()):
            if member.bot:
                continue
            got, target, left = flow.quota_progress(guild.id, member.id, cfg)
            line = f"`{got}/{target}` {member.mention}"
            (done_rows if left == 0 else behind_rows).append(
                line if left == 0 else f"{line} — **{left}** to go"
            )

        embed = discord.Embed(
            title="🎯 Weekly quota standings",
            description=f"Target: **{cfg['quota_target']}** "
                        f"{'points' if cfg['quota_metric'] == 'points' else 'partnerships'} per staff member",
            colour=utils.COLOR_NEUTRAL,
        )
        embed.add_field(
            name=f"✅ Hit quota ({len(done_rows)})",
            value=utils.truncate("\n".join(done_rows), 1000) if done_rows else "*Nobody yet*",
            inline=False,
        )
        embed.add_field(
            name=f"⏳ Still working ({len(behind_rows)})",
            value=utils.truncate("\n".join(behind_rows), 1000) if behind_rows else "*Everyone's done!*",
            inline=False,
        )
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
