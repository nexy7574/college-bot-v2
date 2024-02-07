import asyncio
import io
import logging
import typing

import PIL.Image

import discord
import httpx

from discord.ext import commands


class FFMeta(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("jimmy.cogs.ffmeta")

    def jpegify_image(self, input_file: io.BytesIO, quality: int = 50, image_format: str = "jpeg") -> io.BytesIO:
        quality = min(1, max(quality, 100))
        img_src = PIL.Image.open(input_file)
        img_dst = io.BytesIO()
        self.log.debug("Saving input file (%r) as %r with quality %r%%", input_file, image_format, quality)
        img_src.save(img_dst, format=image_format, quality=quality)
        img_dst.seek(0)
        return img_dst

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

    @commands.slash_command()
    async def jpegify(
            self,
            ctx: discord.ApplicationContext,
            url: str = None,
            attachment: discord.Attachment = None,
            quality: typing.Annotated[
                int,
                discord.Option(
                    int,
                    description="The quality of the resulting image from 1%-100%",
                    default=50,
                    min_value=1,
                    max_value=100
                )
            ] = 50,
            image_format: typing.Annotated[
                str,
                discord.Option(
                    str,
                    description="The format of the resulting image",
                    choices=["jpeg", "png", "webp", "avif"],
                    default="jpeg"
                )
            ] = "jpeg"
    ):
        """Converts a given URL or attachment to a JPEG"""
        if url is None:
            if attachment is None:
                return await ctx.respond("No URL or attachment provided")
            url = attachment.url

        await ctx.defer()

        src = io.BytesIO()
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code != 200:
                return
            src.write(response.content)

        try:
            dst = await asyncio.to_thread(self.jpegify_image, src, quality, image_format)
        except Exception as e:
            await ctx.respond(f"Failed to convert image: `{e}`.")
            self.log.error("Failed to convert image %r: %r", url, e)
            return
        else:
            await ctx.respond(file=discord.File(dst, filename=f"jpegified.{image_format}"))


def setup(bot: commands.Bot):
    bot.add_cog(FFMeta(bot))
