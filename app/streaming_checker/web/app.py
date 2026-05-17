from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from html import escape
from threading import Lock
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from streaming_checker.core.config import Settings, load_settings
from streaming_checker.core.provider_mappings import PROVIDER_BADGE_COLORS
from streaming_checker.services.runner import ScanRunResult
from streaming_checker.services.scheduler import ScanExecution, ScanSchedulerService, SchedulerStatus
from streaming_checker.storage import initialize_storage_from_environment

app = FastAPI(title="streaming-checker")

_state_lock = Lock()
_last_result: ScanRunResult | None = None
_last_error: str | None = None
_scheduler_service: ScanSchedulerService | None = None


@app.on_event("startup")
def initialize_services():
    global _last_error, _scheduler_service

    try:
        initialize_storage_from_environment()
        settings = load_settings()
        _scheduler_service = ScanSchedulerService(settings, execution_callback=_record_scan_execution)
        _scheduler_service.start()
    except Exception as exc:
        _last_error = str(exc)


@app.on_event("shutdown")
def shutdown_services():
    if _scheduler_service:
        _scheduler_service.shutdown()


def _load_settings_for_page() -> tuple[Settings | None, str | None]:
    try:
        return load_settings(), None
    except Exception as exc:
        return None, str(exc)


def _configuration_summary(settings: Settings | None) -> dict[str, str | bool | list[str]]:
    if settings is None:
        return {}

    return {
        "country": settings.country,
        "language": settings.language,
        "dry_run": settings.dry_run,
        "remove_stale_tags": settings.remove_stale_tags,
        "tag_generic": settings.tag_generic,
        "tag_providers": settings.tag_providers,
        "generic_tag": settings.generic_tag,
        "tag_prefix": settings.tag_prefix,
        "provider_allowlist": settings.provider_allowlist,
        "offer_types": settings.offer_types,
        "database_path": settings.database_path,
        "scan_interval_hours": settings.scan_interval_hours,
        "run_scan_on_startup": settings.run_scan_on_startup,
        "ntfy_enabled": bool(settings.ntfy_url and settings.ntfy_topic),
        "ntfy_url": _safe_url(settings.ntfy_url),
        "ntfy_topic": settings.ntfy_topic or "",
        "ntfy_token_configured": bool(settings.ntfy_token),
        "ntfy_basic_auth_configured": bool(settings.ntfy_username and settings.ntfy_password),
        "ntfy_priority": settings.ntfy_priority,
        "ntfy_tags": settings.ntfy_tags,
        "radarr_enabled": bool(settings.radarr_url and settings.radarr_api_key),
        "radarr_url": _safe_url(settings.radarr_url),
        "radarr_api_key_configured": bool(settings.radarr_api_key),
        "sonarr_enabled": bool(settings.sonarr_url and settings.sonarr_api_key),
        "sonarr_url": _safe_url(settings.sonarr_url),
        "sonarr_api_key_configured": bool(settings.sonarr_api_key),
        "tmdb_bearer_token_configured": bool(settings.tmdb_bearer_token),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request, provider: str | None = None):
    settings, config_error = _load_settings_for_page()

    with _state_lock:
        result = _last_result
        scan_error = _last_error
    scheduler_status = _scheduler_status()

    active_provider = _resolve_provider_filter(result, provider)
    results_section = _results_section(result, active_provider)

    if request.headers.get("HX-Request"):
        return HTMLResponse(results_section)

    return HTMLResponse(
        _render_page(
            settings=settings,
            config_error=config_error,
            scan_error=scan_error,
            result=result,
            scheduler_status=scheduler_status,
            active_provider=active_provider,
        )
    )


@app.post("/scan")
def trigger_scan(request: Request, provider: str | None = None):
    global _last_error

    service = _ensure_scheduler_service()
    if service is None:
        with _state_lock:
            _last_error = "scheduler unavailable"
        if request.headers.get("HX-Request"):
            return HTMLResponse(_dashboard_content_for_provider(provider))
        return RedirectResponse("/", status_code=303)

    execution = service.start_manual_scan()
    if execution.started:
        with _state_lock:
            _last_error = None

    if request.headers.get("HX-Request"):
        return HTMLResponse(_dashboard_content_for_provider(provider))

    return RedirectResponse("/", status_code=303)


