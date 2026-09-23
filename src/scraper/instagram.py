"""Instagram scraping and HTML extraction logic."""

import json
from typing import Any

import browser
import data
from scraper import common


class InstagramRateLimitError(Exception):
    """Raised when Instagram blocks via rate limit or login redirect."""


def _decode_instagram_timestamp(pk: int | str | None) -> int:
    """Decodes Unix timestamp in seconds from an Instagram Snowflake media PK.

    Args:
        pk: The media PK (string, int, or None).

    Returns:
        The Unix epoch timestamp in seconds, or 0 if invalid.
    """
    if not pk:
        return 0
    pk_str = str(pk)
    if pk_str.isdigit():
        ms = (int(pk_str) >> 23) + 1314220021000
        return int(ms / 1000)
    return 0


def _extract_profile_info_from_scripts(
    json_scripts: list[str], target_username: str | None
) -> tuple[str | None, str | None]:
    """Extracts display name and username from application/json blocks.

    Args:
        json_scripts: List of JSON script tag contents from the HTML page.
        target_username: Target profile username fallback.

    Returns:
        A tuple of (full_name, username) if found, otherwise None.
    """
    profile_display_name: str | None = None
    resolved_username = target_username

    for script in json_scripts:
        if "xig_user_by_username" not in script:
            continue
        try:
            data_dict = json.loads(script)
            user_matches = common.find_key_in_dict(
                data_dict, "xig_user_by_username"
            )
            for user_obj in user_matches:
                if isinstance(user_obj, dict):
                    fn = user_obj.get("full_name")
                    un = user_obj.get("username")
                    if fn and not profile_display_name:
                        profile_display_name = fn
                    if un and not resolved_username:
                        resolved_username = un
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    return profile_display_name, resolved_username


def _parse_instagram_timeline_node(
    node: dict[str, Any],
    user_obj: dict[str, Any],
    resolved_username: str | None,
    profile_display_name: str | None,
) -> data.PostDict | None:
    """Parses a single Instagram timeline node into a PostDict.

    Args:
        node: The raw timeline post node dictionary.
        user_obj: The enclosing user metadata dictionary.
        resolved_username: Fallback resolved profile username.
        profile_display_name: Fallback profile display name.

    Returns:
        A normalized PostDict instance, or None if essential fields are missing.
    """
    pk = node.get("pk")
    code = node.get("code")
    if not pk or not code:
        return None
    node_user = node.get("user") or {}
    user_pk = node_user.get("pk") or user_obj.get("pk")
    post_id = f"{pk}_{user_pk}" if user_pk else str(pk)
    username = (
        node_user.get("username")
        or user_obj.get("username")
        or resolved_username
        or ""
    )
    display_name = profile_display_name or user_obj.get("full_name") or username
    caption = node.get("caption") or {}
    text = caption.get("text") or ""
    timestamp = _decode_instagram_timestamp(pk)
    media_urls = []
    if node.get("display_uri"):
        media_urls.append(node["display_uri"])

    return {
        "id": post_id,
        "code": code,
        "url": f"https://www.instagram.com/p/{code}/",
        "username": username,
        "display_name": display_name,
        "text": text,
        "timestamp": timestamp,
        "media_urls": media_urls,
    }


def extract_instagram_posts_from_html(
    html_content: str, target_username: str | None = None
) -> list[data.PostDict]:
    """Extracts Instagram posts from application/json blocks in page HTML.

    Args:
        html_content: The rendered HTML page source.
        target_username: Optional target username to fallback to.

    Returns:
        A list of parsed PostDict objects sorted by timestamp descending.
    """
    json_scripts = common.extract_json_scripts(html_content)

    profile_name, res_user = _extract_profile_info_from_scripts(
        json_scripts, target_username
    )

    unique_posts: dict[str, data.PostDict] = {}
    for script in json_scripts:
        if "xig_user_by_username" not in script:
            continue
        try:
            data_dict = json.loads(script)
            for user_obj in common.find_key_in_dict(
                data_dict, "xig_user_by_username"
            ):
                if not isinstance(user_obj, dict):
                    continue
                timeline = (
                    user_obj.get("polaris_ordered_timeline_connection") or {}
                )
                for edge in timeline.get("edges") or []:
                    if not isinstance(edge, dict):
                        continue
                    node = edge.get("node")
                    if not isinstance(node, dict):
                        continue
                    post = _parse_instagram_timeline_node(
                        node, user_obj, res_user, profile_name
                    )
                    if post and post["id"] not in unique_posts:
                        unique_posts[post["id"]] = post
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    return sorted(
        unique_posts.values(),
        key=lambda x: (x["timestamp"] or 0, common.get_numerical_id(x)),
        reverse=True,
    )


