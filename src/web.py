import asyncio
import datetime
import logging
import textwrap

import psutil
import time
import pydantic
from typing import Optional, Any
from conf import CONFIG
import discord
from discord.ext.commands import Paginator

from fastapi import FastAPI, HTTPException, status, WebSocketException, WebSocket, WebSocketDisconnect, Header

class BridgeResponse(pydantic.BaseModel):
    status: str
    pages: list[str]


class BridgePayload(pydantic.BaseModel):
    secret: str
    message: str
    sender: str


class MessagePayload(pydantic.BaseModel):
    class MessageAttachmentPayload(pydantic.BaseModel):
        url: str
        proxy_url: str
        filename: str
        size: int
        width: Optional[int] = None
        height: Optional[int] = None
        content_type: str
        ATTACHMENT: Optional[Any] = None

    event_type: Optional[str] = "create"
    message_id: int
    author: str
    is_automated: bool = False
    avatar: str
    content: str
    clean_content: str
    at: float
    attachments: list[MessageAttachmentPayload] = []
    reply_to: Optional["MessagePayload"] = None


app = FastAPI(
    title="JimmyAPI",
    version="2.0.0a1"
)
log = logging.getLogger("jimmy.web.api")
app.state.bot = None
app.state.bridge_lock = asyncio.Lock()
app.state.last_sender_ts = 0


@app.get("/ping")
def ping():
    """Checks the bot is online and provides some uptime information"""
    if not app.state.bot:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)
    return {
        "ping": "pong",
        "online": app.state.bot.is_ready(),
        "latency": max(round(app.state.bot.latency, 2), 0.01),
        "uptime": round(time.time() - psutil.Process().create_time()),
        "uptime.sys": time.time() - psutil.boot_time()
    }


@app.post("/bridge", status_code=201)
async def bridge_post_send_message(body: BridgePayload):
    """Sends a message FROM matrix TO discord."""
    now = datetime.datetime.now(datetime.timezone.utc)
    ts_diff = (now - app.state.last_sender_ts).total_seconds()
    if not app.state.bot:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)

    if body.secret != CONFIG["jimmy"].get("token"):
        log.warning("Authentication failure: %s was not authenticated.", body.secret)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    channel = app.state.bot.get_channel(CONFIG["server"]["channel"])
    if not channel or not channel.can_send():
        log.warning("Unable to send message: channel not found or not writable.")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)

    if len(body.message) > 4000:
        log.warning(
            "Unable to send message: message too long ({:,} characters long, 4000 max).".format(len(body.message))
        )
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    paginator = Paginator(prefix="", suffix="", max_size=1990)
    for line in body["message"].splitlines():
        try:
            paginator.add_line(line)
        except ValueError:
            paginator.add_line(textwrap.shorten(line, width=1900, placeholder="<...>"))

    if len(paginator.pages) > 1:
        msg = None
        if app.state.last_sender != body["sender"] or ts_diff >= 600:
            msg = await channel.send(f"**{body['sender']}**:")
        m = len(paginator.pages)
        for n, page in enumerate(paginator.pages, 1):
            await channel.send(
                f"[{n}/{m}]\n>>> {page}",
                allowed_mentions=discord.AllowedMentions.none(),
                reference=msg,
                silent=True,
                suppress=n != m,
            )
            app.state.last_sender = body["sender"]
    else:
        content = f"**{body['sender']}**:\n>>> {body['message']}"
        if app.state.last_sender == body["sender"] and ts_diff < 600:
            content = f">>> {body['message']}"
        await channel.send(content, allowed_mentions=discord.AllowedMentions.none(), silent=True, suppress=False)
        app.state.last_sender = body["sender"]
    app.state.last_sender_ts = now
    return {"status": "ok", "pages": len(paginator.pages)}


@app.websocket("/bridge/recv")
async def bridge_recv(ws: WebSocket, secret: str = Header(None)):
    await ws.accept()
    log.info("Websocket %s:%s accepted.", ws.client.host, ws.client.port)
    if secret != app.state.bot.http.token:
        log.warning("Closing websocket %r, invalid secret.", ws.client.host)
        raise WebSocketException(code=1008, reason="Invalid Secret")
    if app.state.ws_connected.locked():
        log.warning("Closing websocket %r, already connected." % ws)
        raise WebSocketException(code=1008, reason="Already connected.")
    queue: asyncio.Queue = app.state.bot.bridge_queue

    async with app.state.ws_connected:
        while True:
            try:
                await ws.send_json({"status": "ping"})
            except (WebSocketDisconnect, WebSocketException):
                log.info("Websocket %r disconnected.", ws)
                break

            try:
                data = await asyncio.wait_for(queue.get(), timeout=5)
            except asyncio.TimeoutError:
                continue

            try:
                await ws.send_json(data)
                log.debug("Sent data %r to websocket %r.", data, ws)
            except (WebSocketDisconnect, WebSocketException):
                log.info("Websocket %r disconnected." % ws)
                break
            finally:
                queue.task_done()
