"""Order streamed ACP notifications before publishing prompt completion."""

from __future__ import annotations

from typing import Any

from acp.task import DefaultMessageDispatcher


class OrderedNativeDispatcher(DefaultMessageDispatcher):
    async def _dispatch_notification(self, message: dict[str, Any]) -> None:
        # ACP responses resolve directly on the receive loop. Awaiting this
        # queue before completion prevents late tokens from leaking into the
        # next graph round. Permission requests remain independently pending.
        await self._notification_runner(message)