def _find_instagram_post_candidates(
    obj: Any, target_code: str
) -> list[dict[str, Any]]:
    """Recursively searches for post objects matching target_code.

    Args:
        obj: The arbitrary parsed JSON object (dict, list, or primitive).
        target_code: The Instagram post shortcode to search for.

    Returns:
        A list of matching candidate post dictionaries.
    """
    res: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        has_post_attrs = any(
            k in obj
            for k in (
                "caption",
                "pk",
                "image_versions2",
                "carousel_media",
                "user",
            )
        )
        if obj.get("code") == target_code and has_post_attrs:
            res.append(obj)
        for v in obj.values():
            res.extend(_find_instagram_post_candidates(v, target_code))
    elif isinstance(obj, list):
        for item in obj:
            res.extend(_find_instagram_post_candidates(item, target_code))
    return res


def _score_instagram_post(p: dict[str, Any]) -> tuple[int, int, int]:
    """Scores an Instagram post candidate by completeness of data.

    Args:
        p: The candidate post dictionary.

    Returns:
        A tuple of (has_media, has_user, len(p)) for sorting priority.
    """
    has_media = (
        1
        if (
            p.get("carousel_media")
            or p.get("image_versions2")
            or p.get("video_versions")
        )
        else 0
    )
    has_user = (
        1
        if (isinstance(p.get("user"), dict) and p["user"].get("username"))
        else 0
    )
    return (has_media, has_user, len(p))


def _build_instagram_single_post(
    best: dict[str, Any], target_code: str
) -> data.PostDict:
    """Constructs a PostDict from the best matched Instagram candidate.

    Args:
        best: The highest-scoring candidate post dictionary.
        target_code: The target post shortcode fallback.

    Returns:
        A normalized PostDict instance.
    """
    pk = best.get("pk")
    code = best.get("code") or target_code
    user = best.get("user") or {}
    username = user.get("username") or ""
    display_name = user.get("full_name") or username
    caption = best.get("caption") or {}
    text = caption.get("text") or ""
    timestamp = best.get("taken_at")
    if not timestamp and pk:
        timestamp = _decode_instagram_timestamp(pk)

    media_urls = common.extract_media(best)
    if not media_urls and best.get("display_uri"):
        media_urls = [best["display_uri"]]

    user_pk = user.get("pk")
    post_id = f"{pk}_{user_pk}" if pk and user_pk else str(pk or code)

    return {
        "id": post_id,
        "code": code,
        "url": f"https://www.instagram.com/p/{code}/",
        "username": username,
        "display_name": display_name,
        "text": text,
        "timestamp": timestamp or 0,
        "media_urls": media_urls,
    }


