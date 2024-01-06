import datetime
import logging
import traceback
from logging import FileHandler
from pathlib import Path

import discord
import toml
from discord.ext import commands
from rich.logging import RichHandler
from conf import CONFIG

log = logging.getLogger("jimmy")



logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=CONFIG.get("logging", {}).get("level", "INFO"),
    handlers=[
        RichHandler(
            level=CONFIG.get("logging", {}).get("level", "INFO"),
            show_time=False,
            show_path=False,
            markup=True
        ),
        FileHandler(
            filename=CONFIG.get("logging", {}).get("file", "jimmy.log"),
            mode="a",
        )
    ]
)

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("h!", "H!"),
    case_insensitive=True,
    strip_after_prefix=True,
    debug_guilds=CONFIG["jimmy"].get("debug_guilds")
)

bot.load_extension("cogs.ytdl")
bot.load_extension("cogs.net")
bot.load_extension("cogs.screenshot")


@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} ({bot.user.id})")


@bot.listen()
async def on_application_command(ctx: discord.ApplicationContext):
    log.info(f"Received command [b]{ctx.command}[/] from {ctx.author} in {ctx.guild}")
    ctx.start_time = discord.utils.utcnow()


@bot.listen()
async def on_application_command_error(ctx: discord.ApplicationContext, exc: Exception):
    log.error(f"Error in {ctx.command} from {ctx.author} in {ctx.guild}", exc_info=exc)
    if isinstance(exc, commands.CommandOnCooldown):
        expires = discord.utils.utcnow() + datetime.timedelta(seconds=exc.retry_after)
        await ctx.respond(f"Command on cooldown. Try again {discord.utils.format_dt(expires, style='R')}.")
    elif isinstance(exc, commands.MaxConcurrencyReached):
        await ctx.respond("You've reached the maximum number of concurrent uses for this command.")
    else:
        if await bot.is_owner(ctx.author):
            paginator = commands.Paginator(prefix="```py")
            for line in traceback.format_exception(type(exc), exc, exc.__traceback__):
                paginator.add_line(line[:1990])
            for page in paginator.pages:
                await ctx.respond(page)
        else:
            await ctx.respond(f"An error occurred while processing your command. Please try again later.\n"
                              f"{exc}")


@bot.listen()
async def on_application_command_completion(ctx: discord.ApplicationContext):
    time_taken = discord.utils.utcnow() - ctx.start_time
    log.info(
        f"Completed command [b]{ctx.command}[/] from {ctx.author} in "
        f"{ctx.guild} in {time_taken.total_seconds():.2f} seconds."
    )


bot.run(CONFIG["jimmy"]["token"])
