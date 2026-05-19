import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from watcharr.services.provider_normalizer import ProviderNormalizer
from watcharr.services.runner import ArrScanResult, ScanItemResult, ScanRunResult
from watcharr.services.scanning import filter_normalized_providers
from datetime import UTC, datetime


class ProviderNormalizerTest(unittest.TestCase):
    def test_normalizes_known_aliases(self):
        normalizer = ProviderNormalizer()

        self.assertEqual(normalizer.canonical_name("Amazon Prime Video with Ads"), "Amazon Prime Video")
        self.assertEqual(normalizer.canonical_name("Prime Video"), "Amazon Prime Video")
        self.assertEqual(normalizer.canonical_name("Apple TV Amazon Channel"), "Apple TV+")
        self.assertEqual(normalizer.canonical_name("Paramount+ Amazon Channel"), "Paramount+")
        self.assertEqual(normalizer.canonical_name("Paramount Plus Apple TV Channel"), "Paramount+")
        self.assertEqual(normalizer.canonical_name("Crunchyroll Amazon Channel"), "Crunchyroll")

    def test_deduplicates_by_canonical_name_and_keeps_originals(self):
        providers = ProviderNormalizer().normalize_many(
            ["Prime Video", "Amazon Prime Video with Ads", "Netflix"]
        )

        self.assertEqual([provider.canonical_name for provider in providers], ["Amazon Prime Video", "Netflix"])
        self.assertEqual(providers[0].slug, "amazon-prime-video")
        self.assertEqual(providers[0].category, "subscription")
        self.assertEqual(
            providers[0].original_names,
            ["Prime Video", "Amazon Prime Video with Ads"],
        )

    def test_filter_normalized_providers_matches_allowlist_aliases(self):
        normalizer = ProviderNormalizer()
        providers = normalizer.normalize_many(["Amazon Prime Video with Ads", "Netflix"])

        filtered = filter_normalized_providers(providers, ["Prime Video"], normalizer)

        self.assertEqual([provider.canonical_name for provider in filtered], ["Amazon Prime Video"])

    def test_scan_result_provider_statistics_use_canonical_names(self):
        now = datetime.now(UTC)
        result = ScanRunResult(
            started_at=now,
            finished_at=now,
            duration_seconds=0.1,
            country="IT",
            dry_run=True,
            offer_types=["flatrate"],
            arr_results=[
                ArrScanResult(
                    kind="radarr",
                    enabled=True,
                    missing_count=2,
                    items=[
                        ScanItemResult(
                            kind="radarr",
                            media_type="movie",
                            title="One",
                            status="processed",
                            providers=["Amazon Prime Video"],
                            provider_categories=["subscription"],
                        ),
                        ScanItemResult(
                            kind="radarr",
                            media_type="movie",
                            title="Two",
                            status="processed",
                            providers=["Amazon Prime Video", "Netflix"],
                            provider_categories=["subscription"],
                        ),
                    ],
                )
            ],
        )

        self.assertEqual(result.provider_statistics, {"Amazon Prime Video": 2, "Netflix": 1})
        self.assertEqual(result.provider_category_statistics, {"subscription": 2})


if __name__ == "__main__":
    unittest.main()
