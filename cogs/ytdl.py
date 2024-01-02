import asyncio
import functools
import logging
import tempfile
import textwrap
import typing
from pathlib import Path
from urllib.parse import urlparse

import discord
import yt_dlp
from discord.ext import commands

COOKIES_TXT = Path.cwd() / "cookies.txt"


class YTDLCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.log = logging.getLogger("jimmy.cogs.ytdl")
        self.common_formats = {
            "144p": "17",  # mp4 (h264+aac) v
            "240p": "133+139",
            "360p": "18",
            "480p": "135+139",
            "720p": "22",
            "1080p": "137+140",
            "1440p": "248+251",   # webm (vp9+opus) v
            "2160p": "313+251",
            "mp3": "ba[filesize<25M]",
            "m4a": "ba[ext=m4a][filesize<25M]",
            "opus": "ba[ext=webm][filesize<25M]",
            "vorbis": "ba[ext=webm][filesize<25M]",
            "ogg": "ba[ext=webm][filesize<25M]",
        }
        self.default_options = {
            "noplaylist": True,
            "nocheckcertificate": True,
            "no_color": True,
            "noprogress": True,
            "logger": self.log,
            "format": "((bv+ba/b)[vcodec!=h265][vcodec!=av01][filesize<15M]/b[filesize<=15M]/b)",
            "outtmpl": f"%(title).50s.%(ext)s",
            "format_sort": [
                "vcodec:h264",
                "acodec:aac",
                "vcodec:vp9",
                "acodec:opus",
                "acodec:vorbis",
                "vcodec:vp8",
                "ext",
            ],
            "merge_output_format": "webm/mp4/mov/m4a/oga/ogg/mp3/mka/mkv",
            "source_address": "0.0.0.0",
            "concurrent_fragment_downloads": 4,
            "max_filesize": (25 * 1024 * 1024) - 256
        }
        self.colours = {
            "youtube.com": 0xff0000,
            "tiktok.com": 0x25F5EF,
            "instagram.com": 0xe1306c,
            "shronk.net": 0xFFF952
        }

    @commands.slash_command(name="yt-dl")
    @commands.max_concurrency(1, wait=False)
    # @commands.bot_has_permissions(send_messages=True, embed_links=True, attach_files=True)
    async def yt_dl_command(
            self,
            ctx: discord.ApplicationContext,
            url: typing.Annotated[
                str,
                discord.Option(
                    str,
                    description="The URL to download from.",
                    required=True
                )
            ],
            user_format: typing.Annotated[
                typing.Optional[str],
                discord.Option(
                    str,
                    name="format",
                    description="The name of the format to download. Can also specify resolutions for youtube.",
                    required=False,
                    default=None
                )
            ],
            audio_only: typing.Annotated[
                bool,
                discord.Option(
                    bool,
                    name="audio-only",
                    description="Whether to convert result into an m4a file. Overwrites `format` if True.",
                    required=False,
                    default=False,
                )
            ],
            snip: typing.Annotated[
                typing.Optional[str],
                discord.Option(
                    str,
                    description="A start and end position to trim. e.g. 00:00:00-00:10:00.",
                    required=False
                )
            ]
    ):
        """Runs yt-dlp and outputs into discord."""
        await ctx.defer()
        options = self.default_options.copy()
        description = ""

        with tempfile.TemporaryDirectory(prefix="jimmy-ytdl-") as temp_dir:
            temp_dir = Path(temp_dir)
            paths = {
                target: str(temp_dir)
                for target in (
                    "home",
                    "temp",
                )
            }

            chosen_format = self.default_options["format"]
            if user_format:
                if user_format in self.common_formats:
                    chosen_format = self.common_formats[user_format]
                else:
                    chosen_format = user_format

            if audio_only:
                # Overwrite format here to be best audio under 25 megabytes.
                chosen_format = "ba[filesize<20M]"
                # Also force sorting by the best audio bitrate first.
                options["format_sort"] = [
                    "abr",
                    "br"
                ]
                options["postprocessors"] = [
                    {"key": "FFmpegExtractAudio", "preferredquality": "96", "preferredcodec": "best"}
                ]
            options["format"] = chosen_format
            options["paths"] = paths

            with yt_dlp.YoutubeDL(options) as downloader:
                await ctx.respond(
                    embed=discord.Embed().set_footer(text="Downloading (step 1/10)")
                )
                try:
                    # noinspection PyTypeChecker
                    extracted_info = await asyncio.to_thread(downloader.extract_info, url, download=False)
                except yt_dlp.utils.DownloadError as e:
                    title = "error"
                    description = str(e)
                    thumbnail_url = webpage_url = None
                else:
                    title = extracted_info.get("title", url)
                    title = textwrap.shorten(title, 100)
                    thumbnail_url = extracted_info.get("thumbnail") or None
                    webpage_url = extracted_info.get("webpage_url") or None

                    chosen_format = extracted_info.get("format")
                    chosen_format_id = extracted_info.get("format_id")
                    final_extension = extracted_info.get("ext")
                    format_note = extracted_info.get("format_note", "%s (%s)" % (chosen_format, chosen_format_id))
                    resolution = extracted_info.get("resolution")
                    fps = extracted_info.get("fps")
                    vcodec = extracted_info.get("vcodec")
                    acodec = extracted_info.get("acodec")
                    filesize = extracted_info.get("filesize", extracted_info.get("filesize_approx", 1))

                    lines = []
                    if chosen_format and chosen_format_id:
                        lines.append(
                            "* Chosen format: `%s` (`%s`)" % (chosen_format, chosen_format_id),
                        )
                    if format_note:
                        lines.append("* Format note: %r" % format_note)
                    if final_extension:
                        lines.append("* File extension: " + final_extension)
                    if resolution:
                        _s = resolution
                        if fps:
                            _s += " @ %s FPS" % fps
                        lines.append("* Resolution: " + _s)
                    if vcodec or acodec:
                        lines.append("%s+%s" % (vcodec or "N/A", acodec or "N/A"))
                    if filesize:
                        lines.append("* Filesize: %s" % yt_dlp.utils.format_bytes(filesize))

                    if lines:
                        description += "\n"
                        description += "\n".join(lines)

                domain = urlparse(webpage_url).netloc
                await ctx.edit(
                    embed=discord.Embed(
                        title=title,
                        description=description,
                        url=webpage_url,
                        colour=self.colours.get(domain, discord.Colour.og_blurple())
                    ).set_footer(text="Downloading (step 2/10)").set_thumbnail(url=thumbnail_url)
                )
                try:
                    await asyncio.to_thread(functools.partial(downloader.download, [url]))
                except yt_dlp.DownloadError as e:
                    logging.error(e, exc_info=True)
                    return await ctx.edit(
                        embed=discord.Embed(
                            title="Error",
                            description=f"Download failed:\n```\n{e}\n```",
                            colour=discord.Colour.red(),
                            url=webpage_url,
                        ),
                        delete_after=120,
                    )
                try:
                    file = next(temp_dir.glob("*." + extracted_info["ext"]))
                except StopIteration:
                    return await ctx.edit(
                        embed=discord.Embed(
                            title="Error",
                            description="Failed to locate downloaded video file.\n"
                                        f"Files: {', '.join(list(map(str, temp_dir.iterdir())))}",
                            colour=discord.Colour.red(),
                            url=webpage_url
                        )
                    )

                if snip:
                    try:
                        trim_start, trim_end = snip.split("-")
                    except ValueError:
                        trim_start, trim_end = snip, None
                    trim_start = trim_start or "00:00:00"
                    trim_end = trim_end or extracted_info.get("duration_string", "00:30:00")
                    new_file = temp_dir / ("output." + file.suffix)
                    args = [
                        "-hwaccel",
                        "auto",
                        "-ss",
                        trim_start,
                        "-i",
                        str(file),
                        "-to",
                        trim_end,
                        "-preset",
                        "faster",
                        "-crf",
                        "28",
                        "-deadline",
                        "realtime",
                        "-cpu-used",
                        "5",
                        "-movflags",
                        "faststart",
                        "-b:a",
                        "48k",
                        "-y",
                        "-strict",
                        "2",
                        str(new_file)
                    ]
                    async with ctx.channel.typing():
                        await ctx.edit(
                            embed=discord.Embed(
                                title=f"Trimming from {trim_start} to {trim_end}.",
                                description="Please wait, this may take a couple of minutes.",
                                colour=discord.Colour.og_blurple(),
                                timestamp=discord.utils.utcnow()
                            )
                        )
                        process = await asyncio.create_subprocess_exec(
                            "ffmpeg",
                            *args,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        stdout, stderr = await process.communicate()
                        if process.returncode != 0:
                            return await ctx.edit(
                                embed=discord.Embed(
                                    title="Error",
                                    description=f"Trimming failed:\n```\n{stderr.decode()}\n```",
                                    colour=discord.Colour.red(),
                                    url=webpage_url
                                )
                            )
                        file = new_file

                stat = file.stat()
                size_bytes = stat.st_size
                if size_bytes >= ((25 * 1024 * 1024) - 256):
                    return await ctx.edit(
                        embed=discord.Embed(
                            title="Error",
                            description=f"File is too large to upload ({round(size_bytes / 1024 / 1024)}MB).",
                            colour=discord.Colour.red(),
                            url=webpage_url
                        )
                    )
                size_megabits = (size_bytes * 8) / 1024 / 1024
                eta_seconds = size_megabits / 20
                upload_file = await asyncio.to_thread(discord.File, file, filename=file.name)
                await ctx.edit(
                    embed=discord.Embed(
                        title="Uploading...",
                        description=f"ETA <t:{int(eta_seconds + discord.utils.utcnow().timestamp()) + 2}:R>",
                        colour=discord.Colour.og_blurple(),
                        timestamp=discord.utils.utcnow()
                    )
                )
                try:
                    await ctx.edit(
                        file=upload_file,
                        embed=discord.Embed(
                            title=f"Downloaded {title}!",
                            colour=discord.Colour.green(),
                            timestamp=discord.utils.utcnow(),
                            url=webpage_url
                        )
                    )
                except discord.HTTPException as e:
                    self.log.error(e, exc_info=True)
                    return await ctx.edit(
                        embed=discord.Embed(
                            title="Error",
                            description=f"Upload failed:\n```\n{e}\n```",
                            colour=discord.Colour.red(),
                            url=webpage_url
                        )
                    )

def setup(bot):
    bot.add_cog(YTDLCog(bot))
