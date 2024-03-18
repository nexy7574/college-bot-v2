import asyncio
import re

import discord
import io
import matplotlib.pyplot as plt
from datetime import timedelta
from discord.ext import commands
from typing import Iterable, Annotated

from conf import CONFIG


class QuoteQuota(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.quotes_channel_id = CONFIG["quote_a"].get("channel_id")

    @property
    def quotes_channel(self) -> discord.TextChannel | None:
        if self.quotes_channel_id:
            c = self.bot.get_channel(self.quotes_channel_id)
            if c:
                return c

    @staticmethod
    def generate_pie_chart(
            usernames: Iterable[str],
            counts: Iterable[int],
    ) -> discord.File:
        """
        Converts the given username and count tuples into a nice pretty pie chart.

        :param usernames: The usernames
        :param counts: The number of times the username appears in the chat
        :returns: The pie chart image
        """
        fig, ax = plt.subplots()
        ax.pie(
            counts,
            labels=usernames,
            autopct='%1.1f%%',
        )
        ax.legend(loc="upper right")
        fig.tight_layout()
        fig.title("Quote Quota")
        fio = io.BytesIO()
        fig.savefig(fio, format='jpg')
        fio.seek(0)
        return discord.File(fio, filename="pie.jpeg")

    @commands.slash_command()
    async def quota(
            self,
            ctx: discord.ApplicationContext,
            days: Annotated[
                int,
                discord.Option(
                    int,
                    name="lookback",
                    description="How many days to look back on. Defaults to 7.",
                    default=7,
                    min_value=1,
                    max_value=365
                )
            ]
    ):
        """Checks the quote quota for the quotes channel."""
        now = discord.utils.utcnow()
        oldest = now - timedelta(days=7)
        await ctx.defer()
        channel = self.quotes_channel
        if not channel:
            return await ctx.respond(":x: Cannot find quotes channel.")

        await ctx.respond("Gathering messages, this may take a moment.")

        authors = {}
        filtered_messages = 0
        total = 0
        async for message in channel.history(
            limit=None,
            after=oldest,
            oldest_first=False
        ):
            total += 1
            if not message.content:
                filtered_messages += 1
                continue
            if message.attachments:
                regex = r".*\s*-\s*(\w+)"
            else:
                regex = r".+\s*-\s*(\w+)"

            if not (m := re.match(regex, message.content)):
                filtered_messages += 1
                continue
            name = m.group(1)
            name = name.strip().title()
            authors.setdefault(name, 0)
            authors[name] += 1

        file = await asyncio.to_thread(
            self.generate_pie_chart,
            list(authors.keys()),
            list(authors.values())
        )
        return await ctx.edit(
            content="{:,} messages (out of {:,}) were filtered (didn't follow format?)".format(
                filtered_messages,
                total
            ),
            file=file
        )


def setup(bot):
    bot.add_cog(QuoteQuota(bot))
