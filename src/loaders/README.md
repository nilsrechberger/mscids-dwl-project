# Data Fetching

Each loader fetches raw data from one external source. Endpoints and tokens come from `src.config`.

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
