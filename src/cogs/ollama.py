import collections
import json
import logging
import time
import typing
from fnmatch import fnmatch

import aiohttp
import discord
from discord.ext import commands
from conf import CONFIG


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
                    default=None
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

        if query is None:
            class InputPrompt(discord.ui.Modal):
                def __init__(self, is_owner: bool):
                    super().__init__(
                        discord.ui.InputText(
                            label="User Prompt",
                            placeholder="Enter prompt",
                            min_length=1,
                            max_length=4000,
                            style=discord.InputTextStyle.long,
                        ),
                        title="Enter prompt",
                        timeout=120,
                    )
                    if is_owner:
                        self.add_item(
                            discord.ui.InputText(
                                label="System Prompt",
                                placeholder="Enter prompt",
                                min_length=1,
                                max_length=4000,
                                style=discord.InputTextStyle.long,
                                value=system_prompt,
                            )
                        )

                    self.user_prompt = None
                    self.system_prompt = system_prompt

                async def callback(self, interaction: discord.Interaction):
                    self.user_prompt = self.children[0].value
                    if len(self.children) > 1:
                        self.system_prompt = self.children[1].value
                    await interaction.response.defer()
                    self.stop()

            modal = InputPrompt(await self.bot.is_owner(ctx.author))
            await ctx.send_modal(modal)
            await modal.wait()
            query = modal.user_prompt
            if not modal.user_prompt:
                return
            system_prompt = modal.system_prompt or system_prompt
        else:
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
        ) as session:
            embed = discord.Embed(
                title="Checking server...",
                description=f"Checking that specified model and tag ({model}) are available on the server.",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            await ctx.respond(embed=embed)

            try:
                async with session.post("/api/show", json={"name": model}) as resp:
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

            embed = discord.Embed(
                title="Generating response...",
                description=">>> \u200b",
                color=discord.Color.blurple()
            )
            async with session.post(
                "/api/generate",
                json={
                    "model": model,
                    "prompt": query,
                    "format": "json",
                    "system": system_prompt,
                    "stream": True
                }
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
                async for line in self.ollama_stream(response.content):
                    if line.get("done", False) is True or time.time() >= (last_update + 5.1):
                        if line.get("done"):
                            embed.title = "Done!"
                            embed.color = discord.Color.green()
                        embed.description += line["response"]
                        if len(embed.description) >= 4096:
                            embed.description = embed.description[:4093] + "..."
                            break
                        await ctx.edit(embed=embed)
                        last_update = time.time()


def setup(bot):
    bot.add_cog(Ollama(bot))
