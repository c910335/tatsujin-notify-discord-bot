"""Unit tests for Threads scraper and post extraction logic."""

# pylint: disable=protected-access,too-many-public-methods

import unittest
from unittest import mock

from playwright import async_api

import scraper


class ScraperTest(unittest.IsolatedAsyncioTestCase):
    """Test cases for Threads profile HTML and state structure parsing."""

    def test_find_key_in_dict(self) -> None:
        """Verifies find_key_in_dict recursion searches correctly."""
        data_dict = {
            "a": 1,
            "b": [
                {"c": 2, "target": "found1"},
                {"d": {"target": "found2"}},
            ],
            "target": "found3",
        }
        results = scraper.find_key_in_dict(data_dict, "target")
        self.assertEqual(len(results), 3)
        self.assertIn("found1", results)
        self.assertIn("found2", results)
        self.assertIn("found3", results)

    def test_extract_media_single_image(self) -> None:
        """Verifies media candidate URL extraction for single images."""
        post_data = {
            "image_versions2": {
                "candidates": [
                    {"url": "https://example.com/img1_large.jpg"},
                    {"url": "https://example.com/img1_small.jpg"},
                ]
            }
        }
        urls = scraper.extract_media(post_data)
        self.assertEqual(urls, ["https://example.com/img1_large.jpg"])

    def test_extract_media_carousel(self) -> None:
        """Verifies media candidate URL extraction for carousels."""
        post_data = {
            "carousel_media": [
                {
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://example.com/slide1.jpg"}
                        ]
                    }
                },
                {
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://example.com/slide2.jpg"}
                        ]
                    }
                },
            ]
        }
        urls = scraper.extract_media(post_data)
        self.assertEqual(
            urls,
            [
                "https://example.com/slide1.jpg",
                "https://example.com/slide2.jpg",
            ],
        )

    def test_extract_media_carousel_mixed(self) -> None:
        """Verifies media extraction for mixed carousels (image and video)."""
        post_data = {
            "carousel_media": [
                {
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://example.com/slide1.jpg"}
                        ]
                    }
                },
                {
                    "video_versions": [
                        {"url": "https://example.com/slide2.mp4"}
                    ],
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://example.com/slide2_thumbnail.jpg"}
                        ]
                    },
                },
            ]
        }
        urls = scraper.extract_media(post_data)
        self.assertEqual(
            urls,
            [
                "https://example.com/slide1.jpg",
                "https://example.com/slide2.mp4",
            ],
        )

    def test_extract_media_linked_inline_media(self) -> None:
        """Verifies media candidate URL extraction for linked inline media."""
        # 1. Linked video versions
        post_data = {
            "text_post_app_info": {
                "linked_inline_media": {
                    "video_versions": [
                        {"url": "https://example.com/linked.mp4"}
                    ],
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://example.com/linked_thumbnail.jpg"}
                        ]
                    },
                }
            }
        }
        urls = scraper.extract_media(post_data)
        self.assertEqual(urls, ["https://example.com/linked.mp4"])

        # 2. Linked image versions
        post_data_img = {
            "text_post_app_info": {
                "linked_inline_media": {
                    "image_versions2": {
                        "candidates": [
                            {"url": "https://example.com/linked.jpg"}
                        ]
                    }
                }
            }
        }
        urls_img = scraper.extract_media(post_data_img)
        self.assertEqual(urls_img, ["https://example.com/linked.jpg"])

    def test_parse_post_correctly(self) -> None:
        """Verifies parsing a raw GraphQL post into a structured PostDict."""
        raw_post = {
            "id": "333444",
            "code": "CodeABC",
            "taken_at": 1700000000,
            "user": {
                "username": "tester",
                "full_name": "Test User",
            },
            "caption": {
                "text": "Check this out!",
            },
            "video_versions": [{"url": "https://example.com/video.mp4"}],
        }
        parsed = scraper.threads._parse_post(raw_post)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], "333444")
        self.assertEqual(parsed["code"], "CodeABC")
        self.assertEqual(parsed["username"], "tester")
        self.assertEqual(parsed["display_name"], "Test User")
        self.assertEqual(parsed["text"], "Check this out!")
        self.assertEqual(parsed["timestamp"], 1700000000)
        self.assertEqual(
            parsed["url"], "https://www.threads.com/@tester/post/CodeABC"
        )
        self.assertEqual(
            parsed["media_urls"], ["https://example.com/video.mp4"]
        )

    def test_extract_threads_posts_from_html(self) -> None:
        """Verifies extracting and sorting posts from script tags in HTML."""
        mock_html = """
        <html>
            <head><title>Threads Test</title></head>
            <body>
                <script type="application/json">
                {
                    "require": [
                        [
                            ["RelayPrefetchProvider"],
                            "thread_items",
                            [],
                            {
                                "thread_items": [
                                    {
                                        "post": {
                                            "id": "post_older",
                                            "code": "OldCode",
                                            "taken_at": 1600000000,
                                            "user": {
                                                "username": "tester",
                                                "full_name": "Test User"
                                            },
                                            "caption": {"text": "First post"}
                                        }
                                    }
                                ]
                            }
                        ]
                    ]
                }
                </script>
                <script type="application/json">
                {
                    "thread_items": [
                        {
                            "post": {
                                "id": "post_newer",
                                "code": "NewCode",
                                "taken_at": 1700000000,
                                "user": {
                                    "username": "tester",
                                    "full_name": "Test User"
                                },
                                "caption": {"text": "Second post"}
                            }
                        }
                    ]
                }
                </script>
            </body>
        </html>
        """
        posts = scraper.extract_threads_posts_from_html(mock_html)
        self.assertEqual(len(posts), 2)
        # Should be sorted newer first
        self.assertEqual(posts[0]["id"], "post_newer")
        self.assertEqual(posts[1]["id"], "post_older")

    def test_extract_posts_with_identical_timestamps(self) -> None:
        """Verifies sorting by numerical ID when timestamps are identical."""
        mock_html = """
        <html>
            <body>
                <script type="application/json">
                {
                    "thread_items": [
                        {
                            "post": {
                                "id": "1000_123",
                                "code": "Code1",
                                "taken_at": 1500000000,
                                "user": {"username": "tester"},
                                "caption": {"text": "Older post in thread"}
                            }
                        },
                        {
                            "post": {
                                "id": "2000_123",
                                "code": "Code2",
                                "taken_at": 1500000000,
                                "user": {"username": "tester"},
                                "caption": {"text": "Newer post in thread"}
                            }
                        }
                    ]
                }
                </script>
            </body>
        </html>
        """
        posts = scraper.extract_threads_posts_from_html(mock_html)
        self.assertEqual(len(posts), 2)
        # Should be sorted newest first (i.e., ID 2000 first)
        self.assertEqual(posts[0]["id"], "2000_123")
        self.assertEqual(posts[1]["id"], "1000_123")

    def test_get_numerical_id(self) -> None:
        """Verifies _get_numerical_id parsing behavior."""
        self.assertEqual(scraper.get_numerical_id({"id": "12345_678"}), 12345)
        self.assertEqual(scraper.get_numerical_id({"id": "abc_678"}), 0)
        self.assertEqual(scraper.get_numerical_id({"id": ""}), 0)
        self.assertEqual(scraper.get_numerical_id({}), 0)

    async def test_scrape_user_posts_with_mock_playwright(self) -> None:
        """Verifies scrape_user_posts lifecycle using context borrowing."""
        mock_browser = mock.AsyncMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()

        mock_page.goto = mock.AsyncMock()
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock()
        mock_page.wait_for_selector = mock.AsyncMock()
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(
            return_value="<html>Mock HTML</html>"
        )
        mock_page.close = mock.AsyncMock()

        with mock.patch(
            "scraper.threads.extract_threads_posts_from_html"
        ) as mock_extract:
            mock_extract.return_value = [
                {
                    "id": "123",
                    "code": "Code123",
                    "username": "tester",
                    "display_name": "Test User",
                    "text": "Hello",
                    "timestamp": 1600000000,
                    "url": "https://www.threads.com/@tester/post/Code123",
                    "media_urls": [],
                }
            ]
            posts = await scraper.scrape_user_posts(mock_browser, "tester")
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0]["username"], "tester")
            mock_browser.new_context.assert_called_once()
            mock_page.goto.assert_called_once_with(
                "https://www.threads.com/@tester",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            mock_page.wait_for_timeout.assert_called_once_with(500)
            mock_page.close.assert_called_once()

    async def test_scrape_user_posts_handles_selector_timeout(self) -> None:
        """Verifies scrape_user_posts handles selector timeout and scroll
        retry.
        """
        mock_browser = mock.AsyncMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()

        mock_page.goto = mock.AsyncMock()
        mock_page.evaluate = mock.AsyncMock()
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock()
        mock_page.wait_for_selector = mock.AsyncMock(
            side_effect=async_api.Error("Timeout")
        )
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(
            return_value="<html>Mock HTML</html>"
        )
        mock_page.close = mock.AsyncMock()

        with mock.patch(
            "scraper.threads.extract_threads_posts_from_html", return_value=[]
        ):
            posts = await scraper.scrape_user_posts(mock_browser, "tester")
            self.assertEqual(posts, [])
            mock_browser.new_context.assert_called_once()
            self.assertEqual(mock_page.wait_for_selector.call_count, 2)
            self.assertEqual(
                mock_page.wait_for_timeout.call_args_list,
                [mock.call(1000), mock.call(500), mock.call(1500)],
            )
            mock_page.close.assert_called_once()

    async def test_scrape_user_posts_handles_navigation_error(self) -> None:
        """Verifies scrape_user_posts handles navigation error gracefully."""
        mock_browser = mock.AsyncMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()

        mock_page.goto = mock.AsyncMock(
            side_effect=async_api.Error("ERR_NAME_NOT_RESOLVED")
        )
        mock_page.evaluate = mock.AsyncMock(
            side_effect=async_api.Error("No frame")
        )
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock(
            side_effect=async_api.Error("No frame")
        )
        mock_page.wait_for_selector = mock.AsyncMock(
            side_effect=async_api.Error("No frame")
        )
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(return_value="")
        mock_page.close = mock.AsyncMock()

        with mock.patch(
            "scraper.threads.extract_threads_posts_from_html", return_value=[]
        ):
            posts = await scraper.scrape_user_posts(mock_browser, "tester")
            self.assertEqual(posts, [])
            mock_page.close.assert_called_once()

    async def test_scrape_post_by_id_success(self) -> None:
        """Verifies scrape_post_by_id successfully retrieves matched post."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)

        mock_page.goto = mock.AsyncMock()
        mock_page.evaluate = mock.AsyncMock()
        mock_page.wait_for_selector = mock.AsyncMock()
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock()
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(return_value="<html></html>")
        mock_page.close = mock.AsyncMock()

        mock_posts = [
            {"code": "other_code", "id": "1"},
            {"code": "target_code", "id": "2"},
        ]

        with mock.patch(
            "scraper.threads.extract_threads_posts_from_html",
            return_value=mock_posts,
        ):
            post = await scraper.scrape_post_by_id(mock_browser, "target_code")
            self.assertIsNotNone(post)
            self.assertEqual(post["code"], "target_code")

    async def test_scrape_post_by_id_not_found(self) -> None:
        """Verifies scrape_post_by_id returns None if no post matches."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)

        mock_page.goto = mock.AsyncMock()
        mock_page.evaluate = mock.AsyncMock()
        mock_page.wait_for_selector = mock.AsyncMock()
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock()
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(return_value="<html></html>")
        mock_page.close = mock.AsyncMock()

        with mock.patch(
            "scraper.threads.extract_threads_posts_from_html", return_value=[]
        ):
            post = await scraper.scrape_post_by_id(mock_browser, "non_existent")
            self.assertIsNone(post)

    def test_parser_defensive_checks(self) -> None:
        """Verifies defensive checks and invalid payloads handling in parser."""
        # 1. _parse_post with non-dict input
        self.assertIsNone(scraper.threads._parse_post("not a dict"))

        # 2. _parse_post with missing id
        self.assertIsNone(scraper.threads._parse_post({"code": "C123"}))

        # 2b. _parse_post with user explicitly None
        parsed_null_user = scraper.threads._parse_post(
            {"id": "p_null", "code": "C_null", "user": None}
        )
        self.assertIsNotNone(parsed_null_user)
        self.assertIsNone(parsed_null_user["username"])

        # 3. extract_threads_posts_from_html with invalid or empty JSON
        mock_html = """
        <html>
            <!-- empty script -->
            <script type="application/json">   </script>

            <!-- invalid JSON -->
            <script type="application/json">{invalid}</script>

            <!-- thread_items is not a list -->
            <script type="application/json">
            {"thread_items": "should_be_list"}
            </script>

            <!-- item in thread_items list is not a dict or missing post -->
            <script type="application/json">
            {"thread_items": ["not_a_dict", {"missing_post": true}]}
            </script>
        </html>
        """
        posts = scraper.extract_threads_posts_from_html(mock_html)
        self.assertEqual(posts, [])

    def test_decode_instagram_timestamp(self) -> None:
        """Verifies _decode_instagram_timestamp converts snowflake correctly."""
        decode_ts = scraper.instagram._decode_instagram_timestamp
        pk = 3324000000000000000
        expected = int(((pk >> 23) + 1314220021000) / 1000)
        self.assertEqual(decode_ts(pk), expected)
        self.assertEqual(decode_ts(str(pk)), expected)
        self.assertEqual(decode_ts(""), 0)
        self.assertEqual(decode_ts(None), 0)
        self.assertEqual(decode_ts("invalid"), 0)

    def test_extract_instagram_posts_from_html_success(self) -> None:
        """Verifies extract_instagram_posts_from_html extracts polaris feed."""
        pk = 3324000000000000000
        expected_ts = int(((pk >> 23) + 1314220021000) / 1000)
        mock_html = f"""
        <html>
        <script type="application/json">
        {{
          "require": [
            ["PolarisRelayPreloaderFeed", "usePreloaderFeed", [], [
              {{
                "data": {{
                  "xig_user_by_username": {{
                    "id": "12345",
                    "username": "nasa",
                    "full_name": "NASA",
                    "polaris_ordered_timeline_connection": {{
                      "edges": [
                        {{
                          "node": {{
                            "pk": "{pk}",
                            "code": "DdEo7DPG8x2",
                            "display_uri": "https://example.com/nasa.jpg",
                            "caption": {{"text": "Cosmos"}},
                            "user": {{"pk": "12345", "username": "nasa"}}
                          }}
                        }}
                      ]
                    }}
                  }}
                }}
              }}
            ]]
          ]
        }}
        </script>
        </html>
        """
        posts = scraper.extract_instagram_posts_from_html(mock_html)
        self.assertEqual(len(posts), 1)
        post = posts[0]
        self.assertEqual(post["id"], f"{pk}_12345")
        self.assertEqual(post["code"], "DdEo7DPG8x2")
        self.assertEqual(post["username"], "nasa")
        self.assertEqual(post["display_name"], "NASA")
        self.assertEqual(post["text"], "Cosmos")
        self.assertEqual(post["timestamp"], expected_ts)
        self.assertEqual(
            post["url"], "https://www.instagram.com/p/DdEo7DPG8x2/"
        )
        self.assertEqual(post["media_urls"], ["https://example.com/nasa.jpg"])

    def test_extract_instagram_posts_from_html_empty_and_defensive(
        self,
    ) -> None:
        """Verifies extract_instagram_posts_from_html handles invalid HTML."""
        # Missing or invalid JSON
        self.assertEqual(scraper.extract_instagram_posts_from_html(""), [])
        self.assertEqual(
            scraper.extract_instagram_posts_from_html(
                '<script type="application/json">{invalid}</script>'
            ),
            [],
        )
        # Invalid JSON containing xig_user_by_username
        self.assertEqual(
            scraper.extract_instagram_posts_from_html(
                '<script type="application/json">'
                '{"xig_user_by_username": {invalid}</script>'
            ),
            [],
        )
        # JSON without polaris connection
        mock_html = """
        <script type="application/json">
        {"xig_user_by_username": [{"no_timeline": true}]}
        </script>
        """
        self.assertEqual(
            scraper.extract_instagram_posts_from_html(mock_html), []
        )
        # Malformed timeline structure (non-dict edge, non-dict node,
        # missing pk)
        malformed_html = """
        <script type="application/json">
        {
            "xig_user_by_username": {
                "polaris_ordered_timeline_connection": {
                    "edges": [
                        "not_a_dict",
                        {"node": "not_a_dict"},
                        {"node": {"missing_pk_and_code": true}}
                    ]
                }
            }
        }
        </script>
        """
        self.assertEqual(
            scraper.extract_instagram_posts_from_html(malformed_html), []
        )

    def test_extract_instagram_single_post_from_html(self) -> None:
        """Verifies extract_instagram_single_post_from_html parses carousels."""
        mock_html = """
        <html>
        <script type="application/json">
        {
            "xdt_shortcode_media": {
                "code": "DdEo7DPG8x2",
                "pk": "3324000000000000000",
                "user": {
                    "username": "nasa",
                    "full_name": "NASA",
                    "pk": "12345"
                },
                "caption": {"text": "Carousel test"},
                "taken_at": 1710000000,
                "carousel_media": [
                    {
                        "image_versions2": {
                            "candidates": [
                                {"url": "https://example.com/s1.jpg"}
                            ]
                        }
                    },
                    {
                        "video_versions": [
                            {"url": "https://example.com/s2.mp4"}
                        ],
                        "image_versions2": {
                            "candidates": [
                                {"url": "https://example.com/thumb2.jpg"}
                            ]
                        }
                    }
                ]
            }
        }
        </script>
        </html>
        """
        post = scraper.extract_instagram_single_post_from_html(
            mock_html, "DdEo7DPG8x2"
        )
        self.assertIsNotNone(post)
        self.assertEqual(post["code"], "DdEo7DPG8x2")
        self.assertEqual(post["username"], "nasa")
        self.assertEqual(post["timestamp"], 1710000000)
        self.assertEqual(
            post["media_urls"],
            ["https://example.com/s1.jpg", "https://example.com/s2.mp4"],
        )

        # Fallback to snowflake timestamp and display_uri
        fallback_html = """
        <script type="application/json">
        {
            "code": "FALLBACK1",
            "pk": "3324000000000000000",
            "display_uri": "https://example.com/fallback.jpg"
        }
        </script>
        """
        fallback_post = scraper.extract_instagram_single_post_from_html(
            fallback_html, "FALLBACK1"
        )
        self.assertIsNotNone(fallback_post)
        self.assertEqual(
            fallback_post["media_urls"],
            ["https://example.com/fallback.jpg"],
        )
        self.assertGreater(fallback_post["timestamp"], 0)

        # Matching code in invalid JSON script
        self.assertIsNone(
            scraper.extract_instagram_single_post_from_html(
                '<script type="application/json">'
                '{"DdEo7DPG8x2": {invalid}</script>',
                "DdEo7DPG8x2",
            )
        )

        # Non-matching shortcode
        self.assertIsNone(
            scraper.extract_instagram_single_post_from_html(
                mock_html, "different_code"
            )
        )

    async def test_scrape_user_posts_instagram_success(self) -> None:
        """Verifies scrape_user_posts with platform='instagram'."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)

        mock_page.goto = mock.AsyncMock()
        mock_page.evaluate = mock.AsyncMock()
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock()
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(return_value="<html></html>")
        mock_page.close = mock.AsyncMock()

        mock_posts = [
            {"code": "code1", "username": "nasa", "id": "1"},
            {"code": "code2", "username": "other", "id": "2"},
        ]

        with mock.patch(
            "scraper.instagram.extract_instagram_posts_from_html",
            side_effect=[[], mock_posts],
        ):
            posts = await scraper.scrape_user_posts(
                mock_browser, "nasa", platform="instagram"
            )
            self.assertEqual(len(posts), 1)
            self.assertEqual(posts[0]["username"], "nasa")
            mock_page.close.assert_called_once()

    async def test_scrape_user_posts_instagram_nav_failure(self) -> None:
        """Verifies scrape_user_posts handles Instagram navigation failure."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)

        mock_page.goto = mock.AsyncMock(
            side_effect=async_api.Error("Network Error")
        )
        mock_page.close = mock.AsyncMock()

        posts = await scraper.scrape_user_posts(
            mock_browser, "nasa", platform="instagram"
        )
        self.assertEqual(posts, [])
        mock_page.close.assert_called_once()

    async def test_scrape_post_by_id_instagram_success(self) -> None:
        """Verifies scrape_post_by_id with platform='instagram'."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)

        mock_page.goto = mock.AsyncMock()
        mock_page.evaluate = mock.AsyncMock()
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock()
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(return_value="<html></html>")
        mock_page.close = mock.AsyncMock()

        mock_post = {"code": "DdEo7DPG8x2", "id": "1", "username": "nasa"}

        with mock.patch(
            "scraper.instagram.extract_instagram_single_post_from_html",
            return_value=mock_post,
        ):
            post = await scraper.scrape_post_by_id(
                mock_browser, "DdEo7DPG8x2", platform="instagram"
            )
            self.assertIsNotNone(post)
            self.assertEqual(post["code"], "DdEo7DPG8x2")

    async def test_scrape_post_by_id_instagram_nav_failure(self) -> None:
        """Verifies scrape_post_by_id handles navigation failure for
        Instagram.
        """
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock()
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)

        mock_page.goto = mock.AsyncMock(
            side_effect=async_api.Error("Network Error")
        )
        mock_page.close = mock.AsyncMock()

        post = await scraper.scrape_post_by_id(
            mock_browser, "DdEo7DPG8x2", platform="instagram"
        )
        self.assertIsNone(post)
        mock_page.close.assert_called_once()

    async def test_scrape_user_posts_instagram_rate_limit_url(self) -> None:
        """Verifies InstagramRateLimitError when redirected to login."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()
        mock_page.url = "https://www.instagram.com/accounts/login/?is_from_rle"

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock(return_value=None)
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_page.goto = mock.AsyncMock()
        mock_page.close = mock.AsyncMock()

        with self.assertRaises(scraper.InstagramRateLimitError):
            await scraper.scrape_user_posts(
                mock_browser, "nasa", platform="instagram"
            )

    async def test_scrape_user_posts_instagram_rate_limit_content(self) -> None:
        """Verifies InstagramRateLimitError on require_login content."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()
        mock_page.url = "https://www.instagram.com/nasa/"

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock(return_value=None)
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_page.goto = mock.AsyncMock()
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock()
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(
            return_value='{"require_login": true, "Please wait a few minutes"}'
        )
        mock_page.close = mock.AsyncMock()

        with self.assertRaises(scraper.InstagramRateLimitError):
            await scraper.scrape_user_posts(
                mock_browser, "nasa", platform="instagram"
            )

    async def test_scrape_post_by_id_instagram_rate_limit(self) -> None:
        """Verifies InstagramRateLimitError on single post login redirect."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()
        mock_page.url = "https://www.instagram.com/accounts/login/?next=/p/code"

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock(return_value=None)
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_page.goto = mock.AsyncMock()
        mock_page.close = mock.AsyncMock()

        with self.assertRaises(scraper.InstagramRateLimitError):
            await scraper.scrape_post_by_id(
                mock_browser, "DdEo7DPG8x2", platform="instagram"
            )

    async def test_scrape_post_by_id_instagram_require_login_rate_limit(
        self,
    ) -> None:
        """Verifies InstagramRateLimitError on post require_login content."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()
        mock_page.url = "https://www.instagram.com/p/DdEo7DPG8x2/"

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock(return_value=None)
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_page.goto = mock.AsyncMock()
        mock_page.keyboard = mock.MagicMock()
        mock_page.keyboard.press = mock.AsyncMock()
        mock_page.wait_for_timeout = mock.AsyncMock()
        mock_page.content = mock.AsyncMock(
            return_value='{"require_login": true, "Please wait a few minutes"}'
        )
        mock_page.close = mock.AsyncMock()

        with self.assertRaises(scraper.InstagramRateLimitError):
            await scraper.scrape_post_by_id(
                mock_browser, "DdEo7DPG8x2", platform="instagram"
            )

    async def test_open_page_save_storage_state(self) -> None:
        """Verifies open_page saves storage state and handles save errors."""
        mock_browser = mock.MagicMock()
        mock_context = mock.MagicMock()
        mock_page = mock.MagicMock()

        mock_browser.new_context = mock.AsyncMock(return_value=mock_context)
        mock_context.__aenter__ = mock.AsyncMock(return_value=mock_context)
        mock_context.__aexit__ = mock.AsyncMock(return_value=None)
        mock_context.new_page = mock.AsyncMock(return_value=mock_page)
        mock_page.goto = mock.AsyncMock()
        mock_page.close = mock.AsyncMock()

        # 1. Successful async save_storage_state
        mock_browser.save_storage_state = mock.AsyncMock()
        async with scraper.common.open_page(
            mock_browser, "https://example.com"
        ) as page:
            self.assertEqual(page, mock_page)
        mock_browser.save_storage_state.assert_called_once_with(mock_context)

        # 2. Failing save_storage_state is safely suppressed
        mock_browser.save_storage_state = mock.AsyncMock(
            side_effect=Exception("Disk Error")
        )
        async with scraper.common.open_page(
            mock_browser, "https://example.com"
        ) as page:
            self.assertEqual(page, mock_page)


if __name__ == "__main__":
    unittest.main()
