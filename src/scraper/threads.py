"""Threads scraping and HTML extraction logic."""

import json
from typing import Any

from playwright import async_api

import browser
import data
from scraper import common


def _parse_post(post_data: dict[str, Any]) -> data.PostDict | None:
    """Parses a raw post dictionary into a structured PostDict.

    Args:
        post_data: A raw post dictionary from the Threads API JSON payload.

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
    user = post_data.get("user") or {}
    username = user.get("username")
    display_name = user.get("full_name") or username
    timestamp = post_data.get("taken_at") or 0

    caption = post_data.get("caption") or {}
    text = caption.get("text", "")

    media_urls = common.extract_media(post_data)

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


def extract_threads_posts_from_html(
    html_content: str,
) -> list[data.PostDict]:
    """Extracts post information from application/json blocks in HTML.

    Args:
        html_content: The fully rendered HTML page source.

    Returns:
        A list of parsed post dictionaries sorted by publication timestamp
        descending.
    """
    json_scripts = common.extract_json_scripts(html_content)

    unique_posts = {}

    for script_content in json_scripts:
        script_content = script_content.strip()
        if not script_content:
            continue
        try:
            data_dict = json.loads(script_content)
            thread_items_lists = common.find_key_in_dict(
                data_dict, "thread_items"
            )

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
        key=lambda x: (x["timestamp"] or 0, common.get_numerical_id(x)),
        reverse=True,
    )
    return sorted_posts


async def _extract_posts_with_retry(
    page: async_api.Page,
) -> list[data.PostDict]:
    """Extracts posts from page HTML, performing a scroll retry if empty.

    Args:
        page: The Playwright page instance.

    Returns:
        A list of extracted post dictionaries.
    """
    content = await common.safe_run(page.content()) or ""
    posts = extract_threads_posts_from_html(content)

    if not posts:
        await common.safe_run(page.evaluate("window.scrollBy(0, 500)"))
        await common.safe_run(page.wait_for_timeout(1500))
        content = await common.safe_run(page.content()) or ""
        posts = extract_threads_posts_from_html(content)

    return posts or []


async def _scrape_threads_page_and_extract_posts(
    browser_inst: browser.Browser, url: str
) -> list[data.PostDict]:
    """Borrows a BrowserContext, navigates to URL, and extracts posts.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        url: The full Threads URL to navigate to.

    Returns:
        A list of parsed post dictionaries from the page.
    """
    async with common.open_page(browser_inst, url) as page:
        if page is None:
            return []

        await common.wait_for_posts(page)
        await common.dismiss_login_modal(page)
        return await _extract_posts_with_retry(page)


async def scrape_threads_user_posts(
    browser_inst: browser.Browser,
    username: str,
) -> list[data.PostDict]:
    """Scrapes posts for a Threads user profile.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        username: The username profile to scrape.

    Returns:
        A list of scraped post dictionaries belonging to the user.
    """
    url = f"https://www.threads.com/@{username}"
    posts = await _scrape_threads_page_and_extract_posts(browser_inst, url)

    # Filter posts to ensure we only return posts of the target user
    return [
        p
        for p in posts
        if p["username"] and p["username"].lower() == username.lower()
    ]


async def scrape_threads_post_by_id(
    browser_inst: browser.Browser,
    post_id: str,
) -> data.PostDict | None:
    """Scrapes a specific Threads post by its ID/code.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        post_id: The shortcode of the post (e.g. "DH_eOgcSUww").

    Returns:
        The scraped post dictionary, or None if not found.
    """
    url = f"https://www.threads.com/post/{post_id}"
    posts = await _scrape_threads_page_and_extract_posts(browser_inst, url)

    for p in posts:
        if p["code"] == post_id:
            return p
    return None
