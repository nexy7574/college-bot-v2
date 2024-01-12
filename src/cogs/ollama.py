import asyncio
import json
import logging
import os
import textwrap
import time
import typing
import base64
import io
import humanize

from discord.ui import View, button
from fnmatch import fnmatch

import aiohttp
import discord
from discord.ext import commands
from conf import CONFIG


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


SERVER_KEYS = list(CONFIG["ollama"].keys())


class Ollama(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("jimmy.cogs.ollama")
        self.last_server = 0
        self.contexts = {}

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
            if context not in self.contexts:
                await ctx.respond("Invalid context key.")
                return
            return await ctx.respond("Context is currently disabled.", ephemeral=True)
        with open("./assets/ollama-prompt.txt") as file:
            system_prompt = file.read()
        await ctx.defer()

        model = model.casefold()
        try:
            model, tag = model.split(":", 1)
            model = model + ":" + tag
            self.log.debug("Model %r already has a tag", model)
        except ValueError:
            model = model + ":latest"
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
                image_data = base64.b64encode(data.read()).decode("utf-8")
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
                timeout=aiohttp.ClientTimeout(0)
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

            params = {}
            if give_acid is True:
                params["temperature"] = 500
                params["top_k"] = 500
                params["top_p"] = 500

            payload = {
                "model": model,
                "prompt": query,
                "system": system_prompt,
                "stream": True,
                "options": params,
            }
            if context is not None:
                payload["context"] = self.contexts[context]
            if image_data:
                payload["images"] = [image_data]
            async with session.post(
                "/api/generate",
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
                context = []
                if not view.cancel.is_set():
                    async for line in self.ollama_stream(response.content):
                        if "context" in line:
                            context = line["context"]
                        buffer.write(line["response"])
                        embed.description += line["response"]
                        embed.timestamp = discord.utils.utcnow()
                        if len(embed.description) >= 4096:
                            embed.description = embed.description = "..." + line["response"]

                        if view.cancel.is_set():
                            break

                        if time.time() >= (last_update + 5.1):
                            await ctx.edit(embed=embed, view=view)
                            self.log.debug(f"Updating message ({last_update} -> {time.time()})")
                            last_update = time.time()
                view.stop()
                if context:
                    self.contexts[key] = context
                    embed.add_field(name="Context Key", value=key, inline=True)
                self.log.debug("Ollama finished consuming.")
                embed.title = "Done!"
                embed.color = discord.Color.green()

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
                    total_duration = humanize.naturaldelta(line["total_duration"] / 1e9)
                    load_duration = humanize.naturaldelta(line["load_duration"] / 1e9)
                    prompt_eval_duration = humanize.naturaldelta(line["prompt_eval_duration"] / 1e9)
                    eval_duration = humanize.naturaldelta(line["eval_duration"] / 1e9)

                    embed = discord.Embed(
                        title="Timings",
                        description=f"Total: {total_duration}\nLoad: {load_duration}\n"
                                    f"Prompt Eval: {prompt_eval_duration}\nEval: {eval_duration}\n"
                                    f"Prompt Tokens: {line['prompt_eval_count']:,}\n"
                                    f"Response Tokens: {line['eval_count']:,}",
                        color=discord.Color.blurple(),
                        timestamp=discord.utils.utcnow()
                    )
                    return await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Ollama(bot))
