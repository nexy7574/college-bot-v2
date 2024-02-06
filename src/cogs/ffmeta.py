import asyncio
import logging

import discord

from discord.ext import commands


class FFMeta(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("jimmy.cogs.ffmeta")

    @commands.slash_command()
    async def ffprobe(self, ctx: discord.ApplicationContext, url: str = None, attachment: discord.Attachment = None):
        """Runs ffprobe on a given URL or attachment"""
        if url is None:
            if attachment is None:
                return await ctx.respond("No URL or attachment provided")
            url = attachment.url

        await ctx.defer()

        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-hide_banner",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        stdout = stdout.decode("utf-8", "replace")
        stderr = stderr.decode("utf-8", "replace")

        paginator = commands.Paginator(prefix="```", suffix="```")
        for line in stdout.splitlines():
            if stderr:
                paginator.add_line(f"[OUT] {line}"[:2000])
            else:
                paginator.add_line(line[:2000])

        for line in stderr.splitlines():
            paginator.add_line(f"[ERR] {line}"[:2000])

        for page in paginator.pages:
            await ctx.respond(page)


def setup(bot: commands.Bot):
    bot.add_cog(FFMeta(bot))
