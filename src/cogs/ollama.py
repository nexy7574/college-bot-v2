import asyncio
import collections
import json
import logging
import textwrap
import time
import typing
import io
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
                    default="llama2-uncensored:latest"
                )
            ],
            server: typing.Annotated[
                str,
                discord.Option(
                    str,
                    "The server to use for ollama.",
                    default=SERVER_KEYS[0],
                    choices=SERVER_KEYS
                )
            ],
    ):
        with open("./assets/ollama-prompt.txt") as file:
            system_prompt = file.read()
        await ctx.defer()

        model = model.casefold()
        try:
            model, tag = model.split(":", 1)
            model = model + ":" + tag
            self.log.debug("Model %r already has a tag")
        except ValueError:
            model = model + ":latest"
            self.log.debug("Resolved model to %r" % model)

        if server not in CONFIG["ollama"]:
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
            await ctx.respond(embed=embed)

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
                def progress_bar(value: float, action: str = None):
                    bar = "\N{large green square}" * round(value / 10)
                    bar += "\N{white large square}" * (10 - len(bar))
                    bar += f" {value:.2f}%"
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

                    async for line in self.ollama_stream(response.content):
                        if time.time() >= (last_update + 5.1):
                            if line.get("total") is not None and line.get("completed") is not None:
                                percent = (line["completed"] / line["total"]) * 100
                            else:
                                percent = 50.0

                            embed.fields[0].value = progress_bar(percent, line["status"])
                            await ctx.edit(embed=embed)
                            last_update = time.time()
            else:
                self.log.debug("Model %r already exists on server.", model)

            embed = discord.Embed(
                title="Generating response...",
                description=">>> ",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(
                name="Prompt",
                value=">>> " + textwrap.shorten(query, width=1020, placeholder="..."),
                inline=False
            )
            embed.set_footer(text="Using server %r" % server, icon_url=server_config.get("icon_url"))
            view = OllamaView(ctx)
            try:
                await ctx.edit(embed=embed, view=view)
            except discord.NotFound:
                await ctx.respond(embed=embed, view=view)
            self.log.debug("Beginning to generate response.")
            async with session.post(
                "/api/generate",
                json={
                    "model": model,
                    "prompt": query,
                    "system": system_prompt,
                    "stream": True
                },
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
                    
                    await ctx.edit(embeds=embeds)
                else:
                    await ctx.edit(embed=embed)

def setup(bot):
    bot.add_cog(Ollama(bot))
