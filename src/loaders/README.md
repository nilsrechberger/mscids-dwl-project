# Data Fetching

Each loader fetches raw data from one external source. Endpoints and tokens come from `src.config`.

## Ist-Daten v2

[istdaten_v2.py](istdaten_v2.py) — `fetch_istdaten_v2() -> requests.Response`

Streams the official daily Ist-Daten v2 CSV from `ISTDATEN_V2_ENDPOINT`. The response stream is uploaded unchanged to `raw/istdaten_v2/` so the large CSV is not materialized in Lambda memory. Column normalization and delay-quality flags belong to later Silver processing.

## GTFS-RT

[gtfs_rt.py](gtfs_rt.py) — `fetch_gtfs_rt() -> dict`

Fetches the GTFS-Realtime feed as JSON (`GTFS_RT_API_ENDPOINT?format=JSON`). The request is authenticated with `GTFS_RT_API_TOKEN`.

## Municipality

[municipality.py](municipality.py) — `fetch_municipality() -> requests.Response`, `parse_municipality_names(xlsx: bytes) -> list[str]`

Downloads the static municipality XLSX file from the BFS (`MUNICIPALITY_XLSX`). It returns the raw response, so the caller has to parse the file.

## Transport

[transport.py](transport.py)

- `fetch_locations(query="Basel", session=None) -> dict` searches locations through the Swiss public transport API (`TRANSPORT_API_ENDPOINT/locations`).
- `fetch_all_locations(municipalities) -> dict[str, dict]` calls it for every municipality name and returns `{name: response}`. A failing name is logged and skipped; if all fail, the error is raised.

`src.run` loads transport in batches (`TRANSPORT_BATCH_SIZE` municipalities per invocation, see the main README) and takes the names from the newest `raw/municipality/` file in the data lake (downloaded from the BFS only if none exists yet) via `parse_municipality_names` in [municipality.py](municipality.py) (unique `Gemeindename` values). The BFS file is the historised directory, so it also contains merged municipalities that no longer exist.

## Weather

[weather.py](weather.py) — `fetch_weather(start_date, end_date) -> dict[str, dict]`

Fetches hourly `temperature_2m` and `rain` from the Open-Meteo archive API (`WEATHER_API_ENDPOINT`) for all 26 cantons in one request. The static `CANTONS` dict holds the coordinates of each cantonal capital. The result is `{canton code: response}`. The default range is 2026-09-14 to 2026-09-28.

## Source contract status

The canonical source registry is defined in `src/sources.py` and is used by `src.run` to validate local and Lambda invocations.

Production sources for the municipality pipeline are currently:

- `istdaten_v2`: primary daily transport source, streamed as unchanged CSV.
- `municipality`: BFS municipality reference source.
- `municipality_weather`: batched Open-Meteo archive responses for the versioned municipality point snapshot.

The following loaders remain available for compatibility or baseline comparisons, but are not the primary municipality-analysis sources yet:

- `weather`: canton-capital weather baseline.
- `transport`: legacy location-search API, loaded in batches.
- `gtfs_rt`: legacy realtime feed.

The municipality-level weather loader reads `MUNICIPALITY_WEATHER_POINTS`, requests up to `MUNICIPALITY_WEATHER_BATCH_SIZE` locations per API call, and stores an envelope containing the request points and raw API response. The existing canton-level `weather` source remains a separate baseline and must not be used as a substitute for municipality weather.
