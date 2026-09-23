"""Unit tests for Playwright browser proxy manager."""

# pylint: disable=protected-access

import tempfile
import unittest
from unittest import mock

from playwright import async_api

import browser


class BrowserTest(unittest.IsolatedAsyncioTestCase):
    """Test cases for the Browser manager in browser.py."""

    async def test_start_stop(self) -> None:
        """Verifies start() and close() manage playwright instances."""
        mock_playwright = mock.MagicMock()
        mock_browser = mock.MagicMock()

        mock_playwright.chromium = mock.MagicMock()
        mock_playwright.chromium.launch = mock.AsyncMock(
            return_value=mock_browser
        )
        mock_browser.close = mock.AsyncMock()
        mock_playwright.stop = mock.AsyncMock()

        async_pw_mock = mock.MagicMock()
        async_pw_mock.start = mock.AsyncMock(return_value=mock_playwright)

        mgr = browser.Browser()
        with mock.patch(
            "browser.async_api.async_playwright", return_value=async_pw_mock
        ):
            # 1. Start browser
            await mgr.start()
            self.assertIsNotNone(mgr._raw_browser)
            self.assertIsNotNone(mgr._playwright)
            mock_playwright.chromium.launch.assert_called_once()
            async_pw_mock.start.assert_called_once()

            # Starting again should be a no-op
            await mgr.start()
            self.assertEqual(mock_playwright.chromium.launch.call_count, 1)

            # 2. Stop browser
            await mgr.close()
            self.assertIsNone(mgr._raw_browser)
            self.assertIsNone(mgr._playwright)
            mock_browser.close.assert_called_once()
            mock_playwright.stop.assert_called_once()

            # Stopping again should be a no-op
            await mgr.close()
            self.assertEqual(mock_browser.close.call_count, 1)

    async def test_new_context_default(self) -> None:
        """Verifies new_context creates an isolated BrowserContext."""
        mock_playwright = mock.MagicMock()
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_context.add_init_script = mock.AsyncMock()
        mock_raw_new_page = mock.AsyncMock()
        mock_context.new_page = mock_raw_new_page

        mock_playwright.chromium = mock.MagicMock()
        mock_playwright.chromium.launch = mock.AsyncMock(
            return_value=mock_browser
        )
        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)

        async_pw_mock = mock.MagicMock()
        async_pw_mock.start = mock.AsyncMock(return_value=mock_playwright)

        mgr = browser.Browser()
        with mock.patch(
            "browser.async_api.async_playwright", return_value=async_pw_mock
        ):
            ctx = await mgr.new_context()
            self.assertEqual(ctx, mock_context)
            mock_browser.new_context.assert_called_once()
            mock_context.add_init_script.assert_called_once_with(
                browser.STEALTH_SCRIPT
            )

    async def test_new_context_with_storage_state(self) -> None:
        """Verifies storage state loading when file exists and is valid."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_context.add_init_script = mock.AsyncMock()
        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        ) as tmp:
            tmp.write('{"cookies": []}')
            tmp_path = tmp.name

        mgr = browser.Browser(storage_state_path=tmp_path)
        mgr._raw_browser = mock_browser

        await mgr.new_context()
        call_kwargs = mock_browser.new_context.call_args[1]
        self.assertEqual(call_kwargs.get("storage_state"), tmp_path)

    async def test_new_context_with_invalid_storage_state(self) -> None:
        """Verifies storage state is ignored when JSON file is invalid."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_context.add_init_script = mock.AsyncMock()
        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        ) as tmp:
            tmp.write("invalid json content")
            tmp_path = tmp.name

        mgr = browser.Browser(storage_state_path=tmp_path)
        mgr._raw_browser = mock_browser

        await mgr.new_context()
        call_kwargs = mock_browser.new_context.call_args[1]
        self.assertNotIn("storage_state", call_kwargs)

    async def test_save_storage_state(self) -> None:
        """Verifies save_storage_state writes state and handles errors."""
        mock_context = mock.MagicMock()
        mock_context.storage_state = mock.AsyncMock()

        mgr = browser.Browser(storage_state_path="/tmp/test_state.json")
        await mgr.save_storage_state(mock_context)
        mock_context.storage_state.assert_called_once_with(
            path="/tmp/test_state.json"
        )

        # Error case handled gracefully
        mock_context.storage_state = mock.AsyncMock(
            side_effect=async_api.Error("Save failed")
        )
        await mgr.save_storage_state(mock_context)

    async def test_apply_cdp_stealth_success(self) -> None:
        """Verifies apply_cdp_stealth issues Network.setUserAgentOverride."""
        mock_context = mock.MagicMock()
        mock_cdp = mock.MagicMock()
        mock_cdp.send = mock.AsyncMock()
        mock_context.new_cdp_session = mock.AsyncMock(return_value=mock_cdp)
        mock_page = mock.MagicMock()

        await browser.Browser.apply_cdp_stealth(mock_context, mock_page)

        mock_context.new_cdp_session.assert_called_once_with(mock_page)
        mock_cdp.send.assert_called_once_with(
            "Network.setUserAgentOverride", browser.CDP_UA_OVERRIDE
        )

    async def test_apply_cdp_stealth_graceful_on_error(self) -> None:
        """Verifies apply_cdp_stealth handles exceptions without crashing."""
        # 1. No new_cdp_session attribute
        bare_context = mock.MagicMock(spec=[])
        mock_page = mock.MagicMock()
        await browser.Browser.apply_cdp_stealth(bare_context, mock_page)

        # 2. async_api.Error raised by new_cdp_session
        err_context = mock.MagicMock()
        err_context.new_cdp_session = mock.AsyncMock(
            side_effect=async_api.Error("CDP error")
        )
        await browser.Browser.apply_cdp_stealth(err_context, mock_page)

    async def test_wrapped_new_page_calls_cdp(self) -> None:
        """Verifies context.new_page wrapped by new_context applies CDP."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_context.add_init_script = mock.AsyncMock()
        mock_cdp = mock.MagicMock()
        mock_cdp.send = mock.AsyncMock()
        mock_context.new_cdp_session = mock.AsyncMock(return_value=mock_cdp)

        mock_page = mock.MagicMock()
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)

        mgr = browser.Browser()
        mgr._raw_browser = mock_browser

        ctx = await mgr.new_context()
        page = await ctx.new_page()

        self.assertEqual(page, mock_page)
        mock_cdp.send.assert_called_once_with(
            "Network.setUserAgentOverride", browser.CDP_UA_OVERRIDE
        )

    async def test_browser_new_page_helper(self) -> None:
        """Verifies Browser.new_page creates a page and applies stealth."""
        mgr = browser.Browser()
        mock_page = mock.MagicMock()

        # Case 1: context.new_page already wrapped as _stealth_new_page
        mock_context_wrapped = mock.MagicMock()

        async def _stealth_new_page() -> async_api.Page:
            return mock_page

        mock_context_wrapped.new_page = _stealth_new_page
        with mock.patch.object(
            browser.Browser, "apply_cdp_stealth", new_callable=mock.AsyncMock
        ) as mock_stealth:
            res1 = await mgr.new_page(mock_context_wrapped)
            self.assertEqual(res1, mock_page)
            mock_stealth.assert_not_called()

        # Case 2: context.new_page is raw mock
        mock_context_raw = mock.MagicMock()
        mock_context_raw.new_page = mock.AsyncMock(return_value=mock_page)
        with mock.patch.object(
            browser.Browser, "apply_cdp_stealth", new_callable=mock.AsyncMock
        ) as mock_stealth:
            res2 = await mgr.new_page(mock_context_raw)
            self.assertEqual(res2, mock_page)
            mock_stealth.assert_called_once_with(mock_context_raw, mock_page)


if __name__ == "__main__":
    unittest.main()
