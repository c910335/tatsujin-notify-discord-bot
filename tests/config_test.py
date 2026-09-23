"""Unit tests for configuration loading logic."""

import importlib
import os
import sys
import unittest
from unittest import mock

import config


class ConfigTest(unittest.TestCase):
    """Test cases for the configuration loader in config.py."""

    def setUp(self) -> None:
        """Saves a backup of os.environ."""
        self._environ_backup = dict(os.environ)

    def tearDown(self) -> None:
        """Restores os.environ and reloads config to pristine state."""
        os.environ.clear()
        os.environ.update(self._environ_backup)
        importlib.reload(config)

    def test_load_env_loads_successfully(self) -> None:
        """Verifies that config loads settings via python-dotenv load_dotenv."""

        def mock_load_dotenv():
            """Mocks the load_dotenv call to set test variables."""
            os.environ["TNDB_DISCORD_TOKEN"] = "dotenv_token"
            os.environ["TNDB_ADMIN_CHANNEL_ID"] = "987654"
            os.environ["TNDB_HEARTBEAT_JITTER_SECONDS"] = "45.5"
            os.environ["TNDB_CHECK_JITTER_SECONDS"] = "4.0"
            os.environ["TNDB_INSTAGRAM_MAX_COOLDOWN_SECONDS"] = "86400"
            os.environ["TNDB_INSTAGRAM_CHECK_INTERVAL_SECONDS"] = "900"
            return True

        with mock.patch("dotenv.load_dotenv", side_effect=mock_load_dotenv):
            with mock.patch.dict(os.environ, {}, clear=True):
                # Remove unittest to simulate non-test environment
                unittest_module = sys.modules.pop("unittest", None)
                try:
                    importlib.reload(config)
                finally:
                    if unittest_module:
                        sys.modules["unittest"] = unittest_module

                self.assertEqual(config.DISCORD_TOKEN, "dotenv_token")
                self.assertEqual(config.ADMIN_CHANNEL_ID, 987654)
                self.assertEqual(config.HEARTBEAT_JITTER_SECONDS, 45.5)
                self.assertEqual(config.CHECK_JITTER_SECONDS, 4.0)
                self.assertEqual(config.INSTAGRAM_MAX_COOLDOWN_SECONDS, 86400)
                self.assertEqual(config.INSTAGRAM_CHECK_INTERVAL_SECONDS, 900)

    def test_default_values(self) -> None:
        """Verifies default values when environment variables are not set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            importlib.reload(config)
            self.assertEqual(config.INSTAGRAM_MAX_COOLDOWN_SECONDS, 43200)
            self.assertEqual(config.INSTAGRAM_CHECK_INTERVAL_SECONDS, 1200)


if __name__ == "__main__":
    unittest.main()
