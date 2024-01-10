import asyncio
import datetime
import logging
import sys
import traceback
import typing

import uvicorn
from web import app
from logging import FileHandler

import discord
from discord.ext import commands
from rich.logging import RichHandler
from conf import CONFIG

log = logging.getLogger("jimmy")
CONFIG.setdefault("logging", {})

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=CONFIG["logging"].get("level", "INFO"),
    handlers=[
        RichHandler(
            level=CONFIG["logging"].get("level", "INFO"),
            show_time=False,
            show_path=False,
            markup=True
        ),
        FileHandler(
            filename=CONFIG["logging"].get("file", "jimmy.log"),
            mode="a",
            encoding="utf-8",
            errors="replace"
        )
    ]
)
for logger in CONFIG["logging"].get("suppress", []):
    logging.getLogger(logger).setLevel(logging.WARNING)
    log.info(f"Suppressed logging for {logger}")


class Client(commands.Bot):
    def __init_(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.web: typing.Optional[asyncio.Task] = None

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        app.state.bot = self
        config = uvicorn.Config(
            app,
            host=CONFIG["server"].get("host", "0.0.0.0"),
            port=CONFIG["server"].get("port", 8080),
            loop="asyncio",
            lifespan="on",
            server_header=False
        )
        server = uvicorn.Server(config=config)
        self.web = self.loop.create_task(asyncio.to_thread(server.serve()))
        await super().start(token, reconnect=reconnect)

    async def close(self) -> None:
        if self.web:
            self.web.cancel()
        await super().close()

bot = Client(
    command_prefix=commands.when_mentioned_or("h!", "H!"),
    case_insensitive=True,
    strip_after_prefix=True,
    debug_guilds=CONFIG["jimmy"].get("debug_guilds")
)

bot.load_extension("cogs.ytdl")
bot.load_extension("cogs.net")
bot.load_extension("cogs.screenshot")
bot.load_extension("cogs.ollama")


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


@bot.message_command(name="Delete Message")
async def delete_message(ctx: discord.ApplicationContext, message: discord.Message):
    await ctx.defer()
    if not ctx.channel.permissions_for(ctx.me).manage_messages:
        if message.author != bot.user:
            return await ctx.respond("I don't have permission to delete messages in this channel.", delete_after=30)

    log.info(
        "%s deleted message %s>%s: %r", ctx.author, ctx.channel.name, ctx.message.id, message.content
    )
    await message.delete(delay=3)
    await ctx.respond(f"\N{white heavy check mark} Deleted message by {message.author.display_name}.")
    await ctx.delete(delay=15)


if not CONFIG["jimmy"].get("token"):
    log.critical("No token specified in config.toml. Exiting. (hint: set jimmy.token in config.toml)")
    sys.exit(1)

bot.run(CONFIG["jimmy"]["token"])