@app.get("/scan/status", response_class=HTMLResponse)
def scan_status(provider: str | None = None):
    return HTMLResponse(_dashboard_content_for_provider(provider))


def _ensure_scheduler_service() -> ScanSchedulerService | None:
    global _last_error, _scheduler_service

    if _scheduler_service:
        return _scheduler_service

    try:
        settings = load_settings()
        _scheduler_service = ScanSchedulerService(settings, execution_callback=_record_scan_execution)
        _scheduler_service.start()
        return _scheduler_service
    except Exception as exc:
        _last_error = str(exc)
        return None


def _scheduler_status() -> SchedulerStatus | None:
    if not _scheduler_service:
        return None
    return _scheduler_service.status()


def _dashboard_content_for_provider(provider: str | None) -> str:
    settings, config_error = _load_settings_for_page()
    with _state_lock:
        result = _last_result
        scan_error = _last_error
    scheduler_status = _scheduler_status()
    active_provider = _resolve_provider_filter(result, provider)
    return _dashboard_content(
        settings=settings,
        config_error=config_error,
        scan_error=scan_error,
        result=result,
        scheduler_status=scheduler_status,
        active_provider=active_provider,
    )


def _record_scan_execution(execution: ScanExecution):
    global _last_error, _last_result

    with _state_lock:
        if execution.result:
            _last_result = execution.result
            _last_error = None
        elif execution.skipped_reason:
            _last_error = execution.skipped_reason
        elif execution.error:
            _last_error = execution.error


