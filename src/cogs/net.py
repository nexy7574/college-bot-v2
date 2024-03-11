import asyncio
import io
import os
import re
import time
import typing
from pathlib import Path

import discord
from discord.ext import commands
from dns import asyncresolver
from rich.console import Console
from rich.tree import Tree


class NetworkCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.slash_command()
    async def ping(self, ctx: discord.ApplicationContext, target: str = None):
        """Get the bot's latency, or the network latency to a target."""
        if target is None:
            return await ctx.respond(f"Pong! {round(self.bot.latency * 1000)}ms")
        else:
            await ctx.defer()
            process = await asyncio.create_subprocess_exec(
                "ping",
                "-c",
                "5",
                target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            paginator = commands.Paginator()

            for line in stdout.splitlines():
                paginator.add_line(line.decode("utf-8"))
            for line in stderr.splitlines():
                paginator.add_line("[STDERR] " + line.decode("utf-8"))

            for page in paginator.pages:
                await ctx.respond(page)

    @commands.slash_command()
    async def whois(self, ctx: discord.ApplicationContext, target: str):
        """Get information about a user."""

        async def run_command(with_disclaimer: bool = False):
            args = [] if with_disclaimer else ["-H"]
            process = await asyncio.create_subprocess_exec(
                "whois",
                *args,
                target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            so, se = await process.communicate()
            return so, se, process.returncode

        await ctx.defer()
        paginator = commands.Paginator()
        redacted = io.BytesIO()
        stdout, stderr, status = await run_command()

        def decide(ln: str) -> typing.Optional[bool]:
            if ln.startswith(">>> Last update"):
                return
            if "REDACTED" in ln or "Please query the WHOIS server of the owning registrar" in ln or ":" not in ln:
                return False
            else:
                return True

        for line in stdout.decode().splitlines():
            line = line.strip()
            if not line:
                continue
            a = decide(line)
            if a:
                paginator.add_line(line)
            elif a is None:
                redacted.write(b"[STDERR] " + line.encode() + b"\n")

        for line in stderr.decode().splitlines():
            line = line.strip()
            if not line:
                continue
            a = decide(line)
            if a:
                paginator.add_line("[STDERR] " + line)
            elif a is None:
                redacted.write(b"[STDERR] " + line.encode() + b"\n")

        if not paginator.pages:
            stdout, stderr, status = await run_command(with_disclaimer=True)
            if not any((stdout, stderr)):
                return await ctx.respond(f"No output was returned with status code {status}.")
            file = io.BytesIO()
            file.write(stdout)
            if stderr:
                file.write(b"\n----- STDERR -----\n")
                file.write(stderr)
            file.seek(0)
            return await ctx.respond(
                "Seemingly all output was filtered. Returning raw command output.",
                file=discord.File(file, "whois.txt")
            )

        for page in paginator.pages:
            await ctx.respond(page)
        if redacted.getvalue():
            redacted.seek(0)
            await ctx.respond(file=discord.File(redacted, "redacted.txt"))

    @commands.slash_command()
    async def dig(
        self,
        ctx: discord.ApplicationContext,
        domain: str,
        _type: discord.Option(
            str,
            name="type",
            default="A",
            choices=[
                "A",
                "AAAA",
                "ANY",
                "AXFR",
                "CNAME",
                "HINFO",
                "LOC",
                "MX",
                "NS",
                "PTR",
                "SOA",
                "SRV",
                "TXT",
            ],
        ),
    ):
        """Looks up a domain name"""
        await ctx.defer()
        if re.search(r"\s+", domain):
            return await ctx.respond("Domain name cannot contain spaces.")
        try:
            response = await asyncresolver.resolve(
                domain,
                _type.upper(),
            )
        except Exception as e:
            return await ctx.respond(f"Error: {e}")
        res = response
        tree = Tree(f"DNS Lookup for {domain}")
        for record in res:
            record_tree = tree.add(f"{record.rdtype.name} Record")
            record_tree.add(f"Name: {res.name}")
            record_tree.add(f"Value: {record.to_text()}")
        console = Console()
        with console.capture() as capture:
            console.print(tree)
        text = capture.get()
        paginator = commands.Paginator(prefix="```", suffix="```")
        for line in text.splitlines():
            paginator.add_line(line)
        paginator.add_line(empty=True)
        paginator.add_line(f"Exit code: {0}")
        paginator.add_line(f"DNS Server used: {res.nameserver}")
        for page in paginator.pages:
            await ctx.respond(page)

    @commands.slash_command()
    async def traceroute(
        self,
        ctx: discord.ApplicationContext,
        url: str,
        port: discord.Option(int, description="Port to use", default=None),
        ping_type: discord.Option(
            str,
            name="ping-type",
            description="Type of ping to use. See `traceroute --help`",
            choices=["icmp", "tcp", "udp", "udplite", "dccp", "default"],
            default="default",
        ),
        use_ip_version: discord.Option(
            str, name="ip-version", description="IP version to use.", choices=["ipv4", "ipv6"], default="ipv4"
        ),
        max_ttl: discord.Option(int, name="ttl", description="Max number of hops", default=30),
    ):
        """Performs a traceroute request."""
        await ctx.defer()
        if re.search(r"\s+", url):
            return await ctx.respond("URL cannot contain spaces.")

        args = ["sudo", "-E", "-n", "traceroute"]
        flags = {
            "ping_type": {
                "icmp": "-I",
                "tcp": "-T",
                "udp": "-U",
                "udplite": "-UL",
                "dccp": "-D",
            },
            "use_ip_version": {"ipv4": "-4", "ipv6": "-6"},
        }

        if ping_type == "default" or os.getuid() == 0:
            args = args[3:]  # removes sudo
        else:
            args.append(flags["ping_type"][ping_type])
        args.append(flags["use_ip_version"][use_ip_version])
        args.append("-m")
        args.append(str(max_ttl))
        if port is not None:
            args.append("-p")
            args.append(str(port))
        args.append(url)
        paginator = commands.Paginator()
        paginator.add_line(f"Running command: {' '.join(args[3 if args[0] == 'sudo' else 0:])}")
        paginator.add_line(empty=True)
        try:
            start = time.time_ns()
            process = await asyncio.create_subprocess_exec(
                args[0],
                *args[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.wait()
            stdout, stderr = await process.communicate()
            end = time.time_ns()
            time_taken_in_ms = (end - start) / 1000000
            if stdout:
                for line in stdout.splitlines():
                    paginator.add_line(line.decode())
            if stderr:
                for line in stderr.splitlines():
                    paginator.add_line(line.decode())
            paginator.add_line(empty=True)
            paginator.add_line(f"Exit code: {process.returncode}")
            paginator.add_line(f"Time taken: {time_taken_in_ms:,.1f}ms")
        except Exception as e:
            paginator.add_line(f"Error: {e}")
        for page in paginator.pages:
            await ctx.respond(page)
    
    @commands.slash_command(name="what-are-matthews-bank-details")
    async def matthew_bank(self, ctx: discord.ApplicationContext):
        """For the 80th time"""
        f = Path.cwd() / "assets" / "sensitive" / "matthew-bank.webp"
        if not f.exists():
            return await ctx.respond("Idk")
        else:
            await ctx.defer()
            await ctx.respond(file=discord.File(f))


def setup(bot):
    bot.add_cog(NetworkCog(bot))
