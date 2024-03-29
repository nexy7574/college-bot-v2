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
        self.names = CONFIG["quote_a"].get("names", {})

    @property
    def quotes_channel(self) -> discord.TextChannel | None:
        if self.quotes_channel_id:
            c = self.bot.get_channel(self.quotes_channel_id)
            if c:
                return c

    @staticmethod
    def generate_pie_chart(
            usernames: list[str],
            counts: list[int],
            no_other: bool = False
    ) -> discord.File:
        """
        Converts the given username and count tuples into a nice pretty pie chart.

        :param usernames: The usernames
        :param counts: The number of times the username appears in the chat
        :param no_other: Disables the "other" grouping
        :returns: The pie chart image
        """

        def pct(v: int):
            return f"{v:.1f}% ({round((v / 100) * sum(counts))})"

        if no_other is False:
            other = []
            # Any authors with less than 5% of the total count will be grouped into "other"
            for i, author in enumerate(usernames.copy()):
                if (c := counts[i]) / sum(counts) < 0.05:
                    other.append(c)
                    counts[i] = -1
                    usernames.remove(author)
            if other:
                usernames.append("Other")
                counts.append(sum(other))
            # And now filter out any -1% counts
            counts = [c for c in counts if c != -1]

        mapping = {}
        for i, author in enumerate(usernames):
            mapping[author] = counts[i]

        # Sort the authors by count
        new_mapping = {}
        for author, count in sorted(mapping.items(), key=lambda x: x[1], reverse=True):
            new_mapping[author] = count

        usernames = list(new_mapping.keys())
        counts = list(new_mapping.values())

        fig, ax = plt.subplots(figsize=(7, 7))
        ax.pie(
            counts,
            labels=usernames,
            autopct=pct,
            startangle=90,
            radius=1.2,
        )
        fig.subplots_adjust(left=0.1, bottom=0.1, right=0.9, top=0.9, wspace=0.3, hspace=0.4)
        fio = io.BytesIO()
        fig.savefig(fio, format='png')
        fio.seek(0)
        return discord.File(fio, filename="pie.png")

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
            ],
            merge_other: Annotated[
                bool,
                discord.Option(
                    bool,
                    name="merge_other",
                    description="Whether to merge authors with less than 5% of the total count into 'Other'.",
                    default=True
                )
            ]
    ):
        """Checks the quote quota for the quotes channel."""
        now = discord.utils.utcnow()
        oldest = now - timedelta(days=days)
        await ctx.defer()
        channel = self.quotes_channel or discord.utils.get(ctx.guild.text_channels, name="quotes")
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
                regex = r".*\s*-\s*@?([\w\s]+)"
            else:
                regex = r".+\s+-\s*@?([\w\s]+)"

            if not (m := re.match(regex, str(message.clean_content))):
                filtered_messages += 1
                continue
            name = m.group(1)
            name = name.strip().casefold()
            if name == "me":
                name = message.author.name.strip().casefold()
                if name in self.names:
                    name = self.names[name].title()
                else:
                    filtered_messages += 1
                    continue
            elif name in self.names:
                name = self.names[name].title()
            elif name.isdigit():
                filtered_messages += 1
                continue

            name = name.title()
            authors.setdefault(name, 0)
            authors[name] += 1

        if not authors:
            if total:
                return await ctx.edit(
                    content="No valid messages found in the last {!s} days. "
                            "Make sure quotes are formatted properly ending with ` - AuthorName`"
                            " (e.g. `\"This is my quote\" - Jimmy`)".format(days)
                )
            else:
                return await ctx.edit(
                    content="No messages found in the last {!s} days.".format(days)
                )

        file = await asyncio.to_thread(
            self.generate_pie_chart,
            list(authors.keys()),
            list(authors.values()),
            merge_other
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
