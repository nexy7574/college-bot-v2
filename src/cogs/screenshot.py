import asyncio
import datetime
import io
import logging
import os
import tempfile
import time
from urllib.parse import urlparse

import discord
import selenium.common
from discord.ext import commands
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService


class ScreenshotCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.log = logging.getLogger("jimmy.cogs.screenshot")

        self.chrome_options = ChromeOptions()
        self.chrome_options.add_argument("--headless")
        self.chrome_options.add_argument("--disable-extensions")
        self.chrome_options.add_argument("--incognito")
        if os.getuid() == 0:
            self.chrome_options.add_argument("--no-sandbox")
            self.log.warning("Running as root, disabling chrome sandbox.")

        prefs = {
            "download.open_pdf_in_system_reader": False,
            # "download.prompt_for_download": True,
            # "download.default_directory": "/dev/null",
            "plugins.always_open_pdf_externally": False,
            "download_restrictions": 3,
        }
        self.chrome_options.add_experimental_option(
            "prefs", prefs
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

    # noinspection PyTypeChecker
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
        self.log.debug(
            "User %s (%s) is attempting to screenshot %r with load timeout %d, render timeout %d, %s loading, and "
            "a %s resolution.",
            ctx.author,
            ctx.author.id,
            url,
            load_timeout,
            render_timeout,
            "eager" if eager else "lazy",
            resolution
        )
        parsed = urlparse(url)
        await ctx.respond("Initialising...")

        start_init = time.time()
        try:
            service = await asyncio.to_thread(ChromeService)
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
        except Exception as e:
            await ctx.respond("Failed to initialise browser: " + str(e))
            raise
        end_init = time.time()

        await ctx.edit(content=("Loading webpage..." if not eager else "Loading & screenshotting webpage..."))
        start_request = time.time()
        try:
            await asyncio.to_thread(driver.get, url)
        except selenium.common.WebDriverException as e:
            if "TimeoutException" in str(e):
                return await ctx.respond("Timed out while loading webpage.")
            else:
                return await ctx.respond("Failed to load webpage:\n```\n%s\n```" % str(e.msg))
        except Exception as e:
            await ctx.respond("Failed to get the webpage: " + str(e))
            raise
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
        await asyncio.to_thread(driver.close)
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
