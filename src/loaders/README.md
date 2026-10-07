# Data Fetching

Each loader fetches raw data from one external source. Endpoints and tokens come from `src.config`.

## GTFS-RT

[gtfs_rt.py](gtfs_rt.py) — `fetch_gtfs_rt() -> dict`

Fetches the GTFS-Realtime feed as JSON (`GTFS_RT_API_ENDPOINT?format=JSON`). The request is authenticated with `GTFS_RT_API_TOKEN`.

## Municipality

[municipality.py](municipality.py) — `fetch_municipality() -> requests.Response`

Downloads the static municipality XLSX file from the BFS (`MUNICIPALITY_XLSX`). It returns the raw response, so the caller has to parse the file.

## Transport

[transport.py](transport.py) — `fetch_locations(query="Basel") -> dict`

Searches locations through the Swiss public transport API (`TRANSPORT_API_ENDPOINT/locations`). `query` is the name to search for.

## Weather

[weather.py](weather.py) — `fetch_weather(url) -> list[WeatherApiResponse]`

Fetches hourly `temperature_2m` from Open-Meteo for a fixed location and date range (2026-09-14 to 2026-09-28). `url` is the API endpoint.
