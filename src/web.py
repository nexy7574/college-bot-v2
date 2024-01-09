import asyncio
import logging
import psutil
import time
import pydantic
from typing import Optional, Any
from conf import CONFIG

from fastapi import FastAPI, HTTPException, status

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
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)
