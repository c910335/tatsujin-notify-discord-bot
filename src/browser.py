"""Playwright browser instance proxy/wrapper."""

import json
import os
from typing import Any

from playwright import async_api

CDP_UA_OVERRIDE: dict[str, Any] = {
    "userAgent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "acceptLanguage": "en-US,en;q=0.9",
    "platform": "Win32",
    "userAgentMetadata": {
        "brands": [
            {"brand": "Not(A:Brand", "version": "99"},
            {"brand": "Google Chrome", "version": "133"},
            {"brand": "Chromium", "version": "133"},
        ],
        "fullVersionList": [
            {"brand": "Not(A:Brand", "version": "99.0.0.0"},
            {"brand": "Google Chrome", "version": "133.0.6943.127"},
            {"brand": "Chromium", "version": "133.0.6943.127"},
        ],
        "platform": "Windows",
        "platformVersion": "10.0.0",
        "architecture": "x86",
        "model": "",
        "mobile": False,
        "bitness": "64",
    },
}

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
    get: () => false,
});
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
});
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {},
};
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'PDF Viewer', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer' },
        { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer' },
    ],
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});
"""


class Browser:
    """Wraps a Playwright browser instance.

    Implements new_context, new_page, save_storage_state, and close.
    """

    def __init__(self, storage_state_path: str = "browser_state.json") -> None:
        """Initializes the browser proxy state placeholders.

        Args:
            storage_state_path: Path to the browser storage state JSON file.
        """
        self._playwright: async_api.Playwright | None = None
        self._raw_browser: async_api.Browser | None = None
        self._storage_state_path = storage_state_path

    async def start(self) -> None:
        """Starts Playwright and launches the Chromium browser."""
        if self._raw_browser is not None:
            return

        self._playwright = await async_api.async_playwright().start()
        self._raw_browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--headless=new",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1920,1080",
            ],
        )

    async def close(self) -> None:
        """Closes the browser and stops Playwright."""
        if self._raw_browser is not None:
            await self._raw_browser.close()
            self._raw_browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def save_storage_state(
        self, context: async_api.BrowserContext
    ) -> None:
        """Saves current browser storage state (cookies/origins) to disk.

        Args:
            context: The BrowserContext to extract storage state from.
        """
        try:
            await context.storage_state(path=self._storage_state_path)
        except (async_api.Error, OSError) as e:
            print(f"[Browser Notice] Failed to save storage state: {e}")

    @staticmethod
    async def apply_cdp_stealth(
        context: async_api.BrowserContext, page: async_api.Page
    ) -> None:
        """Applies CDP user-agent and client hints stealth overrides.

        Args:
            context: The BrowserContext managing the page.
            page: The Page instance to apply overrides to.
        """
        try:
            new_cdp_session = getattr(context, "new_cdp_session", None)
            if new_cdp_session is None:
                return
            cdp = await new_cdp_session(page)
            await cdp.send("Network.setUserAgentOverride", CDP_UA_OVERRIDE)
        except (async_api.Error, OSError) as e:
            print(f"[Browser Notice] Failed to apply CDP stealth: {e}")

    async def new_page(
        self, context: async_api.BrowserContext
    ) -> async_api.Page:
        """Creates a new page within a context and applies stealth overrides.

        Args:
            context: The BrowserContext in which to create the page.

        Returns:
            The configured Page instance.
        """
        page = await context.new_page()
        if getattr(context.new_page, "__name__", "") != "_stealth_new_page":
            await self.apply_cdp_stealth(context, page)
        return page

    async def new_context(self, **kwargs: Any) -> async_api.BrowserContext:
        """Creates a new BrowserContext using default or custom parameters.

        Args:
            **kwargs: Custom parameters passed to the browser context creation.

        Returns:
            A new BrowserContext instance with stealth and persisted state.
        """
        if self._raw_browser is None:
            await self.start()

        assert self._raw_browser is not None

        options: dict[str, Any] = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1920, "height": 1080},
            "locale": "en-US",
            "extra_http_headers": {
                "sec-ch-ua": (
                    '"Not(A:Brand";v="99", '
                    '"Google Chrome";v="133", '
                    '"Chromium";v="133"'
                ),
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if "storage_state" not in kwargs and os.path.isfile(
            self._storage_state_path
        ):
            try:
                with open(self._storage_state_path, "r", encoding="utf-8") as f:
                    json.load(f)
                options["storage_state"] = self._storage_state_path
            except (json.JSONDecodeError, OSError):
                pass

        options.update(kwargs)
        context = await self._raw_browser.new_context(**options)
        await context.add_init_script(STEALTH_SCRIPT)

        raw_new_page = context.new_page

        async def _stealth_new_page() -> async_api.Page:
            page = await raw_new_page()
            await self.apply_cdp_stealth(context, page)
            return page

        context.new_page = _stealth_new_page  # type: ignore[method-assign]
        return context
