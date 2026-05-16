from __future__ import annotations

from dataclasses import asdict
from html import escape
from threading import Lock
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

from streaming_checker.core.config import Settings, load_settings
from streaming_checker.services.runner import ScanRunResult, ScanRunner
from streaming_checker.storage import initialize_storage_from_environment

app = FastAPI(title="streaming-checker")

_state_lock = Lock()
_last_result: ScanRunResult | None = None
_last_error: str | None = None


@app.on_event("startup")
def initialize_storage():
    global _last_error

    try:
        initialize_storage_from_environment()
    except Exception as exc:
        _last_error = str(exc)


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
        "radarr_enabled": bool(settings.radarr_url and settings.radarr_api_key),
        "radarr_url": _safe_url(settings.radarr_url),
        "radarr_api_key_configured": bool(settings.radarr_api_key),
        "sonarr_enabled": bool(settings.sonarr_url and settings.sonarr_api_key),
        "sonarr_url": _safe_url(settings.sonarr_url),
        "sonarr_api_key_configured": bool(settings.sonarr_api_key),
        "tmdb_bearer_token_configured": bool(settings.tmdb_bearer_token),
    }


@app.get("/", response_class=HTMLResponse)
def home():
    settings, config_error = _load_settings_for_page()

    with _state_lock:
        result = _last_result
        scan_error = _last_error

    return HTMLResponse(
        _render_page(
            settings=settings,
            config_error=config_error,
            scan_error=scan_error,
            result=result,
        )
    )


@app.post("/scan")
def trigger_scan():
    global _last_error, _last_result

    try:
        settings = load_settings()
        result = ScanRunner(settings).run()
        with _state_lock:
            _last_result = result
            _last_error = None
    except Exception as exc:
        with _state_lock:
            _last_error = str(exc)

    return RedirectResponse("/", status_code=303)


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
) -> str:
    summary = _configuration_summary(settings)
    disabled = "disabled" if config_error else ""

    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>streaming-checker</title>
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
      padding: 18px;
    }}
    .metric .value {{ display: block; font-size: 30px; font-weight: 800; }}
    .metric .label {{ color: var(--muted); font-size: 13px; }}
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
    .empty {{
      color: var(--muted);
      padding: 18px 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
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
    .processed {{ background: #dff7ee; color: var(--ok); }}
    .skipped {{ background: #fff0d8; color: var(--warning); }}
    .error {{ background: #ffe2df; color: var(--danger); }}
    .config-list {{
      display: grid;
      grid-template-columns: minmax(120px, 0.9fr) minmax(0, 1.1fr);
      gap: 10px 14px;
      font-size: 14px;
    }}
    .config-list dt {{ color: var(--muted); }}
    .config-list dd {{ margin: 0; overflow-wrap: anywhere; }}
    @media (max-width: 820px) {{
      header, .layout {{ grid-template-columns: 1fr; display: grid; }}
      .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .actions {{ justify-content: start; }}
    }}
    @media (max-width: 520px) {{
      main {{ width: min(100% - 20px, 1120px); padding-top: 20px; }}
      .grid {{ grid-template-columns: 1fr; }}
      th:nth-child(1), td:nth-child(1) {{ display: none; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>streaming-checker</h1>
        <p class="subtle">{_last_scan_text(result)}</p>
      </div>
      <form class="actions" method="post" action="/scan">
        <button type="submit" {disabled}>Avvia scansione</button>
      </form>
    </header>

    {_alert(config_error, "Configurazione non valida")}
    {_alert(scan_error, "Ultima scansione fallita")}

    {_dashboard(result)}

    <section class="layout">
      <div class="panel">
        <h2>Ultimi risultati</h2>
        {_results_table(result)}
      </div>
      <aside class="panel">
        <h2>Configurazione</h2>
        {_config_table(summary)}
      </aside>
    </section>
  </main>
</body>
</html>"""


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
    ]
    cards = "".join(
        f'<div class="panel metric"><span class="value">{value}</span><span class="label">{label}</span></div>'
        for label, value in metrics
    )
    return f'<section class="grid">{cards}</section>'


def _results_table(result: ScanRunResult | None) -> str:
    if result is None:
        return '<p class="empty">Nessuna scansione eseguita in questa sessione.</p>'

    rows: list[str] = []
    for arr_result in result.arr_results:
        if not arr_result.enabled:
            rows.append(
                f"<tr><td>{escape(arr_result.kind)}</td><td>-</td><td>"
                '<span class="status skipped">disabled</span></td><td>-</td><td>-</td></tr>'
            )
            continue

        if not arr_result.items:
            rows.append(
                f"<tr><td>{escape(arr_result.kind)}</td><td>-</td><td>"
                '<span class="status processed">empty</span></td><td>-</td><td>Nessun elemento mancante</td></tr>'
            )
            continue

        for item in arr_result.items:
            providers = ", ".join(item.providers) if item.providers else "-"
            message = item.message or "-"
            rows.append(
                "<tr>"
                f"<td>{escape(item.kind)}</td>"
                f"<td>{escape(item.title)}</td>"
                f'<td><span class="status {escape(item.status)}">{escape(item.status)}</span></td>'
                f"<td>{escape(providers)}</td>"
                f"<td>{escape(message)}</td>"
                "</tr>"
            )

    return (
        "<table><thead><tr><th>Servizio</th><th>Titolo</th><th>Stato</th>"
        "<th>Provider</th><th>Messaggio</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _config_table(summary: dict[str, str | bool | list[str]]) -> str:
    if not summary:
        return '<p class="empty">Configurazione non disponibile.</p>'

    rows = []
    for key, value in summary.items():
        display = ", ".join(value) if isinstance(value, list) else str(value)
        rows.append(f"<dt>{escape(key)}</dt><dd><code>{escape(display)}</code></dd>")

    return '<dl class="config-list">' + "".join(rows) + "</dl>"


def _last_scan_text(result: ScanRunResult | None) -> str:
    if result is None:
        return "Nessuna scansione eseguita"

    return (
        "Ultima scansione: "
        f"{escape(result.finished_at.astimezone().strftime('%Y-%m-%d %H:%M:%S'))} "
        f"({result.duration_seconds:.2f}s)"
    )


@app.get("/api/last-scan")
def last_scan():
    with _state_lock:
        if _last_result is None:
            return {"result": None, "error": _last_error}
        return {"result": asdict(_last_result), "error": _last_error}
