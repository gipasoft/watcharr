import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from datetime import UTC, datetime

from streaming_checker.services.runner import ArrScanResult, ScanItemResult, ScanRunResult
from streaming_checker.web.app import (
    _change_status_badge,
    _item_matches_provider,
    _media_type_badge,
    _provider_badge,
    _provider_filter_bar,
    _providers_display,
    _resolve_provider_filter,
    _results_table,
    _sorted_statistics,
)


class ScanResultsUiTest(unittest.TestCase):
    def test_renders_change_status_badges(self):
        self.assertIn("change-new", _change_status_badge("NEW"))
        self.assertIn("change-updated", _change_status_badge("UPDATED"))
        self.assertIn("change-unchanged", _change_status_badge("UNCHANGED"))
        self.assertIn("change-removed", _change_status_badge("REMOVED"))

    def test_renders_media_type_badges(self):
        self.assertIn("badge-movie", _media_type_badge("movie"))
        self.assertIn("badge-series", _media_type_badge("series"))
        self.assertIn("Movie", _media_type_badge("movie"))
        self.assertIn("Series", _media_type_badge("series"))

    def test_provider_display_uses_chips_and_debug_originals(self):
        html = _providers_display(["Amazon Prime Video"], ["Prime Video"])

        self.assertIn("provider-chip", html)
        self.assertIn("provider-prime", html)
        self.assertIn("Amazon Prime Video", html)
        self.assertIn("TMDB: Prime Video", html)

    def test_provider_badge_uses_provider_color_mapping_and_fallback(self):
        self.assertIn("provider-netflix", _provider_badge("Netflix"))
        self.assertIn("provider-default", _provider_badge("Unknown Provider"))

    def test_statistics_sort_by_count_descending_then_name(self):
        self.assertEqual(
            _sorted_statistics({"Netflix": 2, "Disney+": 4, "Apple TV+": 2}),
            [("Disney+", 4), ("Apple TV+", 2), ("Netflix", 2)],
        )

    def test_results_table_uses_scroll_wrapper_and_wrapping_message_cell(self):
        result = _sample_result()

        html = _results_table(result)

        self.assertIn("table-scroll", html)
        self.assertIn("results-table", html)
        self.assertIn("message-cell", html)

    def test_provider_filter_bar_uses_counts_and_htmx_attrs(self):
        result = _sample_result()

        html = _provider_filter_bar(result, "Netflix")

        self.assertIn("All", html)
        self.assertIn("Netflix", html)
        self.assertIn("(1)", html)
        self.assertIn('hx-target="#results-section"', html)
        self.assertIn("active", html)

    def test_results_table_filters_by_canonical_provider(self):
        result = _sample_result()

        html = _results_table(result, "Netflix")

        self.assertIn("Movie", html)
        self.assertNotIn("No Providers", html)

    def test_resolve_provider_filter_preserves_canonical_name(self):
        result = _sample_result()

        self.assertEqual(_resolve_provider_filter(result, "netflix"), "Netflix")
        self.assertIsNone(_resolve_provider_filter(result, "Missing"))

    def test_item_matches_provider_uses_normalized_names(self):
        self.assertTrue(_item_matches_provider(["Netflix"], "Netflix"))
        self.assertFalse(_item_matches_provider(["Amazon Prime Video"], "Prime Video"))


def _sample_result():
    now = datetime.now(UTC)
    return ScanRunResult(
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
                        title="Movie",
                        status="processed",
                        change_status="UNCHANGED",
                        providers=["Amazon Prime Video", "Netflix"],
                        message="providers changed; added: Amazon Prime Video; removed: -",
                    ),
                    ScanItemResult(
                        kind="radarr",
                        media_type="movie",
                        title="No Providers",
                        status="processed",
                        change_status="UNCHANGED",
                        providers=[],
                    ),
                ],
            )
        ],
    )


if __name__ == "__main__":
    unittest.main()
