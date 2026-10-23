"""Živé změny: oznámení otevřeným stránkám, že se data změnila.

Jeden proces má jeden ``ChangeBroker``. Zápisy v tomto procesu ho probudí
okamžitě; zápisy z jiných procesů nebo serverů (více workerů, CLI import,
notifikace) zachytí krátké dotazování na čítač ``seq`` v databázi.
Stránka si pak sama vyžádá změny od svého posledního ``seq`` (``/api/changes``
nebo proud ``/api/stream``), takže nic nepřeskočí ani po výpadku spojení.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

import anyio

log = logging.getLogger(__name__)


class ChangeBroker:
    def __init__(self, read_seq: Callable[[], int], poll_interval_s: float = 1.0):
        self._read_seq = read_seq
        self._poll_interval_s = poll_interval_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self.head = 0

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()
        try:
            self.head = await anyio.to_thread.run_sync(self._read_seq)
        except Exception:  # databáze ještě nemusí být dostupná; dotazování to zkusí znovu
            log.exception("čtení čítače změn při startu selhalo")
        self._task = asyncio.create_task(self._poll(), name="semafor-change-poll")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def notify_threadsafe(self) -> None:
        """Volá úložiště po potvrzeném zápisu (z libovolného vlákna)."""
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._wake)

    def _wake(self) -> None:
        if self._event:
            self._event.set()
            self._event = asyncio.Event()

    def ticket(self) -> asyncio.Event | None:
        """Vezme si aktuální "lístek"; změna po tomto okamžiku ho probudí."""
        return self._event

    async def wait(self, ev: asyncio.Event | None, timeout: float) -> bool:
        """Počká na změnu po vydání lístku, nebo na timeout. True = něco se změnilo."""
        if ev is None:
            await asyncio.sleep(timeout)
            return False
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval_s)
            try:
                seq = await anyio.to_thread.run_sync(self._read_seq)
            except Exception:
                log.warning("dotaz na čítač změn selhal", exc_info=True)
                continue
            if seq != self.head:
                self.head = seq
                self._wake()
