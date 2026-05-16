import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from streaming_checker.core.config import Settings
from streaming_checker.web.app import _configuration_summary


class WebConfigurationSummaryTest(unittest.TestCase):
    def test_summary_omits_secrets_and_sanitizes_urls(self):
        settings = Settings(
            radarr_url="http://user:password@radarr.local:7878/api?token=secret",
            radarr_api_key="radarr-secret",
            sonarr_url="http://sonarr.local:8989",
            sonarr_api_key="sonarr-secret",
            tmdb_bearer_token="tmdb-secret",
            country="IT",
            language="it-IT",
            dry_run=True,
            remove_stale_tags=True,
            tag_generic=True,
            tag_providers=True,
            generic_tag="available-streaming",
            tag_prefix="streaming-",
            provider_allowlist=["Netflix"],
            offer_types=["flatrate"],
            database_path="data/test.sqlite",
        )

        summary = _configuration_summary(settings)
        summary_text = repr(summary)

        self.assertEqual(summary["radarr_url"], "http://radarr.local:7878/api")
        self.assertTrue(summary["radarr_api_key_configured"])
        self.assertTrue(summary["tmdb_bearer_token_configured"])
        self.assertNotIn("radarr-secret", summary_text)
        self.assertNotIn("sonarr-secret", summary_text)
        self.assertNotIn("tmdb-secret", summary_text)
        self.assertNotIn("password", summary_text)


if __name__ == "__main__":
    unittest.main()

