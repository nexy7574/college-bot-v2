import asyncio
import json
import logging
import os
import textwrap
import time
import typing
import base64
import io
import redis
from discord import Interaction

from discord.ui import View, button
from fnmatch import fnmatch

import aiohttp
from yarl import URL
import discord
from discord.ext import commands
from conf import CONFIG


def get_time_spent(nanoseconds: int) -> str:
    hours, minutes, seconds = 0, 0, 0
    seconds = nanoseconds / 1e9
    if seconds >= 60:
        minutes, seconds = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)

    result = []
    if seconds:
        if seconds != 1:
            label = "seconds"
        else:
            label = "second"
        result.append(f"{round(seconds)} {label}")
    if minutes:
        if minutes != 1:
            label = "minutes"
        else:
            label = "minute"
        result.append(f"{round(minutes)} {label}")
    if hours:
        if hours != 1:
            label = "hours"
        else:
            label = "hour"
        result.append(f"{round(hours)} {label}")
    return ", ".join(reversed(result))


class OllamaView(View):
    def __init__(self, ctx: discord.ApplicationContext):
        super().__init__(timeout=3600, disable_on_timeout=True)
        self.ctx = ctx
        self.cancel = asyncio.Event()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.ctx.user

    @button(label="Stop", style=discord.ButtonStyle.danger, emoji="\N{wastebasket}\U0000fe0f")
    async def _stop(self, btn: discord.ui.Button, interaction: discord.Interaction):
        self.cancel.set()
        btn.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


class ChatHistory:
    def __init__(self):
        self._internal = {}
        self.log = logging.getLogger("jimmy.cogs.ollama.history")
        no_ping = CONFIG["redis"].pop("no_ping", False)
        self.redis = redis.Redis(**CONFIG["redis"])
        if no_ping is False:
            assert self.redis.ping(), "Redis appears to be offline."

    def load_thread(self, thread_id: str):
        value: str = self.redis.get("threads:" + thread_id)
        if value:
            self.log.debug("Loaded thread %r: %r", thread_id, value)
            loaded = json.loads(value)
            self._internal.update(loaded)
            return self.get_thread(thread_id)

    def save_thread(self, thread_id: str):
        self.log.info("Saving thread:%s - %r", thread_id, self._internal[thread_id])
        self.redis.set(
            "threads:" + thread_id, json.dumps(self._internal[thread_id])
        )

    def create_thread(self, member: discord.Member, default: str | None = None) -> str:
        """
        Creates a thread, returns its ID.
        """
        key = os.urandom(3).hex()
        self._internal[key] = {
            "member": member.id,
            "seed": round(time.time()),
            "messages": []
        }
        with open("./assets/ollama-prompt.txt") as file:
            system_prompt = default or file.read()
        self.add_message(
            key,
            "system",
            system_prompt
        )
        return key

    @staticmethod
    def _construct_message(role: str, content: str, images: typing.Optional[list[str]]) -> dict[str, str]:
        x = {
            "role": role,
            "content": content
        }
        if images:
            x["images"] = images
        return x

    @staticmethod
    def autocomplete(ctx: discord.AutocompleteContext):
        # noinspection PyTypeChecker
        cog: Ollama = ctx.bot.get_cog("Ollama")
        instance = cog.history
        return list(
            filter(
                lambda v: (ctx.value or v) in v, map(
                    lambda d: list(d.keys()),
                    instance.threads_for(ctx.interaction.user)
                )
            )
        )

    def all_threads(self) -> dict[str, dict[str, list[dict[str, str]] | int]]:
        """Returns all saved threads."""
        return self._internal.copy()

    def threads_for(self, user: discord.Member) -> dict[str, dict[str, list[dict[str, str]] | int]]:
        """Returns all saved threads for a specific user"""
        t = self.all_threads()
        for k, v in t.copy().items():
            if v["member"] != user.id:
                t.pop(k)
        return t

    def add_message(
            self,
            thread: str,
            role: typing.Literal["user", "assistant", "system"],
            content: str,
            images: typing.Optional[list[str]] = None
    ) -> None:
        """
        Appends a message to the given thread.

        :param thread: The thread's ID.
        :param role: The author of the message.
        :param content: The message's actual content.
        :param images: Any images that were attached to the message, in base64.
        :return: None
        """
        new = self._construct_message(role, content, images)
        self.log.debug("Adding message to thread %r: %r", thread, new)
        self._internal[thread]["messages"].append(new)

    def get_history(self, thread: str) -> list[dict[str, str]]:
        """
        Gets the history of a thread.
        """
        if self._internal.get(thread) is None:
            return []
        return self._internal[thread]["messages"].copy()  # copy() makes it immutable.

    def get_thread(self, thread: str) -> dict[str, list[dict[str, str]] | discord.Member | int]:
        """Gets a copy of an entire thread"""
        return self._internal.get(thread, {}).copy()

    def find_thread(self, thread_id: str):
        """Attempts to find a thread."""
        self.log.debug("Checking cache for %r...", thread_id)
        if c := self.get_thread(thread_id):
            return c
        self.log.debug("Checking db for %r...", thread_id)
        if d := self.load_thread(thread_id):
            return d
        self.log.warning("No thread with ID %r found.", thread_id)


