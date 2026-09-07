import asyncio
import json
import logging
import time
from typing import Optional, Any

import aiohttp

logger = logging.getLogger("discord-webhook")

class DiscordWebhookError(Exception):
    pass

class WebhookManager:
    def __init__(self, webhook_url: str, timeout: int = 10):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self._session

    async def send(self, embed: dict) -> dict:
        """Send a new webhook message with ?wait=true. Returns message data including id."""
        session = await self._get_session()
        url = f"{self.webhook_url}?wait=true"
        payload = {"embeds": [embed]}
        async with session.post(url, json=payload) as resp:
            if resp.status == 429:
                retry_after = float(resp.headers.get("Retry-After", 5))
                logger.warning("Webhook rate limited, retrying after %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                return await self.send(embed)
            if resp.status != 200:
                text = await resp.text()
                raise DiscordWebhookError(f"Send failed: {resp.status} - {text}")
            data = await resp.json()
            return data

    async def edit(self, message_id: int, embed: dict) -> bool:
        """Edit an existing webhook message. Returns True if success, False if 404 (message gone)."""
        session = await self._get_session()
        url = f"{self.webhook_url}/messages/{message_id}"
        payload = {"embeds": [embed]}
        async with session.patch(url, json=payload) as resp:
            if resp.status == 429:
                retry_after = float(resp.headers.get("Retry-After", 5))
                logger.warning("Webhook edit rate limited, retrying after %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                return await self.edit(message_id, embed)
            if resp.status == 404:
                logger.warning("Webhook message %s not found, will re-send", message_id)
                return False
            if resp.status != 200:
                text = await resp.text()
                raise DiscordWebhookError(f"Edit failed: {resp.status} - {text}")
            return True

    async def delete(self, message_id: int) -> bool:
        """Delete a webhook message. Returns True if success, False if 404 (already gone)."""
        session = await self._get_session()
        url = f"{self.webhook_url}/messages/{message_id}"
        async with session.delete(url) as resp:
            if resp.status == 429:
                retry_after = float(resp.headers.get("Retry-After", 5))
                logger.warning("Webhook delete rate limited, retrying after %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                return await self.delete(message_id)
            if resp.status == 404:
                logger.warning("Webhook message %s already deleted", message_id)
                return False
            if resp.status not in (200, 204):
                text = await resp.text()
                raise DiscordWebhookError(f"Delete failed: {resp.status} - {text}")
            return True

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None