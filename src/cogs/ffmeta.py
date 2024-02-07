import asyncio
import io
import json
import logging
import tempfile
import typing
from pathlib import Path

import PIL.Image

import discord
import httpx

from discord.ext import commands
from conf import VERSION


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
                    choices=["jpeg", "webp"],
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
        async with httpx.AsyncClient(
            headers={"User-Agent": f"DiscordBot (Jimmy, v2, {VERSION}, +https://github.com/nexy7574/college-bot-v2)"}
        ) as client:
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

    @commands.slash_command()
    async def opusinate(
            self,
            ctx: discord.ApplicationContext,
            url: str = None,
            attachment: discord.Attachment = None,
            bitrate: typing.Annotated[
                int,
                discord.Option(
                    int,
                    description="The bitrate in kilobits of the resulting audio from 1-512",
                    default=96,
                    min_value=0,
                    max_value=512
                )
            ] = 96,
            mono: typing.Annotated[
                bool,
                discord.Option(
                    bool,
                    description="Whether to convert the audio to mono",
                    default=False
                )
            ] = False
    ):
        """Converts a given URL or attachment to an Opus file"""
        if bitrate == 0:
            bitrate = 0.5
        if mono:
            bitrate = min(bitrate, 256)
        filename = "opusinated.ogg"
        if url is None:
            if attachment is None:
                return await ctx.respond("No URL or attachment provided")
            url = attachment.url
            filename = str(Path(attachment.filename).with_suffix(".ogg"))

        await ctx.defer()
        channels = 2 if not mono else 1
        with tempfile.NamedTemporaryFile() as temp:
            async with httpx.AsyncClient(
                headers={
                    "User-Agent": f"DiscordBot (Jimmy, v2, {VERSION}, +https://github.com/nexy7574/college-bot-v2)"
                }
            ) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    return
                temp.write(response.content)
                temp.flush()

            probe_process = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-i",
                temp.name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await probe_process.communicate()
            stdout = stdout.decode("utf-8", "replace")
            data = {"format": {"duration": 195}}  # 3 minutes and 15 seconds is the 2023 average.
            if stdout:
                try:
                    data = json.loads(stdout)
                except json.JSONDecodeError:
                    pass

            duration = float(data["format"].get("duration", 195))
            max_end_size = ((bitrate * duration * channels) / 8) * 1024
            if max_end_size > (24.75 * 1024 * 1024):
                return await ctx.respond(
                    "The file would be too large to send ({:,.2f} MiB).".format(max_end_size / 1024 / 1024)
                )

            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "warning",
                "-stats",
                "-i",
                temp.name,
                "-c:a", "libopus",
                "-b:a", f"{bitrate}k",
                "-vn",
                "-sn",
                "-ac", str(channels),
                "-f", "opus",
                "-y",
                "pipe:1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
        stderr = stderr.decode("utf-8", "replace")

        file = io.BytesIO(stdout)
        if (fs := len(file.getvalue())) > (24.75 * 1024 * 1024):
            return await ctx.respond("The file is too large to send ({:,.2f} MiB).".format(fs / 1024 / 1024))
        if not fs:
            await ctx.respond("Failed to convert audio. See below.")
        else:
            await ctx.respond(file=discord.File(file, filename=filename))

        paginator = commands.Paginator(prefix="```", suffix="```")
        for line in stderr.splitlines():
            if line.strip().startswith(":"):
                continue
            paginator.add_line(f"{line}"[:2000])

        for page in paginator.pages:
            await ctx.respond(page, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(FFMeta(bot))