SERVER_KEYS = list(CONFIG["ollama"].keys())


class OllamaGetPrompt(discord.ui.Modal):

    def __init__(self, ctx: discord.ApplicationContext, prompt_type: str = "User"):
        super().__init__(
            discord.ui.InputText(
                style=discord.InputTextStyle.long,
                label="%s prompt" % prompt_type,
                placeholder="Enter your prompt here.",
            ),
            timeout=300,
            title="Ollama %s prompt" % prompt_type,
        )
        self.ctx = ctx
        self.prompt_type = prompt_type
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.ctx.user

    async def callback(self, interaction: Interaction):
        await interaction.response.defer()
        self.ctx.interaction = interaction
        self.value = self.children[0].value
        self.stop()


class PromptSelector(discord.ui.View):
    def __init__(self, ctx: discord.ApplicationContext):
        super().__init__(timeout=600, disable_on_timeout=True)
        self.ctx = ctx
        self.system_prompt = None
        self.user_prompt = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        return interaction.user == self.ctx.user

    def update_ui(self):
        if self.system_prompt is not None:
            self.get_item("sys").style = discord.ButtonStyle.secondary  # type: ignore
        if self.user_prompt is not None:
            self.get_item("usr").style = discord.ButtonStyle.secondary  # type: ignore

    @discord.ui.button(label="Set System Prompt", style=discord.ButtonStyle.primary, custom_id="sys")
    async def set_system_prompt(self, btn: discord.ui.Button, interaction: Interaction):
        modal = OllamaGetPrompt(self.ctx, "System")
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.system_prompt = modal.value

    @discord.ui.button(label="Set System Prompt", style=discord.ButtonStyle.primary, custom_id="usr")
    async def set_system_prompt(self, btn: discord.ui.Button, interaction: Interaction):
        modal = OllamaGetPrompt(self.ctx)
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.user_prompt = modal.value

    @discord.ui.button(label="Done", style=discord.ButtonStyle.success, custom_id="done")
    async def done(self, btn: discord.ui.Button, interaction: Interaction):
        self.stop()


