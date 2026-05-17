from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Callable

from watcharr.clients.arr_client import ArrClient, ArrItem
from watcharr.clients.tmdb_client import TmdbClient
from watcharr.core.config import Settings
from watcharr.services.notifications import NtfyNotifier
from watcharr.services.provider_normalizer import NormalizedProvider, ProviderNormalizer
from watcharr.services.scanning import ScanningService
from watcharr.services.tagging import TaggingService
from watcharr.storage.sqlite import SQLiteStorage


@dataclass(frozen=True)
class ScanItemResult:
    kind: str
    media_type: str
    title: str
    status: str
    change_status: str = "UNCHANGED"
    providers: list[str] = field(default_factory=list)
    provider_slugs: list[str] = field(default_factory=list)
    provider_categories: list[str] = field(default_factory=list)
    original_provider_names: list[str] = field(default_factory=list)
    previous_providers: list[str] = field(default_factory=list)
    added_providers: list[str] = field(default_factory=list)
    removed_providers: list[str] = field(default_factory=list)
    providers_changed: bool = False
    notification_created: bool = False
    notification_sent: bool = False
    message: str | None = None


@dataclass(frozen=True)
class ArrScanResult:
    kind: str
    enabled: bool
    missing_count: int = 0
    items: list[ScanItemResult] = field(default_factory=list)
    message: str | None = None

    @property
    def processed_count(self) -> int:
        return sum(1 for item in self.items if item.status == "processed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for item in self.items if item.status == "skipped")

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.items if item.status == "error")

    @property
    def changed_count(self) -> int:
        return sum(1 for item in self.items if item.providers_changed)

    @property
    def notification_count(self) -> int:
        return sum(1 for item in self.items if item.notification_created)

    @property
    def notification_sent_count(self) -> int:
        return sum(1 for item in self.items if item.notification_sent)

    @property
    def provider_statistics(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            for provider in item.providers:
                counts[provider] = counts.get(provider, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def provider_category_statistics(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            for category in item.provider_categories:
                counts[category] = counts.get(category, 0) + 1
        return dict(sorted(counts.items()))


@dataclass(frozen=True)
class ScanRunResult:
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    country: str
    dry_run: bool
    offer_types: list[str]
    arr_results: list[ArrScanResult]
    scan_history_id: int | None = None

    @property
    def missing_count(self) -> int:
        return sum(result.missing_count for result in self.arr_results)

    @property
    def processed_count(self) -> int:
        return sum(result.processed_count for result in self.arr_results)

    @property
    def skipped_count(self) -> int:
        return sum(result.skipped_count for result in self.arr_results)

    @property
    def error_count(self) -> int:
        return sum(result.error_count for result in self.arr_results)

    @property
    def changed_count(self) -> int:
        return sum(result.changed_count for result in self.arr_results)

    @property
    def notification_count(self) -> int:
        return sum(result.notification_count for result in self.arr_results)

    @property
    def notification_sent_count(self) -> int:
        return sum(result.notification_sent_count for result in self.arr_results)

    @property
    def provider_statistics(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.arr_results:
            for provider, count in result.provider_statistics.items():
                counts[provider] = counts.get(provider, 0) + count
        return dict(sorted(counts.items()))

    @property
    def provider_category_statistics(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.arr_results:
            for category, count in result.provider_category_statistics.items():
                counts[category] = counts.get(category, 0) + count
        return dict(sorted(counts.items()))


class ScanRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        tmdb_factory: Callable[[str, str], TmdbClient] = TmdbClient,
        arr_client_factory: Callable[[str, str, str], ArrClient] = ArrClient,
        storage_factory: Callable[[str], SQLiteStorage] | None = SQLiteStorage,
        notifier_factory: Callable[[Settings], NtfyNotifier] | None = NtfyNotifier,
        provider_normalizer_factory: Callable[[], ProviderNormalizer] = ProviderNormalizer,
    ):
        self.settings = settings
        self.tmdb_factory = tmdb_factory
        self.arr_client_factory = arr_client_factory
        self.storage = storage_factory(settings.database_path) if storage_factory else None
        self.notifier = notifier_factory(settings) if notifier_factory else None
        self.provider_normalizer = provider_normalizer_factory()

    def run(self) -> ScanRunResult:
        started_at = datetime.now(UTC)
        start = perf_counter()
        tmdb = self.tmdb_factory(self.settings.tmdb_bearer_token, self.settings.language)
        arr_results: list[ArrScanResult] = []

        if self.settings.radarr_url and self.settings.radarr_api_key:
            arr_results.append(
                self.process_arr(
                    self.arr_client_factory(self.settings.radarr_url, self.settings.radarr_api_key, "radarr"),
                    tmdb,
                )
            )
        else:
            print("[radarr] disabled")
            arr_results.append(ArrScanResult(kind="radarr", enabled=False, message="disabled"))

        if self.settings.sonarr_url and self.settings.sonarr_api_key:
            arr_results.append(
                self.process_arr(
                    self.arr_client_factory(self.settings.sonarr_url, self.settings.sonarr_api_key, "sonarr"),
                    tmdb,
                )
            )
        else:
            print("[sonarr] disabled")
            arr_results.append(ArrScanResult(kind="sonarr", enabled=False, message="disabled"))

        finished_at = datetime.now(UTC)
        result = ScanRunResult(
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=perf_counter() - start,
            country=self.settings.country,
            dry_run=self.settings.dry_run,
            offer_types=list(self.settings.offer_types),
            arr_results=arr_results,
        )
        scan_history_id = self._record_scan_history(result)
        return replace(result, scan_history_id=scan_history_id)

    def process_arr(self, client: ArrClient, tmdb: TmdbClient) -> ArrScanResult:
        items = client.list_missing_monitored()
        print(f"[{client.kind}] missing monitored items: {len(items)}")

        scanner = ScanningService(tmdb, self.settings, self.provider_normalizer)
        tagger = TaggingService(self.settings)
        item_results: list[ScanItemResult] = []

        for item in items:
            item_results.append(self._process_item(client, scanner, tagger, item))

        return ArrScanResult(
            kind=client.kind,
            enabled=True,
            missing_count=len(items),
            items=item_results,
        )

    def _process_item(
        self,
        client: ArrClient,
        scanner: ScanningService,
        tagger: TaggingService,
        item: ArrItem,
    ) -> ScanItemResult:
        try:
            normalized_providers = scanner.normalized_providers_for_item(client.kind, item)
            if normalized_providers is None:
                return ScanItemResult(
                    kind=client.kind,
                    media_type=self._media_type(client.kind),
                    title=item.title,
                    status="skipped",
                    message="missing tmdbId/tvdbId mapping",
                )

            providers = ProviderNormalizer.canonical_names(normalized_providers)
            tagger.apply(client, item, providers)
            change = self.storage.record_availability(client.kind, item, providers) if self.storage else None
            notification_sent, notification_error = self._send_notification(client.kind, item.title, change)
            message = self._change_message(change) if change and change.changed else None
            if change and change.notification_created and self.notifier and not self.notifier.enabled:
                message = f"{message}; ntfy disabled" if message else "ntfy disabled"
            if change and change.notification_created and self.notifier and self.notifier.enabled and not notification_sent:
                detail = f"ntfy send failed: {notification_error}" if notification_error else "ntfy send failed"
                message = f"{message}; {detail}" if message else detail
            return ScanItemResult(
                kind=client.kind,
                media_type=self._media_type(client.kind),
                title=item.title,
                status="processed",
                change_status=change.status if change else "UNCHANGED",
                providers=providers,
                provider_slugs=[provider.slug for provider in normalized_providers],
                provider_categories=self._provider_categories(normalized_providers),
                original_provider_names=ProviderNormalizer.original_names(normalized_providers),
                previous_providers=change.previous_providers if change else [],
                added_providers=change.added_providers if change else [],
                removed_providers=change.removed_providers if change else [],
                providers_changed=bool(change and change.changed),
                notification_created=bool(change and change.notification_created),
                notification_sent=notification_sent,
                message=message,
            )
        except Exception as exc:
            print(f"[{client.kind}] ERROR processing {item.title}: {exc}")
            return ScanItemResult(
                kind=client.kind,
                media_type=self._media_type(client.kind),
                title=item.title,
                status="error",
                message=str(exc),
            )

    def _record_scan_history(self, result: ScanRunResult) -> int | None:
        if not self.storage:
            return None

        return self.storage.record_scan(
            started_at=result.started_at,
            finished_at=result.finished_at,
            duration_seconds=result.duration_seconds,
            country=result.country,
            dry_run=result.dry_run,
            offer_types=result.offer_types,
            missing_count=result.missing_count,
            processed_count=result.processed_count,
            skipped_count=result.skipped_count,
            error_count=result.error_count,
        )

    @staticmethod
    def _change_message(change) -> str:
        added = ", ".join(change.added_providers) if change.added_providers else "-"
        removed = ", ".join(change.removed_providers) if change.removed_providers else "-"
        message = f"providers changed; added: {added}; removed: {removed}"
        if not change.notification_created:
            message = f"{message}; notification already recorded"
        return message

    def _send_notification(self, kind: str, title: str, change) -> tuple[bool, str | None]:
        if not change or not change.notification_created or not self.notifier:
            return False, None

        try:
            sent = self.notifier.notify_provider_change(kind=kind, title=title, change=change)
            if sent and self.storage:
                self.storage.mark_notification_sent(change)
            return sent, None
        except Exception as exc:
            error = str(exc)
            if self.storage:
                self.storage.mark_notification_failed(change, error)
            print(f"[ntfy] ERROR sending notification for {title}: {error}")
            return False, error

    @staticmethod
    def _provider_categories(providers: list[NormalizedProvider]) -> list[str]:
        return sorted(provider.category for provider in providers if provider.category)

    @staticmethod
    def _media_type(kind: str) -> str:
        if kind == "radarr":
            return "movie"
        if kind == "sonarr":
            return "series"
        return kind

