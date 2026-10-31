"""A task approval lease is captured before an HTTP response starts streaming."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)
class TaskResumeLease:
    manager: Any
    task_id: str
    attempt: int
    agent_id: str
    user_id: int
    thread_id: str
    pending: Any
    cancelled: bool = False
    stream_task: asyncio.Task[Any] | None = None

    @property
    def attempts(self) -> dict[str, int]:
        return {self.task_id: self.attempt}

    async def enter(self) -> None:
        # Register before the first await: cancel also stops a body waiting to
        # acquire the task lock, rather than allowing its Graph resume later.
        self.stream_task = asyncio.current_task()
        await self.manager._enter_resume(self)

    def cancel(self) -> None:
        self.cancelled = True
        if (
            self.stream_task is not None
            and self.stream_task is not asyncio.current_task()
            and not self.stream_task.done()
        ):
            self.stream_task.cancel()

    def close(self) -> None:
        self.manager._release_resume(self)
