from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from ..config import Settings
from .utils import iso_now, trim_output


class BrowserSessionManager:
    """Owns public render passes and the opt-in authenticated Edge session."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Any | None = None
        self._authenticated_context: Any | None = None
        self._started_at: str | None = None

    @staticmethod
    def edge_running() -> bool:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return "msedge.exe" in result.stdout.lower()
        except OSError:
            return False

    async def status(self) -> dict[str, Any]:
        active = self._authenticated_context is not None
        return {
            "active": active,
            "session": "authenticated" if active else None,
            "profile": self.settings.edge_profile,
            "startedAt": self._started_at,
            "edgeRunning": self.edge_running(),
            "message": "Authenticated Edge session is active." if active else "No authenticated browser session is active.",
        }

    async def start_authenticated(self) -> dict[str, Any]:
        if self._authenticated_context is not None:
            return await self.status()
        if self.edge_running():
            return {
                "active": False,
                "blocked": True,
                "profile": self.settings.edge_profile,
                "message": "Close all Microsoft Edge windows, then start the authenticated browser session again. Vogi will not close Edge automatically.",
            }
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"active": False, "error": "Playwright is not installed. Install it to use rendered or authenticated browsing."}
        try:
            self._playwright = await async_playwright().start()
            self._authenticated_context = await self._playwright.chromium.launch_persistent_context(
                str(self.settings.edge_user_data_dir),
                channel=self.settings.edge_channel,
                headless=False,
                args=[f"--profile-directory={self.settings.edge_profile}"],
            )
            self._started_at = iso_now()
            return await self.status()
        except Exception as exc:
            await self._stop_playwright()
            return {"active": False, "error": f"Could not start authenticated Edge session: {trim_output(str(exc), 300)}"}

    async def close_authenticated(self) -> dict[str, Any]:
        if self._authenticated_context is not None:
            try:
                await self._authenticated_context.close()
            finally:
                self._authenticated_context = None
        await self._stop_playwright()
        self._started_at = None
        return {"active": False, "message": "Authenticated browser session closed."}

    async def render_public(self, url: str) -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"error": "Playwright is not installed for rendered browsing."}
        try:
            async with async_playwright() as runner:
                browser = await runner.chromium.launch(channel=self.settings.edge_channel, headless=True)
                page = await browser.new_page()
                response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(800)
                payload = await self._page_payload(page, response.status if response else None)
                await browser.close()
                return payload
        except Exception as exc:
            return {"error": f"Rendered browsing failed: {trim_output(str(exc), 300)}"}

    async def read_authenticated(self, url: str) -> dict[str, Any]:
        if self._authenticated_context is None:
            return {"error": "No authenticated browser session is active. Start one in Settings first."}
        try:
            pages = self._authenticated_context.pages
            page = pages[0] if pages else await self._authenticated_context.new_page()
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(800)
            return await self._page_payload(page, response.status if response else None)
        except Exception as exc:
            return {"error": f"Authenticated browsing failed: {trim_output(str(exc), 300)}"}

    @staticmethod
    async def _page_payload(page: Any, status_code: int | None) -> dict[str, Any]:
        title = await page.title()
        text = await page.locator("body").inner_text(timeout=10000)
        html = await page.content()
        return {"url": page.url, "title": title, "statusCode": status_code, "text": text, "html": html}

    async def _stop_playwright(self) -> None:
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
