"""
Partnership Bot — entry point.

Detects Discord invite links in a partnership channel, opens a private thread
per link, collects screenshot proof, lets higher staff approve, and keeps a
points leaderboard.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands, tasks

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional in production
    pass

import config
import db

# --------------------------------------------------------------------------- #
#  Logging
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("partnership")

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
COGS = (
    "cogs.admin_cog",
    "cogs.partnership_cog",
    "cogs.leaderboard_cog",
    "cogs.liveboard_cog",
    "cogs.weekly_cog",
)


class PartnershipBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # needed to read invite links
        intents.members = True          # needed to add staff to private threads
        intents.guilds = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=True, users=True),
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="for partnerships"
            ),
        )

    async def setup_hook(self) -> None:
        import views

        db.connect()
        log.info("Database ready at %s", db.DB_PATH)

        # Make the thread buttons work again after a restart.
        self.add_dynamic_items(views.ApproveButton, views.RejectButton)

        for ext in COGS:
            await self.load_extension(ext)
            log.info("Loaded %s", ext)

        cfg = config.get()
        if cfg["guild_id"]:
            guild = discord.Object(id=cfg["guild_id"])
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s (instant)", len(synced), cfg["guild_id"])
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (up to 1h to appear)", len(synced))

        self.config_watcher.start()

    @tasks.loop(seconds=30)
    async def config_watcher(self):
        """Pick up edits to config.toml without a restart."""
        try:
            new = config.reload_if_changed()
        except config.ConfigError as exc:
            log.error("config.toml is broken, keeping the previous settings: %s", exc)
            return
        if new is not None:
            log.info("config.toml changed on disk — reloaded")
            for w in new.warnings:
                log.warning("config: %s", w)

    @config_watcher.before_loop
    async def before_config_watcher(self):
        await self.wait_until_ready()

    async def on_ready(self):
        assert self.user is not None
        cfg = config.get()
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        log.info("Serving %d guild(s)", len(self.guilds))
        if not self.intents.message_content:
            log.warning("MESSAGE CONTENT INTENT IS OFF — invite detection will not work!")
        guild = self.get_guild(cfg["guild_id"]) if cfg["guild_id"] else None
        if guild is None:
            log.warning(
                "guild_id %s from config.toml not found — is the bot in that server?",
                cfg["guild_id"],
            )
        else:
            log.info("Active in %s. Run /diagnose in Discord to verify setup.", guild.name)

    async def on_guild_join(self, guild: discord.Guild):
        log.info("Joined guild %s (%s)", guild.name, guild.id)

    async def on_app_command_error(self, interaction, error):  # pragma: no cover
        log.exception("App command error", exc_info=error)

    async def close(self):
        db.close()
        await super().close()


async def main() -> None:
    # --- configuration must load before anything else ---------------------- #
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        print(f"\nCONFIG ERROR\n{exc}\n", file=sys.stderr)
        sys.exit(1)

    missing = cfg.missing()
    if missing:
        print(
            "\nCONFIG INCOMPLETE — fill these in before the bot can work:\n"
            + "\n".join(f"  - {m}" for m in missing)
            + f"\n\nFile: {os.path.abspath(cfg.path)}\n",
            file=sys.stderr,
        )
    for w in cfg.warnings:
        print(f"  config warning: {w}", file=sys.stderr)

    if not TOKEN:
        print(
            "ERROR: DISCORD_TOKEN is not set.\n"
            "Create a .env file (copy .env.example) or set it in your host's "
            "environment variables panel.",
            file=sys.stderr,
        )
        sys.exit(1)

    if os.getenv("KEEP_ALIVE", "false").lower() in ("1", "true", "yes"):
        import keep_alive

        keep_alive.start()

    bot = PartnershipBot()

    try:
        async with bot:
            await bot.start(TOKEN)
    except discord.LoginFailure:
        print(
            "\nERROR: Discord rejected the token.\n"
            "  • Make sure you copied the BOT token (Developer Portal → Bot → Reset Token),\n"
            "    not the Client Secret or Application ID.\n"
            "  • If the token ever touched a public repo, Discord has already killed it —\n"
            "    reset it and update your host's environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        print(
            "\nERROR: Privileged intents are not enabled for this bot.\n"
            "  Go to Developer Portal → your app → Bot → Privileged Gateway Intents\n"
            "  and turn ON both:  MESSAGE CONTENT INTENT  and  SERVER MEMBERS INTENT.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
