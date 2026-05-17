import sys
import unittest
from pathlib import Path
from threading import Event
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from streaming_checker.core.config import Settings
from streaming_checker.services.runner import ScanRunResult
from streaming_checker.services.scheduler import ScanSchedulerService
from datetime import UTC, datetime


def make_settings(**overrides):
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
        "ntfy_url": None,
        "ntfy_topic": None,
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


class FakeRunner:
    def __init__(self, settings):
        self.settings = settings

    def run(self):
        now = datetime.now(UTC)
        return ScanRunResult(
            started_at=now,
            finished_at=now,
            duration_seconds=0.1,
            country=self.settings.country,
            dry_run=self.settings.dry_run,
            offer_types=self.settings.offer_types,
            arr_results=[],
        )


class SchedulerServiceTest(unittest.TestCase):
    def test_manual_scan_runs_through_lock_and_callback(self):
        executions = []
        service = ScanSchedulerService(
            make_settings(),
            runner_factory=FakeRunner,
            scheduler_factory=None,
            execution_callback=executions.append,
        )

        execution = service.run_manual_scan()
        status = service.status()

        self.assertTrue(execution.started)
        self.assertIsNotNone(execution.result)
        self.assertEqual(len(executions), 1)
        self.assertFalse(status.scan_running)
        self.assertEqual(status.scan_state, "completed")
        self.assertIsNone(status.current_scan_started_at)
        self.assertEqual(status.last_scan_source, "manual")
        self.assertIsNotNone(status.last_scan_at)

    def test_start_manual_scan_reports_running_state_until_background_scan_finishes(self):
        started = Event()
        release = Event()

        class SlowRunner(FakeRunner):
            def run(self):
                started.set()
                release.wait(timeout=2)
                return super().run()

        service = ScanSchedulerService(make_settings(), runner_factory=SlowRunner)

        execution = service.start_manual_scan()
        self.assertTrue(execution.started)
        self.assertTrue(started.wait(timeout=1))

        status = service.status()
        self.assertTrue(status.scan_running)
        self.assertEqual(status.scan_state, "running")
        self.assertIsNotNone(status.current_scan_started_at)

        skipped = service.start_manual_scan()
        self.assertFalse(skipped.started)
        self.assertEqual(skipped.skipped_reason, "scan already running; skipped manual scan")

        release.set()
        for _ in range(20):
            if not service.status().scan_running:
                break
            sleep(0.05)

        status = service.status()
        self.assertFalse(status.scan_running)
        self.assertEqual(status.scan_state, "completed")

    def test_failed_scan_sets_failed_state(self):
        class FailingRunner(FakeRunner):
            def run(self):
                raise RuntimeError("boom")

        service = ScanSchedulerService(make_settings(), runner_factory=FailingRunner)

        execution = service.run_manual_scan()
        status = service.status()

        self.assertTrue(execution.started)
        self.assertEqual(execution.error, "boom")
        self.assertEqual(status.scan_state, "failed")
        self.assertEqual(status.error, "boom")

    def test_overlapping_scan_is_skipped(self):
        service = ScanSchedulerService(make_settings(), runner_factory=FakeRunner)
        service._scan_lock.acquire()
        try:
            execution = service.run_manual_scan()
        finally:
            service._scan_lock.release()

        self.assertFalse(execution.started)
        self.assertEqual(execution.skipped_reason, "scan already running; skipped manual scan")
        self.assertEqual(service.status().last_skip_reason, execution.skipped_reason)


if __name__ == "__main__":
    unittest.main()