class Ollama(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("jimmy.cogs.ollama")
        self.last_server = 0
        self.contexts = {}
        self.history = ChatHistory()

    def next_server(self, increment: bool = True) -> str:
        """Returns the next server key."""
        if increment:
            self.last_server += 1
        return SERVER_KEYS[self.last_server % len(SERVER_KEYS)]

    async def ollama_stream(self, iterator: aiohttp.StreamReader) -> typing.AsyncIterator[dict]:
        async for line in iterator:
            original_line = line
            line = line.decode("utf-8", "replace").strip()
            try:
                line = json.loads(line)
            except json.JSONDecodeError:
                self.log.warning("Unable to decode JSON: %r", original_line)
                continue
            else:
                self.log.debug("Decoded JSON %r -> %r", original_line, line)
            yield line

    async def check_server(self, url: str) -> bool:
        """Checks that a server is online and responding."""
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(10)) as session:
            self.log.debug("Checking if %r is online.", url)
            try:
                async with session.get(url + "/api/tags") as resp:
                    self.log.debug("%r is online.", resp.url.host)
                    return resp.ok
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError):
                self.log.warning("%r is offline.", url, exc_info=True)
                return False

    @commands.slash_command()
    async def ollama(
            self,
            ctx: discord.ApplicationContext,
            query: typing.Annotated[
                str,
                discord.Option(
                    str,
                    "The query to feed into ollama. Not the system prompt.",
                )
            ],
            model: typing.Annotated[
                str,
                discord.Option(
                    str,
                    "The model to use for ollama. Defaults to 'llama2-uncensored:latest'.",
                    default="llama2-uncensored:7b-chat"
                )
            ],
            server: typing.Annotated[
                str,
                discord.Option(
                    str,
                    "The server to use for ollama.",
                    default="next",
                    choices=SERVER_KEYS
                )
            ],
            context: typing.Annotated[
                str,
                discord.Option(
                    str,
                    "The context key of a previous ollama response to use as context.",
                    default=None
                )
            ],
            give_acid: typing.Annotated[
                bool,
                discord.Option(
                    bool,
                    "Whether to give the AI acid, LSD, and other hallucinogens before responding.",
                    default=False
                )
            ],
            image: typing.Annotated[
                discord.Attachment,
                discord.Option(
                    discord.Attachment,
                    "An image to feed into ollama. Only works with llava.",
                    default=None
                )
            ]
    ):
        if context is not None:
            if not self.history.get_thread(context):
                await ctx.respond("Invalid context key.")
                return

        try:
            await ctx.defer()
        except discord.HTTPException:
            pass

        if query == "$":
            v = PromptSelector(ctx)
            await ctx.respond("Select edit your prompts, as desired. Click done when you want to continue.", view=v)
            await v.wait()
            query = v.user_prompt or query

        model = model.casefold()
        try:
            model, tag = model.split(":", 1)
            model = model + ":" + tag
            self.log.debug("Model %r already has a tag", model)
        except ValueError:
            model += ":latest"
            self.log.debug("Resolved model to %r" % model)

        if image:
            if fnmatch(model, "llava:*") is False:
                await ctx.respond(
                    "You can only use images with llava. Switching model to `llava:latest`.",
                    delete_after=5
                )
                model = "llava:latest"

            if image.size > 1024 * 1024 * 25:
                await ctx.respond("Attachment is too large. Maximum size is 25 MB, for sanity. Try compressing it.")
                return
            elif not fnmatch(image.content_type, "image/*"):
                await ctx.respond("Attachment is not an image. Try using a different file.")
                return
            else:
                data = io.BytesIO()
                await image.save(data)
                data.seek(0)
                image_data = base64.b64encode(data.read()).decode()
        else:
            image_data = None

        if server == "next":
            server = self.next_server()
        elif server not in CONFIG["ollama"]:
            await ctx.respond("Invalid server")
            return

        server_config = CONFIG["ollama"][server]
        for model_pattern in server_config["allowed_models"]:
            if fnmatch(model, model_pattern):
                break
        else:
            allowed_models = ", ".join(map(discord.utils.escape_markdown, server_config["allowed_models"]))
            await ctx.respond(f"Invalid model. You can only use one of the following models: {allowed_models}")
            return

        async with aiohttp.ClientSession(
                base_url=server_config["base_url"],
                timeout=aiohttp.ClientTimeout(
                    connect=30,
                    sock_read=10800,
                    sock_connect=30,
                    total=10830
                )
        ) as session:
            embed = discord.Embed(
                title="Checking server...",
                description=f"Checking that specified model and tag ({model}) are available on the server.",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Using server %r" % server, icon_url=server_config.get("icon_url"))
            await ctx.respond(embed=embed)
            if not await self.check_server(server_config["base_url"]):
                for i in range(10):
                    server = self.next_server()
                    embed = discord.Embed(
                        title="Server was offline. Trying next server.",
                        description=f"Trying server {server}...",
                        color=discord.Color.gold(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text="Using server %r" % server, icon_url=server_config.get("icon_url"))
                    await ctx.edit(embed=embed)
                    await asyncio.sleep(1)
                    if await self.check_server(CONFIG["ollama"][server]["base_url"]):
                        server_config = CONFIG["ollama"][server]
                        setattr(session, "_base_url", URL(server_config["base_url"]))
                        break
                else:
                    embed = discord.Embed(
                        title="All servers are offline.",
                        description="Please try again later.",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text="Unable to continue.")
                    return await ctx.edit(embed=embed)

            try:
                self.log.debug("Connecting to %r", server_config["base_url"])
                async with session.post("/api/show", json={"name": model}) as resp:
                    self.log.debug("%r responded.", server_config["base_url"])
                    if resp.status not in [404, 200]:
                        embed = discord.Embed(
                            url=resp.url,
                            title=f"HTTP {resp.status} {resp.reason!r} while checking for model.",
                            description=f"```{await resp.text() or 'No response body'}```"[:4096],
                            color=discord.Color.red(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.set_footer(text="Unable to continue.")
                        return await ctx.edit(embed=embed)
            except aiohttp.ClientConnectionError as e:
                embed = discord.Embed(
                    title="Connection error while checking for model.",
                    description=f"```{e}```"[:4096],
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                embed.set_footer(text="Unable to continue.")
                return await ctx.edit(embed=embed)

            if resp.status == 404:
                self.log.debug("Beginning download of %r", model)

                def progress_bar(_v: float, action: str = None):
                    bar = "\N{large green square}" * round(_v / 10)
                    bar += "\N{white large square}" * (10 - len(bar))
                    bar += f" {_v:.2f}%"
                    if action:
                        return f"{action} {bar}"
                    return bar

                embed = discord.Embed(
                    title=f"Downloading {model!r}",
                    description=f"Downloading {model!r} from {server_config['base_url']}",
                    color=discord.Color.blurple(),
                    timestamp=discord.utils.utcnow()
                )
                embed.add_field(name="Progress", value=progress_bar(0))
                await ctx.edit(embed=embed)

                last_update = time.time()

                async with session.post("/api/pull", json={"name": model, "stream": True}, timeout=None) as response:
                    if response.status != 200:
                        embed = discord.Embed(
                            url=response.url,
                            title=f"HTTP {response.status} {response.reason!r} while downloading model.",
                            description=f"```{await response.text() or 'No response body'}```"[:4096],
                            color=discord.Color.red(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.set_footer(text="Unable to continue.")
                        return await ctx.edit(embed=embed)
                    view = OllamaView(ctx)
                    async for line in self.ollama_stream(response.content):
                        if view.cancel.is_set():
                            embed = discord.Embed(
                                title="Download cancelled.",
                                colour=discord.Colour.red(),
                                timestamp=discord.utils.utcnow()
                            )
                            return await ctx.edit(embed=embed, view=None)
                        if time.time() >= (last_update + 5.1):
                            if line.get("total") is not None and line.get("completed") is not None:
                                percent = (line["completed"] / line["total"]) * 100
                            else:
                                percent = 50.0

                            embed.fields[0].value = progress_bar(percent, line["status"])
                            await ctx.edit(embed=embed, view=view)
                            last_update = time.time()
            else:
                self.log.debug("Model %r already exists on server.", model)

            key = os.urandom(6).hex()

            embed = discord.Embed(
                title="Generating response...",
                description=">>> ",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_author(
                name=model,
                url="https://ollama.ai/library/" + model.split(":")[0],
                icon_url="https://ollama.ai/public/ollama.png"
            )
            embed.add_field(
                name="Prompt",
                value=">>> " + textwrap.shorten(query, width=1020, placeholder="..."),
                inline=False
            )
            embed.set_footer(text="Using server %r" % server, icon_url=server_config.get("icon_url"))
            if image_data:
                if (image.height / image.width) >= 1.5:
                    embed.set_image(url=image.url)
                else:
                    embed.set_thumbnail(url=image.url)
            view = OllamaView(ctx)
            try:
                await ctx.edit(embed=embed, view=view)
            except discord.NotFound:
                await ctx.respond(embed=embed, view=view)
            self.log.debug("Beginning to generate response with key %r.", key)

            if context is None:
                context = self.history.create_thread(ctx.user, system_query)
            elif context is not None and self.history.get_thread(context) is None:
                __thread = self.history.find_thread(context)
                if not __thread:
                    return await ctx.respond("Invalid thread ID.")
                else:
                    context = list(__thread.keys())[0]

            messages = self.history.get_history(context)
            user_message = {
                "role": "user",
                "content": query
            }
            if image_data:
                user_message["images"] = [image_data]
            messages.append(user_message)

            params = {"seed": self.history.get_thread(context)["seed"]}
            if give_acid is True:
                params["temperature"] = 2
                params["top_k"] = 0
                params["top_p"] = 2
                params["repeat_penalty"] = 2

            payload = {
                "model": model,
                "stream": True,
                "options": params,
                "messages": messages
            }
            async with session.post(
                "/api/chat",
                json=payload,
            ) as response:
                if response.status != 200:
                    embed = discord.Embed(
                        url=response.url,
                        title=f"HTTP {response.status} {response.reason!r} while generating response.",
                        description=f"```{await response.text() or 'No response body'}```"[:4096],
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text="Unable to continue.")
                    return await ctx.edit(embed=embed)

                last_update = time.time()
                buffer = io.StringIO()
                if not view.cancel.is_set():
                    async for line in self.ollama_stream(response.content):
                        buffer.write(line["message"]["content"])
                        embed.description += line["message"]["content"]
                        embed.timestamp = discord.utils.utcnow()
                        if len(embed.description) >= 4000:
                            embed.description = "[...]" + line["message"]["content"]
                        if len(embed.description) >= 3250:
                            embed.colour = discord.Color.gold()
                            embed.set_footer(text="Warning: {:,}/4096 characters.".format(len(embed.description)))
                        else:
                            embed.colour = discord.Color.blurple()
                            embed.set_footer(text="Using server %r" % server, icon_url=server_config.get("icon_url"))

                        if view.cancel.is_set():
                            break

                        if time.time() >= (last_update + 5.1):
                            await ctx.edit(embed=embed, view=view)
                            self.log.debug(f"Updating message ({last_update} -> {time.time()})")
                            last_update = time.time()
                view.stop()
                self.history.add_message(context, "user", user_message["content"], user_message.get("images"))
                self.history.add_message(context, "assistant", buffer.getvalue())
                self.history.save_thread(context)

                embed.add_field(name="Context Key", value=context, inline=True)
                self.log.debug("Ollama finished consuming.")
                embed.title = "Done!"
                embed.colour = discord.Color.green()

                value = buffer.getvalue()
                if len(value) >= 4096:
                    embeds = [discord.Embed(title="Done!", colour=discord.Color.green())]
                    
                    current_page = ""
                    for word in value.split():
                        if len(current_page) + len(word) >= 4096:
                            embeds.append(discord.Embed(description=current_page))
                            current_page = ""
                        current_page += word + " "
                    else:
                        embeds.append(discord.Embed(description=current_page))
                    
                    await ctx.edit(embeds=embeds, view=None)
                else:
                    await ctx.edit(embed=embed, view=None)

                if line.get("done"):
                    total_duration = get_time_spent(line["total_duration"])
                    load_duration = get_time_spent(line["load_duration"])
                    prompt_eval_duration = get_time_spent(line["prompt_eval_duration"])
                    eval_duration = get_time_spent(line["eval_duration"])

                    embed = discord.Embed(
                        title="Timings",
                        description=f"Total: {total_duration}\nLoad: {load_duration}\n"
                                    f"Prompt Eval: {prompt_eval_duration}\nEval: {eval_duration}",
                        color=discord.Color.blurple(),
                        timestamp=discord.utils.utcnow()
                    )
                    return await ctx.respond(embed=embed, ephemeral=True)

    @commands.slash_command(name="ollama-history")
    async def ollama_history(
            self,
            ctx: discord.ApplicationContext,
            thread_id: typing.Annotated[
                str,
                discord.Option(
                    name="thread_id",
                    description="Thread/Context ID",
                    type=str,
                    autocomplete=ChatHistory.autocomplete,
                )
            ]
    ):
        """Shows the history for a thread."""
        # await ctx.defer(ephemeral=True)
        paginator = commands.Paginator("", "", 4000, "\n\n")

        thread = self.history.load_thread(thread_id)
        if not thread:
            return await ctx.respond("No thread with that ID exists.")
        history = self.history.get_history(thread_id)
        if not history:
            return await ctx.respond("No history or invalid context key.")

        for message in history:
            if message["role"] == "system":
                continue
            max_length = 4000 - len("> **%s**: " % message["role"])
            paginator.add_line(
                "> **{}**: {}".format(message["role"], textwrap.shorten(message["content"], max_length))
            )

        embeds = []
        for page in paginator.pages:
            embeds.append(
                discord.Embed(
                    description=page
                )
            )
        ephemeral = len(embeds) > 1
        for chunk in discord.utils.as_chunks(iter(embeds or [discord.Embed(title="No Content.")]), 10):
            await ctx.respond(embeds=chunk, ephemeral=ephemeral)


def setup(bot):
    bot.add_cog(Ollama(bot))
