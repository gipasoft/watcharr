from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock, Thread
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import SchedulerNotRunningError

from streaming_checker.core.config import Settings
from streaming_checker.services.runner import ScanRunResult, ScanRunner


@dataclass(frozen=True)
class SchedulerStatus:
    enabled: bool
    running: bool
    scan_running: bool
    scan_state: str
    current_scan_started_at: datetime | None
    interval_hours: float | None
    run_scan_on_startup: bool
    next_scan_at: datetime | None
    last_scan_at: datetime | None
    last_scan_source: str | None
    last_skip_reason: str | None
    error: str | None


@dataclass(frozen=True)
class ScanExecution:
    started: bool
    result: ScanRunResult | None = None
    error: str | None = None
    skipped_reason: str | None = None


class ScanSchedulerService:
    JOB_ID = "periodic-scan"
    STARTUP_JOB_ID = "startup-scan"

    def __init__(
        self,
        settings: Settings,
        *,
        runner_factory: Callable[[Settings], ScanRunner] = ScanRunner,
        scheduler_factory: Callable[[], BackgroundScheduler] | None = None,
        execution_callback: Callable[[ScanExecution], None] | None = None,
    ):
        self.settings = settings
        self.runner_factory = runner_factory
        self.execution_callback = execution_callback
        self.scheduler = scheduler_factory() if scheduler_factory else BackgroundScheduler(timezone=UTC)
        self._scan_lock = Lock()
        self._state_lock = Lock()
        self._last_scan_at: datetime | None = None
        self._last_scan_source: str | None = None
        self._last_skip_reason: str | None = None
        self._current_scan_started_at: datetime | None = None
        self._scan_state = "idle"
        self._error: str | None = None
        self._started = False

    def start(self):
        if self._started:
            return

        self.scheduler.add_job(
            self.run_scheduled_scan,
            "interval",
            hours=self.settings.scan_interval_hours,
            id=self.JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        if self.settings.run_scan_on_startup:
            self.scheduler.add_job(
                self.run_startup_scan,
                "date",
                run_date=datetime.now(UTC),
                id=self.STARTUP_JOB_ID,
                replace_existing=True,
                max_instances=1,
            )

        self.scheduler.start()
        self._started = True

    def shutdown(self):
        if not self._started:
            return

        try:
            self.scheduler.shutdown(wait=True)
        except SchedulerNotRunningError:
            pass
        finally:
            self._started = False

    def run_manual_scan(self) -> ScanExecution:
        return self._run_scan("manual")

    def start_manual_scan(self) -> ScanExecution:
        return self._start_scan_thread("manual")

    def run_scheduled_scan(self) -> ScanExecution:
        return self._run_scan("scheduled")

    def run_startup_scan(self) -> ScanExecution:
        return self._run_scan("startup")

    def status(self) -> SchedulerStatus:
        job = self.scheduler.get_job(self.JOB_ID) if self._started else None
        with self._state_lock:
            return SchedulerStatus(
                enabled=self._started,
                running=self.scheduler.running if self._started else False,
                scan_running=self._scan_lock.locked(),
                scan_state=self._scan_state,
                current_scan_started_at=self._current_scan_started_at,
                interval_hours=self.settings.scan_interval_hours,
                run_scan_on_startup=self.settings.run_scan_on_startup,
                next_scan_at=job.next_run_time if job else None,
                last_scan_at=self._last_scan_at,
                last_scan_source=self._last_scan_source,
                last_skip_reason=self._last_skip_reason,
                error=self._error,
            )

    def _start_scan_thread(self, source: str) -> ScanExecution:
        started_at = datetime.now(UTC)
        if not self._scan_lock.acquire(blocking=False):
            return self._skip_scan(source)

        self._mark_scan_started(source, started_at)
        Thread(target=self._run_scan_locked, args=(source,), daemon=True).start()
        return ScanExecution(started=True)

    def _run_scan(self, source: str) -> ScanExecution:
        started_at = datetime.now(UTC)
        if not self._scan_lock.acquire(blocking=False):
            return self._skip_scan(source)

        self._mark_scan_started(source, started_at)
        return self._run_scan_locked(source)

    def _run_scan_locked(self, source: str) -> ScanExecution:
        try:
            print(f"[scheduler] starting {source} scan")
            result = self.runner_factory(self.settings).run()
            with self._state_lock:
                self._last_scan_at = result.finished_at
                self._last_scan_source = source
                self._last_skip_reason = None
                self._current_scan_started_at = None
                self._scan_state = "completed"
                self._error = None
            print(f"[scheduler] completed {source} scan")
            execution = ScanExecution(started=True, result=result)
            self._notify_execution(execution)
            return execution
        except Exception as exc:
            error = str(exc)
            with self._state_lock:
                self._error = error
                self._last_scan_source = source
                self._current_scan_started_at = None
                self._scan_state = "failed"
            print(f"[scheduler] ERROR during {source} scan: {error}")
            execution = ScanExecution(started=True, error=error)
            self._notify_execution(execution)
            return execution
        finally:
            self._scan_lock.release()

    def _mark_scan_started(self, source: str, started_at: datetime):
        with self._state_lock:
            self._current_scan_started_at = started_at
            self._last_scan_source = source
            self._last_skip_reason = None
            self._scan_state = "running"
            self._error = None

    def _skip_scan(self, source: str) -> ScanExecution:
        reason = f"scan already running; skipped {source} scan"
        print(f"[scheduler] {reason}")
        with self._state_lock:
            self._last_skip_reason = reason
        execution = ScanExecution(started=False, skipped_reason=reason)
        self._notify_execution(execution)
        return execution

    def _notify_execution(self, execution: ScanExecution):
        if self.execution_callback:
            self.execution_callback(execution)
