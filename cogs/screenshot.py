import datetime
import io
import logging
import shutil
import tempfile
import time
import zipfile
from urllib.parse import urlparse
from PIL import Image

import discord
from discord.ext import commands
import asyncio
import aiohttp
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService


class ScreenshotCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.chrome_options = ChromeOptions()
        self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--disable-dev-shm-usage")
        # self.chrome_options.add_argument("--disable-gpu")
        self.chrome_options.add_argument("--disable-extensions")
        self.chrome_options.add_argument("--incognito")

        prefs = {
            # "download.open_pdf_in_system_reader": False,
            # "download.prompt_for_download": True,
            # "download.default_directory": "/dev/null",
            # "plugins.always_open_pdf_externally": False,
            "download_restrictions": 3,
        }
        self.chrome_options.add_experimental_option(
            "prefs", prefs
        )

        self.dir = Path(__file__).parent.parent / "chrome"
        self.dir.mkdir(mode=0o775, exist_ok=True)

        self.chrome_dir = self.dir / "chrome-headless-shell-linux64"
        self.chrome_bin = self.chrome_dir / "chrome-headless-shell"
        self.chromedriver_dir = self.dir / "chromedriver-linux64"
        self.chromedriver_bin = self.chromedriver_dir / "chromedriver"

        self.chrome_options.binary_location = str(self.chrome_bin.resolve())

        self.log = logging.getLogger("jimmy.cogs.screenshot")

    def clear_directories(self):
        shutil.rmtree(self.chrome_dir, ignore_errors=True)
        shutil.rmtree(self.chromedriver_dir, ignore_errors=True)
        self.chrome_dir.mkdir(mode=0o775, exist_ok=True)
        self.chromedriver_dir.mkdir(mode=0o775, exist_ok=True)

    async def download_latest_chrome(self, current: str = None, *, channel: str = "Stable"):
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            async with session.get(
                "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json",
            ) as response:
                versions = await response.json()
                self.log.debug("Got chrome versions: %r", versions)
            downloads = versions["channels"][channel]["downloads"]
            version = versions["channels"][channel]["version"]
            if version == current:
                self.log.debug(f"Chrome is up to date ({versions} == {current})")
                return

            self.log.debug("Downloading chrome...")
            chrome_zip_url = filter(lambda x: x["platform"] == "linux64", downloads["chrome-headless-shell"])
            if not chrome_zip_url:
                self.log.critical("No chrome zip url found for linux64 in %r.", downloads["chrome-headless-shell"])
                raise RuntimeError("No chrome zip url found for linux64.")
            chrome_zip_url = next(chrome_zip_url)["url"]
            self.log.debug("Chrome zip url: %s", chrome_zip_url)

            self.clear_directories()

            chrome_target = (self.chrome_dir.parent / f"chrome-download-{version}.zip")
            chromedriver_target = (self.chromedriver_dir.parent / f"chromedriver-download-{version}.zip")
            if chrome_target.exists():
                chrome_target.unlink()
            if chromedriver_target.exists():
                chromedriver_target.unlink()
            with chrome_target.open("wb+") as file:
                async with session.get(chrome_zip_url) as response:
                    async for data in response.content.iter_any():
                        self.log.debug("Read %d bytes from chrome zip.", len(data))
                        file.write(data)

            self.log.debug("Extracting chrome...")
            with zipfile.ZipFile(chrome_target) as zip_file:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    zip_file.extractall,
                    self.chrome_dir.parent
                )
            self.log.debug("Finished extracting chrome.")

            self.log.debug("Downloading chromedriver...")
            chromedriver_zip_url = filter(lambda x: x["platform"] == "linux64", downloads["chromedriver"])
            if not chromedriver_zip_url:
                self.log.critical("No chromedriver zip url found for linux64 in %r.", downloads["chromedriver"])
                raise RuntimeError("No chromedriver zip url found for linux64.")
            chromedriver_zip_url = next(chromedriver_zip_url)["url"]
            self.log.debug("Chromedriver zip url: %s", chromedriver_zip_url)

            with chromedriver_target.open("wb+") as file:
                async with session.get(chromedriver_zip_url) as response:
                    async for data in response.content.iter_any():
                        self.log.debug("Read %d bytes from chromedriver zip.", len(data))
                        file.write(data)

            self.log.debug("Extracting chromedriver...")
            with zipfile.ZipFile(chromedriver_target) as zip_file:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    zip_file.extractall,
                    self.chromedriver_dir.parent
                )
            self.log.debug("Finished extracting chromedriver.")

            self.log.debug("Making binaries executable.")
            await asyncio.get_event_loop().run_in_executor(
                None,
                self.chrome_bin.chmod,
                0o775
            )
            await asyncio.get_event_loop().run_in_executor(
                None,
                self.chromedriver_bin.chmod,
                0o775
            )
            self.log.debug("Finished making binaries executable.")

    async def get_version(self, full: bool = False) -> str:
        proc = await asyncio.create_subprocess_exec(
            str(self.chromedriver_bin),
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Error getting chromedriver version: {stderr.decode()}")
        if full:
            return stdout.decode().strip()
        return stdout.decode().strip().split(" ")[1]

    async def is_up_to_date(self, channel: str = "Stable"):
        try:
            current = await self.get_version(False)
        except (RuntimeError, FileNotFoundError):
            return False
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            async with session.get(
                "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json",
            ) as response:
                versions = await response.json()
                self.log.debug("Got chrome versions: %r", versions)
            version = versions["channels"][channel]["version"]
            if version == current:
                self.log.debug(f"Chrome is up to date ({versions} == {current})")
                return True
        return False

    @commands.command(name="update-chrome")
    async def update_chrome(self, ctx: commands.Context, channel: str = "Stable"):
        channel = channel.title()
        if await self.is_up_to_date(channel):
            await ctx.reply("Chrome is already up to date. Updating anyway.")
        async with ctx.channel.typing():
            try:
                await self.download_latest_chrome(channel)
            except RuntimeError as e:
                return await ctx.reply(f"\N{cross mark} Error downloading chrome: {e}")

        chrome_okay = self.chrome_bin.exists() and self.chrome_bin.is_file()
        chromedriver_okay = self.chromedriver_bin.exists() and self.chromedriver_bin.is_file()

        try:
            chromedriver_version = await self.get_version(True)
        except RuntimeError as e:
            chromedriver_version = str(e)

        return await ctx.reply(
            f"\N{white heavy check mark} Done.\n"
            f"CHANNEL: {channel}\n"
            f"CHROME OKAY: {chrome_okay}\n"
            f"CHROMEDRIVER OKAY: {chromedriver_okay}\n"
            f"CHROMEDRIVER VERSION: {chromedriver_version}"
        )

    def compress_png(self, input_file: io.BytesIO) -> io.BytesIO:
        img = Image.open(input_file)
        img = img.convert("RGB")
        with tempfile.NamedTemporaryFile(suffix=".webp") as file:
            quality = 100
            while quality > 0:
                if quality == 100:
                    quality_r = 99
                else:
                    quality_r = quality
                self.log.debug("Compressing image with quality %d%%", quality_r)
                img.save(file.name, "webp", quality=quality_r)
                file.seek(0)
                value = io.BytesIO(file.read())
                if len(value.getvalue()) <= 24 * 1024 * 1024:
                    self.log.debug("%d%% was sufficient.", quality_r)
                    break
                quality -= 15
            else:
                raise RuntimeError("Couldn't compress image.")
        return value

    @commands.slash_command()
    async def screenshot(
            self,
            ctx: discord.ApplicationContext,
            url: str,
            load_timeout: int = 10,
            render_timeout: int = None,
            eager: bool = None,
            resolution: str = "1920x1080"
    ):
        """Screenshots a webpage."""
        await ctx.defer()

        if eager is None:
            eager = render_timeout is None
        if render_timeout is None:
            render_timeout = 30 if eager else 10
        if not url.startswith("http"):
            url = "https://" + url
        parsed = urlparse(url)
        await ctx.respond("Initialising...")

        if not all(map(lambda x: x.exists() and x.is_file(), (self.chrome_bin, self.chromedriver_bin))):
            await ctx.edit(content="Chrome is not installed, downloading. This may take a minute.")
            await self.download_latest_chrome()
            await ctx.edit(content="Initialising...")
        elif not await self.is_up_to_date():
            await ctx.edit(content="Updating chrome. This may take a minute.")
            await self.download_latest_chrome()
            await ctx.edit(content="Initialising...")

        start_init = time.time()
        service = await asyncio.to_thread(ChromeService, str(self.chromedriver_bin))
        driver: webdriver.Chrome = await asyncio.to_thread(
            webdriver.Chrome,
            service=service,
            options=self.chrome_options
        )
        driver.set_page_load_timeout(load_timeout)
        if resolution:
            try:
                width, height = map(int, resolution.split("x"))
                driver.set_window_size(width, height)
                if height > 4320 or width > 7680:
                    return await ctx.respond("Invalid resolution. Max resolution is 7680x4320 (8K).")
            except ValueError:
                return await ctx.respond("Invalid resolution. please provide width x height, e.g. 1920x1080")
        if eager:
            driver.implicitly_wait(render_timeout)
        end_init = time.time()

        await ctx.edit(content=("Loading webpage..." if not eager else "Loading & screenshotting webpage..."))
        start_request = time.time()
        await asyncio.to_thread(driver.get, url)
        end_request = time.time()

        if not eager:
            now = discord.utils.utcnow()
            expires = now + datetime.timedelta(seconds=render_timeout)
            await ctx.edit(content=f"Rendering (expires {discord.utils.format_dt(expires, 'R')})...")
            start_wait = time.time()
            await asyncio.sleep(render_timeout)
            end_wait = time.time()
        else:
            start_wait = end_wait = 1

        await ctx.edit(content="Saving screenshot...")
        start_save = time.time()
        ss = await asyncio.to_thread(driver.get_screenshot_as_png)
        file = io.BytesIO()
        await asyncio.to_thread(file.write, ss)
        file.seek(0)
        end_save = time.time()

        if len(await asyncio.to_thread(file.getvalue)) > 24 * 1024 * 1024:
            start_compress = time.time()
            file = await asyncio.to_thread(self.compress_png, file)
            fn = "screenshot.webp"
            end_compress = time.time()
        else:
            fn = "screenshot.png"
            start_compress = end_compress = 1

        await ctx.edit(content="Cleaning up...")
        start_cleanup = time.time()
        await asyncio.to_thread(driver.quit)
        end_cleanup = time.time()

        screenshot_size_mb = round(len(await asyncio.to_thread(file.getvalue)) / 1024 / 1024, 2)

        def seconds(start: float, end: float) -> float:
            return round(end - start, 2)

        embed = discord.Embed(
            title=f"Screenshot of {parsed.hostname}",
            description=f"Init time: {seconds(start_init, end_init)}s\n"
                        f"Request time: {seconds(start_request, end_request)}s\n"
                        f"Wait time: {seconds(start_wait, end_wait)}s\n"
                        f"Save time: {seconds(start_save, end_save)}s\n"
                        f"Compress time: {seconds(start_compress, end_compress)}s\n"
                        f"Cleanup time: {seconds(start_cleanup, end_cleanup)}s\n"
                        f"Screenshot size: {screenshot_size_mb}MB\n",
            colour=discord.Colour.dark_theme(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_image(url="attachment://" + fn)
        return await ctx.edit(content=None, embed=embed, file=discord.File(file, filename=fn))


def setup(bot):
    bot.add_cog(ScreenshotCog(bot))
