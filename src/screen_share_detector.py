"""Detect screen sharing using psutil (no subprocess)"""

import asyncio
import psutil
from typing import Callable

SHARING_APPS = {"zoom", "teams", "webex", "gotomeeting", "anydesk", "teamviewer"}


class ScreenShareDetector:

    def __init__(self):
        self.is_sharing = False

    def _check(self) -> bool:
        try:
            running = {p.name().lower().replace(".exe", "") for p in psutil.process_iter(["name"])}
            return bool(running & SHARING_APPS)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    async def monitor(self, callback: Callable, interval: int = 5):
        while True:
            current = self._check()
            if current != self.is_sharing:
                self.is_sharing = current
                await callback(current)
            await asyncio.sleep(interval)
