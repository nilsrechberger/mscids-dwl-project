-- Exploration queries for the raw Ist-Daten v2 table.
--
-- Run them in the Athena console with workgroup mscids-dwl-<environment> and
-- database mscids_dwl_<environment>_raw. Always restrict dt: one day scans
-- about 0.7 GB (~0.004 USD), the whole 50-day CKAN window about 34 GB (~0.17 USD).
-- Run each statement on its own.
--
-- A raw day folder can hold more than the current data file: the run manifest,
-- older runs of a replaced file and (test bucket only) files of the earlier
-- permalink loader. Query 1 shows them. The filter
--     "$path" LIKE '%/run=istdaten-v2-%/data.csv'
-- drops manifests and permalink files; for exactly one version per day use the
-- data_key from the run manifest (query 2).


-- 1) Which files does Athena see per day? Expect one data.csv per day.
--    More than one data.csv on a day means CKAN replaced the file.
SELECT dt, "$path" AS file, count(*) AS row_count
FROM istdaten_v2
WHERE dt BETWEEN '2026-11-15' AND '2026-11-21'
GROUP BY dt, "$path"
ORDER BY dt, file;


-- 2) Sample rows of one exact file version (path = s3://<bucket>/ + data_key
--    from manifest.json). Check the timestamp formats and status values here.
SELECT *
FROM istdaten_v2
WHERE dt = '2026-11-21'
  AND "$path" = 's3://<bucket>/raw/istdaten_v2/dt=2026-11-21/run=istdaten-v2-2026-11-21-<hash12>/data.csv'
LIMIT 20;


-- 3) Volume per day: rows, trips, stops, cancellations and extra trips.
SELECT dt,
       count(*)                                         AS stop_events,
       count(DISTINCT fahrt_bezeichner)                 AS trips,
       count(DISTINCT bpuic)                            AS stops,
       round(avg(IF(faellt_aus_tf = 'true', 1.0, 0.0)) * 100, 2) AS cancelled_pct,
       round(avg(IF(zusatzfahrt_tf = 'true', 1.0, 0.0)) * 100, 2) AS extra_trip_pct
FROM istdaten_v2
WHERE dt BETWEEN '2026-11-15' AND '2026-11-21'
  AND "$path" LIKE '%/run=istdaten-v2-%/data.csv'
GROUP BY dt
ORDER BY dt;


-- 4) Forecast status mix for arrivals (only REAL is a measured time).
SELECT an_prognose_status, count(*) AS stop_events
FROM istdaten_v2
WHERE dt = '2026-11-21'
  AND "$path" LIKE '%/run=istdaten-v2-%/data.csv'
GROUP BY an_prognose_status
ORDER BY stop_events DESC;


-- 5) Arrival delay distribution for measured (REAL) arrivals.
--    Timestamps come as dd.MM.yyyy HH:mm (scheduled) or dd.MM.yyyy HH:mm:ss
--    (forecast); both are tried. Delays beyond +-6 h are treated as invalid,
--    as in scripts/delay_quality.py.
WITH arrivals AS (
    SELECT
        date_diff(
            'second',
            coalesce(try(date_parse(ankunftszeit, '%d.%m.%Y %H:%i:%s')), try(date_parse(ankunftszeit, '%d.%m.%Y %H:%i'))),
            coalesce(try(date_parse(an_prognose, '%d.%m.%Y %H:%i:%s')), try(date_parse(an_prognose, '%d.%m.%Y %H:%i')))
        ) AS delay_s
    FROM istdaten_v2
    WHERE dt = '2026-11-21'
      AND "$path" LIKE '%/run=istdaten-v2-%/data.csv'
      AND an_prognose_status = 'REAL'
      AND faellt_aus_tf <> 'true'
)
SELECT
    CASE
        WHEN delay_s < -60  THEN 'a) early > 1 min'
        WHEN delay_s < 180  THEN 'b) on time (< 3 min)'
        WHEN delay_s < 360  THEN 'c) 3-6 min'
        WHEN delay_s < 900  THEN 'd) 6-15 min'
        ELSE                     'e) > 15 min'
    END AS delay_class,
    count(*) AS arrivals,
    round(count(*) * 100.0 / sum(count(*)) OVER (), 2) AS pct
FROM arrivals
WHERE delay_s IS NOT NULL AND abs(delay_s) <= 6 * 3600
GROUP BY 1
ORDER BY 1;


-- 6) Punctuality by means of transport (share of REAL arrivals >= 3 min late).
WITH arrivals AS (
    SELECT
        verkehrsmittel_text,
        date_diff(
            'second',
            coalesce(try(date_parse(ankunftszeit, '%d.%m.%Y %H:%i:%s')), try(date_parse(ankunftszeit, '%d.%m.%Y %H:%i'))),
            coalesce(try(date_parse(an_prognose, '%d.%m.%Y %H:%i:%s')), try(date_parse(an_prognose, '%d.%m.%Y %H:%i')))
        ) AS delay_s
    FROM istdaten_v2
    WHERE dt = '2026-11-21'
      AND "$path" LIKE '%/run=istdaten-v2-%/data.csv'
      AND an_prognose_status = 'REAL'
      AND faellt_aus_tf <> 'true'
)
SELECT verkehrsmittel_text,
       count(*) AS arrivals,
       round(avg(IF(delay_s >= 180, 1.0, 0.0)) * 100, 2) AS late_3min_pct,
       round(avg(delay_s) / 60.0, 2) AS avg_delay_min
FROM arrivals
WHERE delay_s IS NOT NULL AND abs(delay_s) <= 6 * 3600
GROUP BY verkehrsmittel_text
HAVING count(*) >= 1000
ORDER BY arrivals DESC;
