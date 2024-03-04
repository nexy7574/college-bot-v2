import asyncio
import datetime
import logging
import sys
import traceback
import typing
from threading import Thread, Event
import time
import random
import httpx

import uvicorn
from web import app
from logging import FileHandler

import discord
from discord.ext import commands
from rich.logging import RichHandler
from conf import CONFIG


class KillableThread(Thread):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kill = Event()


class KumaThread(KillableThread):
    def __init__(self, url: str, interval: float = 60.0):
        super().__init__(target=self.run)
        self.daemon = True
        self.log = logging.getLogger("philip.status")
        self.url = url
        self.interval = interval
        self.kill = Event()
        self.retries = 0
    
    def calculate_backoff(self) -> float:
        rnd = random.uniform(0, 1)
        retries = min(self.retries, 1000)
        t = (2 * 2 ** retries) + rnd
        self.log.debug("Backoff: 2 * (2 ** %d) + %f = %f", retries, rnd, t)
        # T can never exceed self.interval
        return max(0, min(self.interval, t))
    
    def run(self) -> None:
        with httpx.Client(http2=True) as client:
            while not self.kill.is_set():
                start_time = time.time()
                try:
                    self.retries += 1
                    response = client.get(self.url)
                    response.raise_for_status()
                except httpx.HTTPError as error:
                    self.log.error("Failed to connect to uptime-kuma: %r: %r", self.url, error, exc_info=error)
                    timeout = self.calculate_backoff()
                    self.log.warning("Waiting %d seconds before retrying ping.", timeout)
                    time.sleep(timeout)
                    continue

                self.retries = 0
                end_time = time.time()
                timeout = self.interval - (end_time - start_time)
                self.kill.wait(timeout)


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
        self.uptime_thread = None

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        if CONFIG["jimmy"].get("uptime_kuma_url"):
            self.uptime_thread = KumaThread(
                CONFIG["jimmy"]["uptime_kuma_url"], 
                CONFIG["jimmy"].get("uptime_kuma_interval", 60.0)
            )
            self.uptime_thread.start()
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
        if self.thread:
            self.thread.kill.set()
            await asyncio.get_event_loop().run_in_executor(None, self.thread.join)
        await super().close()


bot = Client(
    command_prefix=commands.when_mentioned_or("h!", "H!"),
    case_insensitive=True,
    strip_after_prefix=True,
    debug_guilds=CONFIG["jimmy"].get("debug_guilds")
)

for ext in ("ytdl", "net", "screenshot", "ollama", "ffmeta"):
    try:
        bot.load_extension(f"cogs.{ext}")
    except discord.ExtensionError as e:
        log.error(f"Failed to load extension cogs.{ext}", exc_info=e)
    else:
        log.info(f"Loaded extension cogs.{ext}")


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
        "%s deleted message %s>%s: %r", ctx.author, ctx.channel.name, message.id, message.content
    )
    await message.delete(delay=3)
    await ctx.respond(f"\N{white heavy check mark} Deleted message by {message.author.display_name}.")
    await ctx.delete(delay=15)


if not CONFIG["jimmy"].get("token"):
    log.critical("No token specified in config.toml. Exiting. (hint: set jimmy.token in config.toml)")
    sys.exit(1)

bot.run(CONFIG["jimmy"]["token"])
