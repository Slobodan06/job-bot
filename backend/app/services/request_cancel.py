"""Stop expensive AI work as soon as the browser abandons the request.

Starlette keeps running a handler after the client disconnects, so a user who
clicks Stop would still pay for every remaining LLM call. `run_until_disconnect`
runs the work as a task and cancels it (closing any in-flight OpenAI request)
the moment the client goes away.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

T = TypeVar("T")

_POLL_SECONDS = 0.5
# nginx's convention for "client closed request"; nobody is left to read it.
CLIENT_CLOSED_REQUEST = 499


async def run_until_disconnect(request: Request, work: Coroutine[Any, Any, T]) -> T:
    task = asyncio.ensure_future(work)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=_POLL_SECONDS)
            if done:
                return task.result()
            if await request.is_disconnected():
                logger.info("Client disconnected from %s; cancelling generation", request.url.path)
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                raise HTTPException(status_code=CLIENT_CLOSED_REQUEST, detail="Generation stopped.")
    finally:
        if not task.done():
            task.cancel()
