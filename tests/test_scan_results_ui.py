import sys
import unittest
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from datetime import UTC, datetime

from watcharr.services.runner import ArrScanResult, ScanItemResult, ScanRunResult
from watcharr.services.scheduler import SchedulerStatus
from watcharr.web.app import (
    _change_status_badge,
    _column_selector,
    _item_matches_provider,
    _media_type_badge,
    _ntfy_test_form,
    _ntfy_test_notice,
    _provider_badge,
    _provider_filter_bar,
    _providers_display,
    _resolve_provider_filter,
    _render_page,
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
        self.assertIn("desktop-results", html)
        self.assertIn("results-table", html)
        self.assertIn("mobile-results", html)
        self.assertIn("result-card", html)
        self.assertIn("service-cell", html)
        self.assertIn("provider-cell", html)
        self.assertIn("media-type-cell", html)
        self.assertIn("message-cell", html)
        self.assertIn('data-column="service" hidden', html)
        self.assertLess(html.index("Provider"), html.index("Cambio"))

    def test_page_css_allows_long_provider_chips_to_wrap(self):
        html = _render_page(
            settings=_settings(),
            config_error=None,
            scan_error=None,
            result=_sample_result(),
            scheduler_status=None,
            active_provider=None,
        )

        self.assertIn("word-break: break-word", html)
        self.assertIn("word-break: keep-all", html)
        self.assertIn("white-space: normal", html)
        self.assertIn("white-space: nowrap", html)
        self.assertIn(".results-table th:not(:last-child)", html)
        self.assertIn("padding-right: 18px", html)
        self.assertIn(".service-cell", html)
        self.assertIn("overflow-x: hidden", html)
        self.assertIn(".providers .provider-chip", html)
        self.assertIn(".desktop-results", html)
        self.assertIn(".mobile-results", html)

    def test_column_selector_defaults_to_hiding_service(self):
        html = _column_selector()

        self.assertIn("column-selector", html)
        self.assertIn('data-column-toggle="service"', html)
        self.assertIn('data-column-toggle="providers" checked', html)
        self.assertNotIn('data-column-toggle="service" checked', html)

    def test_page_has_column_selector_script(self):
        html = _render_page(
            settings=_settings(),
            config_error=None,
            scan_error=None,
            result=_sample_result(),
            scheduler_status=None,
            active_provider=None,
        )

        self.assertIn("watcharr.results.columns", html)
        self.assertIn("data-column-toggle", html)
        self.assertIn("htmx:afterSwap", html)
        self.assertIn("Test ntfy", html)

    def test_page_has_pwa_metadata(self):
        html = _render_page(
            settings=_settings(),
            config_error=None,
            scan_error=None,
            result=_sample_result(),
            scheduler_status=None,
            active_provider=None,
        )

        self.assertIn('rel="manifest"', html)
        self.assertIn('href="/manifest.webmanifest"', html)
        self.assertIn('name="theme-color"', html)
        self.assertIn('apple-mobile-web-app-capable', html)
        self.assertIn('serviceWorker.register("/sw.js")', html)

    def test_pwa_manifest_has_install_metadata(self):
        manifest_path = Path(__file__).resolve().parents[1] / "app" / "watcharr" / "web" / "static" / "manifest.webmanifest"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["name"], "Watcharr")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/")
        self.assertTrue(any(icon["purpose"] == "maskable" for icon in manifest["icons"]))

    def test_ntfy_test_notice_renders_success_and_failure(self):
        self.assertIn("Test ntfy inviato", _ntfy_test_notice((True, "sent")))
        self.assertIn("Test ntfy fallito", _ntfy_test_notice((False, "failed")))

    def test_ntfy_test_form_requires_url_and_topic(self):
        enabled = _ntfy_test_form(_settings(ntfy_url="https://ntfy.example.com", ntfy_topic="topic"), None)
        disabled = _ntfy_test_form(_settings(ntfy_url=None, ntfy_topic="topic"), None)

        self.assertIn('hx-post="/ntfy/test"', enabled)
        self.assertNotIn("disabled", enabled)
        self.assertIn("disabled", disabled)

    def test_page_shows_scan_running_state_and_htmx_polling(self):
        started_at = datetime.now(UTC)
        html = _render_page(
            settings=None,
            config_error=None,
            scan_error=None,
            result=_sample_result(),
            scheduler_status=SchedulerStatus(
                enabled=True,
                running=True,
                scan_running=True,
                scan_state="running",
                current_scan_started_at=started_at,
                interval_hours=12.0,
                run_scan_on_startup=True,
                next_scan_at=None,
                last_scan_at=None,
                last_scan_source="manual",
                last_skip_reason=None,
                error=None,
            ),
            active_provider=None,
        )

        self.assertIn("Scansione in corso...", html)
        self.assertIn("Scansione in corso, attendere...", html)
        self.assertIn('hx-post="/scan"', html)
        self.assertIn('hx-get="/scan/status"', html)
        self.assertIn('hx-trigger="every 2s"', html)
        self.assertIn("disabled", html)

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


def _settings(**overrides):
    from watcharr.core.config import Settings

    values = {
        "radarr_url": None,
        "radarr_api_key": None,
        "sonarr_url": None,
        "sonarr_api_key": None,
        "tmdb_bearer_token": "tmdb",
        "country": "IT",
        "language": "it-IT",
        "dry_run": True,
        "remove_stale_tags": True,
        "tag_generic": True,
        "tag_providers": True,
        "generic_tag": "available-streaming",
        "tag_prefix": "streaming-",
        "provider_allowlist": [],
        "offer_types": ["flatrate"],
        "database_path": ":memory:",
        "ntfy_url": "https://ntfy.example.com",
        "ntfy_topic": "topic",
        "ntfy_token": None,
        "ntfy_username": None,
        "ntfy_password": None,
        "ntfy_priority": "default",
        "ntfy_tags": ["tv"],
        "scan_interval_hours": 12.0,
        "run_scan_on_startup": True,
    }
    values.update(overrides)
    return Settings(**values)


if __name__ == "__main__":
    unittest.main()
