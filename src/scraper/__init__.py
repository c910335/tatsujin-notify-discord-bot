"""Web scraper package for Threads and Instagram."""

import browser
import data
from scraper import common, instagram, threads
from scraper.common import (
    dismiss_login_modal,
    extract_json_scripts,
    extract_media,
    extract_single_media_url,
    find_key_in_dict,
    get_numerical_id,
    open_page,
    safe_run,
    wait_for_posts,
)
from scraper.instagram import (
    InstagramRateLimitError,
    extract_instagram_posts_from_html,
    extract_instagram_single_post_from_html,
    scrape_instagram_post_by_id,
    scrape_instagram_user_posts,
)
from scraper.threads import (
    extract_threads_posts_from_html,
    scrape_threads_post_by_id,
    scrape_threads_user_posts,
)


async def scrape_user_posts(
    browser_inst: browser.Browser,
    username: str,
    platform: str | data.Platform = data.Platform.THREADS,
) -> list[data.PostDict]:
    """Launches Playwright Chromium and scrapes posts for a user profile.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        username: The username profile to scrape.
        platform: The social platform (Platform.THREADS or Platform.INSTAGRAM).

    Returns:
        A list of scraped post dictionaries belonging to the user.

    Raises:
        InstagramRateLimitError: If Instagram redirects to login / rate limits.
    """
    if platform == data.Platform.INSTAGRAM:
        return await scrape_instagram_user_posts(browser_inst, username)
    return await scrape_threads_user_posts(browser_inst, username)


async def scrape_post_by_id(
    browser_inst: browser.Browser,
    post_id: str,
    platform: str | data.Platform = data.Platform.THREADS,
) -> data.PostDict | None:
    """Launches Playwright and scrapes a specific post by its ID/code.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        post_id: The shortcode of the post (e.g. "DH_eOgcSUww").
        platform: The social platform (Platform.THREADS or Platform.INSTAGRAM).

    Returns:
        The scraped post dictionary, or None if not found.

    Raises:
        InstagramRateLimitError: If Instagram redirects to login / rate limits.
    """
    if platform == data.Platform.INSTAGRAM:
        return await scrape_instagram_post_by_id(browser_inst, post_id)
    return await scrape_threads_post_by_id(browser_inst, post_id)


__all__ = [
    "common",
    "threads",
    "instagram",
    "InstagramRateLimitError",
    "find_key_in_dict",
    "extract_json_scripts",
    "extract_single_media_url",
    "extract_media",
    "get_numerical_id",
    "safe_run",
    "wait_for_posts",
    "dismiss_login_modal",
    "open_page",
    "extract_threads_posts_from_html",
    "extract_instagram_posts_from_html",
    "extract_instagram_single_post_from_html",
    "scrape_user_posts",
    "scrape_post_by_id",
    "scrape_threads_user_posts",
    "scrape_threads_post_by_id",
    "scrape_instagram_user_posts",
    "scrape_instagram_post_by_id",
]
