"""Common scraping and HTML/JSON extraction utilities."""

import contextlib
import inspect
import re
from collections.abc import AsyncIterator, Awaitable
from typing import Any

from playwright import async_api

import browser
import data


def find_key_in_dict(obj: Any, target_key: str) -> list[Any]:
    """Recursively finds all values associated with a target key in a dict/list.

    Args:
        obj: The nested dictionary or list structure to search.
        target_key: The key string to look for.

    Returns:
        A list of all values associated with the target key.
    """
    results = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == target_key:
                results.append(v)
            else:
                results.extend(find_key_in_dict(v, target_key))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(find_key_in_dict(item, target_key))
    return results


def extract_json_scripts(html_content: str) -> list[str]:
    """Extracts application/json script tag blocks from HTML source.

    Args:
        html_content: The rendered HTML page source.

    Returns:
        A list of script block strings found in the HTML.
    """
    return re.findall(
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
        html_content,
        re.DOTALL,
    )


def extract_single_media_url(media_obj: dict[str, Any]) -> str | None:
    """Extracts a single video or image URL from a media object.

    Prefers video over image when both are available.

    Args:
        media_obj: A raw media dictionary containing video_versions or
            image_versions2.

    Returns:
        The first video or image URL found, or None.
    """
    videos = media_obj.get("video_versions") or []
    if videos:
        return videos[0].get("url")
    img_versions = media_obj.get("image_versions2", {}).get("candidates", [])
    if img_versions:
        return img_versions[0].get("url")
    return None


def extract_media(post_data: dict[str, Any]) -> list[str]:
    """Extracts media candidate URLs (image/video) from a post.

    Checks carousel media first, then single-item media, and
    finally linked inline media as a fallback.

    Args:
        post_data: A raw post dictionary from the API payload.

    Returns:
        A list of media URLs found in the post.
    """
    media_urls = []
    # 1. Carousel media
    carousel = post_data.get("carousel_media") or []
    for c in carousel:
        url = extract_single_media_url(c)
        if url:
            media_urls.append(url)

    # 2. Single item (not carousel)
    if not carousel:
        url = extract_single_media_url(post_data)
        if url:
            media_urls.append(url)

    # 3. Linked inline media (e.g. video attachments or shared reels)
    if not media_urls:
        linked = post_data.get("text_post_app_info", {}).get(
            "linked_inline_media"
        )
        if linked:
            url = extract_single_media_url(linked)
            if url:
                media_urls.append(url)

    return media_urls


def get_numerical_id(post: data.PostDict) -> int:
    """Helper to extract numerical sequence ID prefix from a post ID.

    Args:
        post: The parsed post dictionary.

    Returns:
        The extracted numerical sequence ID as an integer, or 0 if not found.
    """
    post_id = post.get("id") or ""
    parts = post_id.split("_")
    if parts and parts[0].isdigit():
        return int(parts[0])
    return 0


async def safe_run(coro: Awaitable[Any]) -> Any:
    """Executes an awaitable, suppressing and logging Playwright API errors.

    Args:
        coro: The awaitable coroutine to execute.

    Returns:
        The result of the coroutine execution, or None if an Error occurs.
    """
    try:
        return await coro
    except async_api.Error as e:
        print(f"[Scraper Notice] Playwright operation warning: {e}")
        return None


async def wait_for_posts(page: async_api.Page) -> None:
    """Waits for post elements, triggering lazy-loading scroll if needed.

    Args:
        page: The Playwright page instance.
    """
    has_posts = await safe_run(
        page.wait_for_selector('a[href*="/post/"]', timeout=5000)
    )
    if not has_posts:
        await safe_run(page.evaluate("window.scrollBy(0, 500)"))
        has_posts = await safe_run(
            page.wait_for_selector('a[href*="/post/"]', timeout=3000)
        )
        if not has_posts:
            await safe_run(page.wait_for_timeout(1000))


async def dismiss_login_modal(page: async_api.Page) -> None:
    """Dismisses the login overlay modal if present.

    Args:
        page: The Playwright page instance.
    """
    await safe_run(page.keyboard.press("Escape"))
    await safe_run(page.wait_for_timeout(500))


@contextlib.asynccontextmanager
async def open_page(
    browser_inst: browser.Browser, url: str
) -> AsyncIterator[async_api.Page | None]:
    """Borrows a context, creates a page, and navigates to the given URL.

    Args:
        browser_inst: The shared Browser instance.
        url: The destination URL to navigate to.

    Yields:
        The loaded Page instance, or None if navigation failed.
    """
    async with await browser_inst.new_context() as context:
        page = await context.new_page()
        try:
            nav_res = await safe_run(
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            )
            if nav_res is None:
                yield None
            else:
                yield page
        finally:
            try:
                save_fn = getattr(browser_inst, "save_storage_state", None)
                if save_fn is not None:
                    res = save_fn(context)
                    if inspect.isawaitable(res):
                        await res
            except Exception:  # pylint: disable=broad-except
                pass
            await safe_run(page.close())
