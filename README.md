# streaming-checker

Piccolo container Python per controllare se film/serie mancanti in Radarr/Sonarr sono disponibili in streaming in Italia tramite TMDB Watch Providers, e applicare tag automatici.

## Cosa fa

- Legge Radarr e/o Sonarr via API.
- Considera solo contenuti `monitored` e mancanti.
- Interroga TMDB Watch Providers per `COUNTRY=IT`.
- Aggiunge tag tipo:
  - `available-streaming`
  - `streaming-netflix`
  - `streaming-prime-video`
  - `streaming-disney-plus`
- Rimuove i tag gestiti quando il contenuto non risulta più disponibile, se `REMOVE_STALE_TAGS=true`.
- Salva cronologia scansioni, cache disponibilità e storico notifiche in SQLite.
- Di default è in `DRY_RUN=true`, quindi non modifica nulla.

## Requisiti

- API key Radarr
- API key Sonarr, opzionale
- TMDB API Bearer Token

Su TMDB: Settings → API → API Read Access Token.

## Avvio rapido

Copia `.env.example` in `.env` e modifica i valori.

```bash
docker compose up -d
```

La UI web è disponibile su:

```text
http://localhost:8080
```

Per applicare davvero i tag:

```env
DRY_RUN=false
```

## Variabili principali

```env
RADARR_URL=http://radarr:7878
RADARR_API_KEY=xxx

SONARR_URL=http://sonarr:8989
SONARR_API_KEY=xxx

TMDB_BEARER_TOKEN=xxx
COUNTRY=IT

DRY_RUN=true
REMOVE_STALE_TAGS=true
TAG_GENERIC=true
TAG_PROVIDERS=true
GENERIC_TAG=available-streaming
DATABASE_PATH=/data/streaming_checker.sqlite
```

## Persistenza SQLite

All'avvio vengono create automaticamente le tabelle SQLite, se mancanti:

- `availability_cache`
- `notification_history`
- `scan_history`

La cache confronta i provider dell'ultima scansione con quelli già noti per ogni contenuto e registra una voce di storico solo per stati non già notificati.

## Note

Per Radarr viene usato `tmdbId` già presente nella movie entity.

Per Sonarr:
- se la serie ha `tmdbId`, usa quello;
- altrimenti prova `tvdbId` tramite endpoint TMDB `/find/{tvdbId}?external_source=tvdb_id`.

## Primo test consigliato

1. Lascia `DRY_RUN=true`.
2. Avvia il container.
3. Controlla i log.
4. Solo dopo metti `DRY_RUN=false`.

## Sviluppo

Il codice applicativo vive nel package `streaming_checker`.

```bash
python -m unittest discover -s tests
```

La CLI resta disponibile con:

```bash
python -m streaming_checker
```

Nel container puoi eseguire una scansione CLI con:

```bash
docker compose run --rm streaming-checker python -m streaming_checker
```