def _safe_url(value: str | None) -> str:
    if not value:
        return ""

    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value.split("?", 1)[0].split("#", 1)[0]

    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"

    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _render_page(
    *,
    settings: Settings | None,
    config_error: str | None,
    scan_error: str | None,
    result: ScanRunResult | None,
    scheduler_status: SchedulerStatus | None,
    active_provider: str | None,
) -> str:
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>streaming-checker</title>
  <script src="https://unpkg.com/htmx.org@2.0.4" defer></script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #1f2937;
      --muted: #64748b;
      --accent: #0f766e;
      --accent-strong: #0b5f59;
      --danger: #b42318;
      --warning: #a15c07;
      --ok: #0f766e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      overflow-x: hidden;
    }}
    main {{
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0 48px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: center;
      margin-bottom: 24px;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 28px; line-height: 1.2; }}
    h2 {{ font-size: 18px; margin-bottom: 14px; }}
    h3 {{ font-size: 15px; margin-bottom: 10px; }}
    .subtle {{ color: var(--muted); margin-top: 6px; }}
    .actions {{ display: flex; gap: 12px; align-items: center; }}
    button {{
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      padding: 10px 16px;
      cursor: pointer;
    }}
    button .spinner {{ display: none; }}
    button.is-loading {{
      align-items: center;
      display: inline-flex;
      gap: 8px;
    }}
    button.is-loading .spinner {{
      animation: spin 800ms linear infinite;
      border: 2px solid rgba(255, 255, 255, 0.45);
      border-top-color: white;
      border-radius: 999px;
      display: inline-block;
      height: 14px;
      width: 14px;
    }}
    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}
    button:hover {{ background: var(--accent-strong); }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
      padding: 18px;
    }}
    .metric .value {{ display: block; font-size: 30px; font-weight: 800; }}
    .metric .label {{ color: var(--muted); font-size: 13px; }}
    .scheduler-card {{
      margin-bottom: 18px;
    }}
    .scheduler-strip {{
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      align-items: center;
    }}
    .scheduler-item {{
      min-width: 0;
    }}
    .scheduler-label {{
      color: var(--muted);
      display: block;
      font-size: 11px;
      font-weight: 700;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}
    .scheduler-value {{
      display: block;
      font-size: 13px;
      font-weight: 700;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .filter-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
    }}
    .filter-bar a {{
      text-decoration: none;
    }}
    .filter-chip {{ transition: filter 120ms ease; }}
    .filter-chip:hover {{
      filter: brightness(0.97);
    }}
    .filter-chip.active {{
      box-shadow: 0 0 0 2px var(--accent);
    }}
    .filter-count {{
      font-weight: 800;
      margin-left: 4px;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(320px, 0.8fr);
      gap: 18px;
      align-items: start;
    }}
    .alert {{
      border: 1px solid #f1b8b1;
      background: #fff4f2;
      color: var(--danger);
      padding: 12px 14px;
      border-radius: 8px;
      margin-bottom: 18px;
    }}
    .scan-banner {{
      border: 1px solid #99f6e4;
      background: #ecfdf5;
      color: var(--accent-strong);
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 12px 14px;
      border-radius: 8px;
      margin-bottom: 18px;
    }}
    .scan-banner strong {{
      display: block;
      font-size: 14px;
    }}
    .scan-banner span {{
      color: var(--muted);
      display: block;
      font-size: 12px;
      margin-top: 2px;
    }}
    .empty {{
      color: var(--muted);
      padding: 18px 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .table-scroll {{
      max-width: 100%;
      overflow-x: hidden;
      padding-bottom: 2px;
    }}
    .results-table {{
      table-layout: fixed;
    }}
    .results-table th:nth-child(1), .results-table td:nth-child(1) {{ width: 9%; }}
    .results-table th:nth-child(2), .results-table td:nth-child(2) {{ width: 9%; }}
    .results-table th:nth-child(3), .results-table td:nth-child(3) {{ width: 24%; }}
    .results-table th:nth-child(4), .results-table td:nth-child(4) {{ width: 12%; }}
    .results-table th:nth-child(5), .results-table td:nth-child(5) {{ width: 12%; }}
    .results-table th:nth-child(6), .results-table td:nth-child(6) {{ width: 22%; }}
    .results-table th:nth-child(7), .results-table td:nth-child(7) {{ width: 12%; }}
    .results-table th, .results-table td {{
      min-width: 0;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    th, td {{
      text-align: left;
      padding: 12px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    code {{
      background: #eef2f7;
      border-radius: 4px;
      padding: 2px 5px;
      font-size: 13px;
    }}
    .status {{
      display: inline-block;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      line-height: 1;
      padding: 4px 8px;
      white-space: nowrap;
    }}
    .results-table .badge,
    .results-table .status {{
      max-width: 100%;
      overflow-wrap: anywhere;
      white-space: normal;
      word-break: break-word;
    }}
    .badge-movie {{ background: #e0f2fe; color: #075985; }}
    .badge-series {{ background: #f3e8ff; color: #6b21a8; }}
    .change-new {{ background: #dcfce7; color: #166534; }}
    .change-updated {{ background: #dbeafe; color: #1d4ed8; }}
    .change-unchanged {{ background: #e5e7eb; color: #374151; }}
    .change-removed {{ background: #fee2e2; color: #b91c1c; }}
    .processed {{ background: #dff7ee; color: var(--ok); }}
    .skipped {{ background: #fff0d8; color: var(--warning); }}
    .error {{ background: #ffe2df; color: var(--danger); }}
    .providers {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      max-width: 100%;
      min-width: 0;
    }}
    .provider-chip {{
      background: #eef2f7;
      border: 1px solid var(--line);
      border-radius: 999px;
      display: inline-block;
      font-size: 13px;
      font-weight: 700;
      line-height: 1.2;
      max-width: 100%;
      overflow-wrap: anywhere;
      padding: 4px 8px;
      white-space: normal;
      word-break: break-word;
    }}
    .providers .provider-chip {{
      flex: 0 1 auto;
      min-width: 0;
    }}
    .filter-chip {{
      white-space: nowrap;
    }}
    .provider-netflix {{ background: #fee2e2; border-color: #fecaca; color: #b91c1c; }}
    .provider-disney {{ background: #dbeafe; border-color: #bfdbfe; color: #1d4ed8; }}
    .provider-prime {{ background: #e0f2fe; border-color: #bae6fd; color: #0369a1; }}
    .provider-apple {{ background: #e5e7eb; border-color: #d1d5db; color: #111827; }}
    .provider-paramount {{ background: #dbeafe; border-color: #bfdbfe; color: #1e40af; }}
    .provider-raiplay {{ background: #dcfce7; border-color: #bbf7d0; color: #166534; }}
    .provider-crunchyroll {{ background: #ffedd5; border-color: #fed7aa; color: #c2410c; }}
    .provider-default {{ background: #eef2f7; border-color: var(--line); color: var(--text); }}
    .message-cell, .title-cell {{ overflow-wrap: anywhere; }}
    .mobile-results {{
      display: none;
    }}
    .result-card {{
      border-top: 1px solid var(--line);
      display: grid;
      gap: 10px;
      padding: 14px 0;
      min-width: 0;
    }}
    .result-card:first-child {{
      border-top: 0;
      padding-top: 0;
    }}
    .result-card:last-child {{
      padding-bottom: 0;
    }}
    .result-card-header {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
      min-width: 0;
    }}
    .result-card-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      min-width: 0;
    }}
    .result-service {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .result-title {{
      font-size: 15px;
      font-weight: 800;
      line-height: 1.3;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .result-card .providers {{
      margin-top: 0;
    }}
    .result-card .debug {{
      font-size: 11px;
      line-height: 1.35;
      overflow: visible;
      overflow-wrap: anywhere;
      text-overflow: clip;
      white-space: normal;
      word-break: break-word;
    }}
    .stats-table td:last-child {{
      font-weight: 800;
      text-align: right;
    }}
    .stats-table td {{
      padding: 9px 8px;
    }}
    .config-list {{
      display: grid;
      grid-template-columns: minmax(120px, 0.9fr) minmax(0, 1.1fr);
      gap: 10px 14px;
      font-size: 14px;
    }}
    .config-list dt {{ color: var(--muted); }}
    .config-list dd {{ margin: 0; overflow-wrap: anywhere; }}
    .debug {{
      color: var(--muted);
      display: block;
      font-size: 12px;
      margin-top: 4px;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    @media (max-width: 820px) {{
      header, .layout {{ grid-template-columns: 1fr; display: grid; }}
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .scheduler-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .actions {{ justify-content: start; }}
      .desktop-results {{ display: none; }}
      .mobile-results {{ display: grid; gap: 0; }}
    }}
    @media (max-width: 520px) {{
      main {{ width: min(100% - 20px, 1120px); padding-top: 20px; }}
      .grid {{ grid-template-columns: 1fr; }}
      .scheduler-strip {{ grid-template-columns: 1fr; }}
      header {{ gap: 14px; }}
      .scan-banner {{ align-items: flex-start; flex-direction: column; }}
      button {{ width: 100%; }}
      .actions {{ width: 100%; }}
      .filter-bar {{ max-width: 100%; overflow: hidden; }}
      .filter-bar a {{ max-width: 100%; }}
      .filter-chip {{ white-space: normal; }}
    }}
  </style>
</head>
<body>
  <main>
    {_dashboard_content(settings=settings, config_error=config_error, scan_error=scan_error, result=result, scheduler_status=scheduler_status, active_provider=active_provider)}
  </main>
</body>
</html>"""


def _dashboard_content(
    *,
    settings: Settings | None,
    config_error: str | None,
    scan_error: str | None,
    result: ScanRunResult | None,
    scheduler_status: SchedulerStatus | None,
    active_provider: str | None,
) -> str:
    summary = _configuration_summary(settings)
    scanning = bool(scheduler_status and scheduler_status.scan_running)
    disabled = "disabled" if config_error or scanning else ""
    loading_class = " is-loading" if scanning else ""
    button_text = "Scansione in corso..." if scanning else "Avvia scansione ora"
    scan_url = _scan_url("/scan", active_provider)
    poll_attrs = (
        f' hx-get="{_scan_url("/scan/status", active_provider)}" hx-trigger="every 2s" hx-swap="outerHTML"'
        if scanning
        else ""
    )

    return f"""
    <div id="dashboard-content"{poll_attrs}>
      <header>
        <div>
          <h1>streaming-checker</h1>
          <p class="subtle">{_last_scan_text(result)}</p>
        </div>
        <form class="actions" method="post" action="{scan_url}" hx-post="{scan_url}" hx-target="#dashboard-content" hx-swap="outerHTML">
          <button type="submit" class="{loading_class.strip()}" {disabled}><span class="spinner" aria-hidden="true"></span>{button_text}</button>
        </form>
      </header>

      {_alert(config_error, "Configurazione non valida")}
      {_alert(scan_error, _scan_error_title(scan_error))}
      {_scan_banner(scheduler_status)}

      {_dashboard(result)}
      {_scheduler_panel(scheduler_status)}

      <section class="layout">
        <div class="panel">
          <h2>Ultimi risultati</h2>
          {_results_section(result, active_provider)}
        </div>
        <aside>
          <div class="panel">
            <h2>Statistiche provider</h2>
            {_provider_statistics(result)}
          </div>
          <div class="panel" style="margin-top: 18px;">
            <h2>Configurazione</h2>
            {_config_table(summary)}
          </div>
        </aside>
      </section>
    </div>"""


def _scan_url(path: str, active_provider: str | None) -> str:
    if active_provider is None:
        return path
    return f"{path}?provider={quote(active_provider)}"


def _scan_error_title(message: str | None) -> str:
    if message and "scan already running" in message:
        return "Scansione già in corso"
    return "Ultima scansione fallita"


def _scan_banner(status: SchedulerStatus | None) -> str:
    if not status or not status.scan_running:
        return ""

    started = _format_datetime(status.current_scan_started_at)
    started_text = f"Avviata: {started}" if started != "-" else "Avvio in corso"
    return (
        '<div class="scan-banner" role="status" aria-live="polite">'
        "<div><strong>Scansione in corso, attendere...</strong>"
        f"<span>{escape(started_text)}</span></div>"
        '<span class="status processed">running</span>'
        "</div>"
    )


def _alert(message: str | None, title: str) -> str:
    if not message:
        return ""
    return f'<div class="alert"><strong>{escape(title)}:</strong> {escape(message)}</div>'


def _dashboard(result: ScanRunResult | None) -> str:
    metrics = [
        ("Mancanti", result.missing_count if result else 0),
        ("Processati", result.processed_count if result else 0),
        ("Saltati", result.skipped_count if result else 0),
        ("Errori", result.error_count if result else 0),
        ("Cambi provider", result.changed_count if result else 0),
        ("Notifiche", result.notification_count if result else 0),
        ("Inviate", result.notification_sent_count if result else 0),
    ]
    cards = "".join(
        f'<div class="panel metric"><span class="value">{value}</span><span class="label">{label}</span></div>'
        for label, value in metrics
    )
    return f'<section class="grid">{cards}</section>'


def _scheduler_panel(status: SchedulerStatus | None) -> str:
    if status is None:
        items = [
            ("Stato", "non disponibile"),
            ("Prossima", "-"),
            ("Ultima", "-"),
            ("Intervallo", "-"),
            ("Origine", "-"),
        ]
    else:
        state = "running" if status.running else "stopped"
        if status.scan_running:
            state = "scan in corso"
        items = [
            ("Stato", state),
            ("Prossima", _format_datetime(status.next_scan_at)),
            ("Ultima", _format_datetime(status.last_scan_at)),
            ("Intervallo", f"{status.interval_hours:g}h" if status.interval_hours else "-"),
            ("Origine", status.last_scan_source or "-"),
        ]
        if status.last_skip_reason or status.error:
            items.append(("Nota", status.error or status.last_skip_reason or "-"))

    rendered = "".join(
        '<div class="scheduler-item">'
        f'<span class="scheduler-label">{escape(label)}</span>'
        f'<span class="scheduler-value">{escape(value)}</span>'
        "</div>"
        for label, value in items
    )
    return f'<section class="panel scheduler-card"><h2>Scheduler</h2><div class="scheduler-strip">{rendered}</div></section>'


def _results_section(result: ScanRunResult | None, active_provider: str | None) -> str:
    return (
        '<div id="results-section">'
        + _provider_filter_bar(result, active_provider)
        + _results_table(result, active_provider)
        + "</div>"
    )


def _provider_filter_bar(result: ScanRunResult | None, active_provider: str | None) -> str:
    if result is None or not result.provider_statistics:
        return ""

    chips = [_filter_chip("All", None, result.processed_count, active_provider is None)]
    chips.extend(
        _filter_chip(provider, provider, count, provider == active_provider)
        for provider, count in _sorted_statistics(result.provider_statistics)
    )
    return '<nav class="filter-bar" aria-label="Provider filters">' + "".join(chips) + "</nav>"


def _filter_chip(label: str, provider: str | None, count: int, active: bool) -> str:
    href = "/" if provider is None else f"/?provider={quote(provider)}"
    active_class = " active" if active else ""
    chip = _provider_badge(label, extra_class=f"filter-chip{active_class}", count=count)
    return (
        f'<a href="{href}" hx-get="{href}" hx-target="#results-section" '
        f'hx-push-url="true">{chip}</a>'
    )


def _results_table(result: ScanRunResult | None, active_provider: str | None = None) -> str:
    if result is None:
        return '<p class="empty">Nessuna scansione eseguita in questa sessione.</p>'

    rows: list[str] = []
    cards: list[str] = []
    for arr_result in result.arr_results:
        if not arr_result.enabled:
            rows.append(
                f"<tr><td>{escape(arr_result.kind)}</td><td>-</td><td>-</td><td>-</td><td>"
                '<span class="status skipped">disabled</span></td><td>-</td><td>-</td></tr>'
            )
            cards.append(
                _result_card(
                    service=arr_result.kind,
                    media_type=None,
                    title="Servizio disabilitato",
                    providers_html="-",
                    change_status=None,
                    status="skipped",
                    message=None,
                )
            )
            continue

        if not arr_result.items:
            rows.append(
                f"<tr><td>{escape(arr_result.kind)}</td><td>-</td><td>-</td><td>-</td><td>"
                '<span class="status processed">empty</span></td><td>-</td><td>Nessun elemento mancante</td></tr>'
            )
            cards.append(
                _result_card(
                    service=arr_result.kind,
                    media_type=None,
                    title="Nessun elemento mancante",
                    providers_html="-",
                    change_status=None,
                    status="processed",
                    message=None,
                )
            )
            continue

        for item in arr_result.items:
            if not _item_matches_provider(item.providers, active_provider):
                continue

            providers = _providers_display(item.providers, item.original_provider_names)
            message = item.message or "-"
            rows.append(
                "<tr>"
                f"<td>{escape(item.kind)}</td>"
                f"<td>{_media_type_badge(item.media_type)}</td>"
                f'<td class="title-cell">{escape(item.title)}</td>'
                f"<td>{_change_status_badge(item.change_status)}</td>"
                f'<td><span class="status {escape(item.status)}">{escape(item.status)}</span></td>'
                f'<td class="provider-cell">{providers}</td>'
                f'<td class="message-cell">{escape(message)}</td>'
                "</tr>"
            )
            cards.append(
                _result_card(
                    service=item.kind,
                    media_type=item.media_type,
                    title=item.title,
                    providers_html=providers,
                    change_status=item.change_status,
                    status=item.status,
                    message=item.message,
                )
            )

    if not rows:
        provider_text = escape(active_provider) if active_provider else "questo filtro"
        return f'<p class="empty">Nessun risultato per {provider_text}.</p>'

    return (
        '<div class="table-scroll desktop-results"><table class="results-table"><thead><tr><th>Servizio</th><th>Tipo</th><th>Titolo</th><th>Cambio</th><th>Stato</th>'
        "<th>Provider</th><th>Messaggio</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        + '<div class="mobile-results" aria-label="Risultati scansione">'
        + "".join(cards)
        + "</div>"
    )


def _config_table(summary: dict[str, str | bool | list[str]]) -> str:
    if not summary:
        return '<p class="empty">Configurazione non disponibile.</p>'

    rows = []
    for key, value in summary.items():
        display = ", ".join(value) if isinstance(value, list) else str(value)
        rows.append(f"<dt>{escape(key)}</dt><dd><code>{escape(display)}</code></dd>")

    return '<dl class="config-list">' + "".join(rows) + "</dl>"


def _providers_display(canonical_names: list[str], original_names: list[str]) -> str:
    if not canonical_names:
        return "-"

    chips = "".join(_provider_badge(provider) for provider in canonical_names)
    display = f'<span class="providers">{chips}</span>'
    if sorted(canonical_names) != sorted(original_names):
        originals = ", ".join(original_names) if original_names else "-"
        display = f'{display}<span class="debug" title="TMDB: {escape(originals)}">TMDB: {escape(originals)}</span>'
    return display


def _result_card(
    *,
    service: str,
    media_type: str | None,
    title: str,
    providers_html: str,
    change_status: str | None,
    status: str,
    message: str | None,
) -> str:
    media_badge = _media_type_badge(media_type) if media_type else ""
    change_badge = _change_status_badge(change_status) if change_status else ""
    message_html = (
        f'<span class="debug">{escape(message)}</span>'
        if message and providers_html == "-"
        else ""
    )
    return (
        '<article class="result-card">'
        '<div class="result-card-header">'
        f'<span class="result-service">{escape(service)}</span>'
        '<span class="result-card-badges">'
        f"{media_badge}{change_badge}"
        f'<span class="status {escape(status)}">{escape(status)}</span>'
        "</span>"
        "</div>"
        f'<div class="result-title">{escape(title)}</div>'
        f'<div class="result-providers">{providers_html}{message_html}</div>'
        "</article>"
    )


def _media_type_badge(media_type: str) -> str:
    css_class = "badge-series" if media_type == "series" else "badge-movie"
    label = "📺 Series" if media_type == "series" else "🎬 Movie"
    return f'<span class="badge {css_class}">{label}</span>'


def _change_status_badge(change_status: str) -> str:
    normalized = change_status.upper()
    css_class = {
        "NEW": "change-new",
        "UPDATED": "change-updated",
        "UNCHANGED": "change-unchanged",
        "REMOVED": "change-removed",
    }.get(normalized, "change-unchanged")
    return f'<span class="badge {css_class}">{escape(normalized)}</span>'


def _provider_statistics(result: ScanRunResult | None) -> str:
    if result is None or not result.provider_statistics:
        return '<p class="empty">Nessun dato provider disponibile.</p>'

    provider_rows = "".join(
        f"<tr><td>{escape(provider)}</td><td>{count}</td></tr>"
        for provider, count in _sorted_statistics(result.provider_statistics)
    )
    category_rows = "".join(
        f"<tr><td>{escape(category)}</td><td>{count}</td></tr>"
        for category, count in _sorted_statistics(result.provider_category_statistics)
    )
    categories = (
        '<h3>Categorie</h3><table class="stats-table"><tbody>' + category_rows + "</tbody></table>"
        if category_rows
        else ""
    )
    return '<table class="stats-table"><tbody>' + provider_rows + "</tbody></table>" + categories


def _provider_badge(provider: str, *, extra_class: str = "", count: int | None = None) -> str:
    provider_class = PROVIDER_BADGE_COLORS.get(provider, "default")
    count_html = f'<span class="filter-count">({count})</span>' if count is not None else ""
    classes = f"provider-chip provider-{escape(provider_class)}"
    if extra_class:
        classes = f"{classes} {escape(extra_class)}"
    return f'<span class="{classes}">{escape(provider)}{count_html}</span>'


def _sorted_statistics(statistics: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(statistics.items(), key=lambda item: (-item[1], item[0].casefold()))


def _resolve_provider_filter(result: ScanRunResult | None, provider: str | None) -> str | None:
    if not result or not provider:
        return None

    requested = provider.strip().casefold()
    for canonical_provider in result.provider_statistics:
        if canonical_provider.casefold() == requested:
            return canonical_provider
    return None


def _item_matches_provider(providers: list[str], active_provider: str | None) -> bool:
    if active_provider is None:
        return True
    return active_provider in providers


def _last_scan_text(result: ScanRunResult | None) -> str:
    if result is None:
        return "Nessuna scansione eseguita"

    return (
        "Ultima scansione: "
        f"{escape(result.finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S'))} "
        f"({result.duration_seconds:.2f}s)"
    )


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


@app.get("/api/last-scan")
def last_scan():
    with _state_lock:
        if _last_result is None:
            return {"result": None, "error": _last_error}
        payload = asdict(_last_result)
        payload["provider_statistics"] = _last_result.provider_statistics
        payload["provider_category_statistics"] = _last_result.provider_category_statistics
        return {"result": payload, "error": _last_error}


@app.get("/api/scheduler")
def scheduler_status():
    status = _scheduler_status()
    return {"scheduler": asdict(status) if status else None}
