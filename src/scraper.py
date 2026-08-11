"""Scraping utility for public Threads profiles using Playwright."""

import json
import re
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


def _extract_single_media_url(media_obj: dict[str, Any]) -> str | None:
    """Extracts a single video or image URL from a media object.

    Prefers video over image when both are available.

    Args:
        media_obj: A raw media dictionary from the Threads
            API containing video_versions or image_versions2.

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


def _extract_media(post_data: dict[str, Any]) -> list[str]:
    """Extracts media candidate URLs (image/video) from a post.

    Checks carousel media first, then single-item media, and
    finally linked inline media as a fallback.

    Args:
        post_data: A raw post dictionary from the Threads API.

    Returns:
        A list of media URLs found in the post.
    """
    media_urls = []
    # 1. Carousel media
    carousel = post_data.get("carousel_media") or []
    for c in carousel:
        url = _extract_single_media_url(c)
        if url:
            media_urls.append(url)

    # 2. Single item (not carousel)
    if not carousel:
        url = _extract_single_media_url(post_data)
        if url:
            media_urls.append(url)

    # 3. Linked inline media (e.g. video attachments or shared reels)
    if not media_urls:
        linked = post_data.get("text_post_app_info", {}).get(
            "linked_inline_media"
        )
        if linked:
            url = _extract_single_media_url(linked)
            if url:
                media_urls.append(url)

    return media_urls


def _parse_post(post_data: dict[str, Any]) -> data.PostDict | None:
    """Parses a raw post dictionary into a structured PostDict.

    Args:
        post_data: A raw post dictionary from the Threads
            API JSON payload.

    Returns:
        A PostDict with extracted fields, or None if the
        input is invalid or missing a post ID.
    """
    if not isinstance(post_data, dict):
        return None
    post_id = post_data.get("id")
    if not post_id:
        return None

    code = post_data.get("code")
    user = post_data.get("user", {})
    username = user.get("username")
    display_name = user.get("full_name") or username
    timestamp = post_data.get("taken_at")

    caption = post_data.get("caption") or {}
    text = caption.get("text", "")

    media_urls = _extract_media(post_data)

    return {
        "id": post_id,
        "code": code,
        "username": username,
        "display_name": display_name,
        "text": text,
        "timestamp": timestamp,
        "url": (
            f"https://www.threads.com/@{username}/post/{code}"
            if username and code
            else None
        ),
        "media_urls": media_urls,
    }


def _get_numerical_id(post: data.PostDict) -> int:
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


def extract_posts_from_html(html_content: str) -> list[data.PostDict]:
    """Extracts post information from application/json blocks in HTML.

    Args:
        html_content: The fully rendered HTML page source.

    Returns:
        A list of parsed post dictionaries sorted by publication timestamp
        descending.
    """
    json_scripts = re.findall(
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
        html_content,
        re.DOTALL,
    )

    unique_posts = {}

    for script_content in json_scripts:
        script_content = script_content.strip()
        if not script_content:
            continue
        try:
            data_dict = json.loads(script_content)
            thread_items_lists = find_key_in_dict(data_dict, "thread_items")

            for items_list in thread_items_lists:
                if not isinstance(items_list, list):
                    continue
                for item in items_list:
                    if not isinstance(item, dict) or "post" not in item:
                        continue
                    parsed = _parse_post(item["post"])
                    if parsed:
                        unique_posts[parsed["id"]] = parsed
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            # Ignore parsing errors from unexpected API payload structures.
            pass

    sorted_posts = sorted(
        unique_posts.values(),
        key=lambda x: (x["timestamp"] or 0, _get_numerical_id(x)),
        reverse=True,
    )
    return sorted_posts


async def _safe_run(coro: Any) -> Any:
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


async def _wait_for_posts(page: async_api.Page) -> None:
    """Waits for post elements, triggering lazy-loading scroll if needed.

    Args:
        page: The Playwright page instance.
    """
    has_posts = await _safe_run(
        page.wait_for_selector('a[href*="/post/"]', timeout=5000)
    )
    if not has_posts:
        await _safe_run(page.evaluate("window.scrollBy(0, 500)"))
        has_posts = await _safe_run(
            page.wait_for_selector('a[href*="/post/"]', timeout=3000)
        )
        if not has_posts:
            await _safe_run(page.wait_for_timeout(1000))


async def _dismiss_login_modal(page: async_api.Page) -> None:
    """Dismisses the Threads login overlay modal if present.

    Args:
        page: The Playwright page instance.
    """
    await _safe_run(page.keyboard.press("Escape"))
    await _safe_run(page.wait_for_timeout(500))


async def _extract_posts_with_retry(
    page: async_api.Page,
) -> list[data.PostDict]:
    """Extracts posts from page HTML, performing a scroll retry if empty.

    Args:
        page: The Playwright page instance.

    Returns:
        A list of extracted post dictionaries.
    """
    content = await _safe_run(page.content()) or ""
    posts = extract_posts_from_html(content)

    if not posts:
        await _safe_run(page.evaluate("window.scrollBy(0, 500)"))
        await _safe_run(page.wait_for_timeout(1500))
        content = await _safe_run(page.content()) or ""
        posts = extract_posts_from_html(content)

    return posts or []


async def _scrape_page_and_extract_posts(
    browser_inst: browser.Browser, url: str
) -> list[data.PostDict]:
    """Borrows a BrowserContext, navigates to URL, and extracts posts.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        url: The full Threads URL to navigate to.

    Returns:
        A list of parsed post dictionaries from the page.
    """
    async with await browser_inst.new_context() as context:
        page = await context.new_page()
        try:
            nav_res = await _safe_run(
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            )
            if nav_res is None:
                return []

            await _wait_for_posts(page)
            await _dismiss_login_modal(page)
            return await _extract_posts_with_retry(page)

        finally:
            await page.close()


async def scrape_user_posts(
    browser_inst: browser.Browser, username: str
) -> list[data.PostDict]:
    """Launches Playwright Chromium and scrapes posts for a user profile.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        username: The Threads username profile to scrape.

    Returns:
        A list of scraped post dictionaries belonging to the user.
    """
    url = f"https://www.threads.com/@{username}"
    posts = await _scrape_page_and_extract_posts(browser_inst, url)

    # Filter posts to ensure we only return posts of the target user
    return [
        p
        for p in posts
        if p["username"] and p["username"].lower() == username.lower()
    ]


async def scrape_post_by_id(
    browser_inst: browser.Browser, post_id: str
) -> data.PostDict | None:
    """Launches Playwright and scrapes a specific post by its ID/code.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        post_id: The shortcode of the post (e.g. "DH_eOgcSUww").

    Returns:
        The scraped post dictionary, or None if not found.
    """
    url = f"https://www.threads.com/post/{post_id}"
    posts = await _scrape_page_and_extract_posts(browser_inst, url)

    for p in posts:
        if p["code"] == post_id:
            return p
    return None