def extract_instagram_single_post_from_html(
    html_content: str, target_code: str
) -> data.PostDict | None:
    """Extracts a specific Instagram post from page HTML.

    Args:
        html_content: The rendered HTML page source.
        target_code: The Instagram post shortcode (e.g. "DdEo7DPG8x2").

    Returns:
        The extracted PostDict, or None if not found.
    """
    json_scripts = common.extract_json_scripts(html_content)

    candidates: list[dict[str, Any]] = []
    for script in json_scripts:
        if target_code not in script:
            continue
        try:
            data_dict = json.loads(script)
            candidates.extend(
                _find_instagram_post_candidates(data_dict, target_code)
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    if not candidates:
        return None

    best = max(candidates, key=_score_instagram_post)
    return _build_instagram_single_post(best, target_code)


async def _scrape_instagram_page_and_extract_posts(
    browser_inst: browser.Browser, url: str, target_username: str | None = None
) -> list[data.PostDict]:
    """Navigates to Instagram profile URL and extracts posts.

    Args:
        browser_inst: The shared Browser instance.
        url: The Instagram profile URL.
        target_username: Optional target username.

    Returns:
        A list of extracted post dictionaries.

    Raises:
        InstagramRateLimitError: If Instagram redirects to login / rate limits.
    """
    async with common.open_page(browser_inst, url) as page:
        if page is None:
            return []

        if "is_from_rle" in page.url or "/accounts/login/" in page.url:
            raise InstagramRateLimitError(
                f"Instagram redirected to login wall / rate limit: {page.url}"
            )

        await common.dismiss_login_modal(page)
        content = await common.safe_run(page.content()) or ""

        if (
            "require_login" in content
            and "Please wait a few minutes" in content
        ):
            raise InstagramRateLimitError(
                "Instagram API returned require_login rate limit message"
            )

        posts = extract_instagram_posts_from_html(
            content, target_username=target_username
        )

        if not posts:
            await common.safe_run(page.evaluate("window.scrollBy(0, 500)"))
            await common.safe_run(page.wait_for_timeout(1000))
            content = await common.safe_run(page.content()) or ""
            posts = extract_instagram_posts_from_html(
                content, target_username=target_username
            )

        return posts or []


async def _scrape_instagram_post_page(
    browser_inst: browser.Browser, url: str, target_code: str
) -> data.PostDict | None:
    """Navigates to an Instagram post URL and extracts post details.

    Args:
        browser_inst: The shared Browser instance.
        url: The Instagram post URL.
        target_code: The post shortcode.

    Returns:
        The extracted post dictionary, or None if not found.

    Raises:
        InstagramRateLimitError: If Instagram redirects to login / rate limits.
    """
    async with common.open_page(browser_inst, url) as page:
        if page is None:
            return None

        if "is_from_rle" in page.url or "/accounts/login/" in page.url:
            raise InstagramRateLimitError(
                f"Instagram redirected to login wall / rate limit: {page.url}"
            )

        await common.dismiss_login_modal(page)
        content = await common.safe_run(page.content()) or ""
        if (
            "require_login" in content
            and "Please wait a few minutes" in content
        ):
            raise InstagramRateLimitError(
                "Instagram API returned require_login rate limit message"
            )
        return extract_instagram_single_post_from_html(content, target_code)


async def scrape_instagram_user_posts(
    browser_inst: browser.Browser,
    username: str,
) -> list[data.PostDict]:
    """Scrapes posts for an Instagram user profile.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        username: The Instagram username to scrape.

    Returns:
        A list of scraped post dictionaries belonging to the user.

    Raises:
        InstagramRateLimitError: If Instagram redirects to login / rate limits.
    """
    url = f"https://www.instagram.com/{username}/"
    posts = await _scrape_instagram_page_and_extract_posts(
        browser_inst, url, target_username=username
    )
    return [
        p
        for p in posts
        if p["username"] and p["username"].lower() == username.lower()
    ]


async def scrape_instagram_post_by_id(
    browser_inst: browser.Browser,
    post_id: str,
) -> data.PostDict | None:
    """Scrapes a specific Instagram post by its shortcode.

    Args:
        browser_inst: The shared Browser instance to borrow contexts from.
        post_id: The shortcode of the post (e.g. "DdEo7DPG8x2").

    Returns:
        The scraped post dictionary, or None if not found.

    Raises:
        InstagramRateLimitError: If Instagram redirects to login / rate limits.
    """
    url = f"https://www.instagram.com/p/{post_id}/"
    return await _scrape_instagram_post_page(
        browser_inst, url, target_code=post_id
    )
