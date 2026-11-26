-- Checks for silver.istdaten (database mscids_dwl_<environment>_silver).
-- The table is built by the silver-istdaten state machine; the statements
-- live in src/silver/sql. Silver is Parquet, so these queries scan little.
-- Run each statement on its own.


-- 1) Rows and source run per day. Expect one source_run_id per day.
SELECT operating_date, count(*) AS stop_events,
       count(DISTINCT source_run_id) AS source_runs,
       min(source_run_id) AS source_run_id
FROM istdaten
WHERE operating_date BETWEEN DATE '2025-08-01' AND DATE '2025-08-07'
GROUP BY operating_date
ORDER BY operating_date;


-- 2) Completeness: days in Silver per month (compare with the raw days).
SELECT date_trunc('month', operating_date) AS month,
       count(DISTINCT operating_date) AS days,
       count(*) AS stop_events
FROM istdaten
GROUP BY 1
ORDER BY 1;


-- 3) Delay quality mix per day (rules from scripts/delay_quality.py).
SELECT operating_date, delay_quality, count(*) AS stop_events
FROM istdaten
WHERE operating_date = DATE '2026-11-24'
GROUP BY operating_date, delay_quality
ORDER BY stop_events DESC;


-- 4) Same day in raw (scans the CSV, ~0.7 GB): the row count must match 1).
--    Replace the path with the source_data_key from the build marker
--    silver/_state/istdaten/dt=<day>/run=<run_id>.json.
SELECT count(*) AS raw_rows
FROM mscids_dwl_test_raw.istdaten_v2
WHERE dt = '2026-11-24'
  AND "$path" = 's3://<bucket>/raw/istdaten_v2/dt=2026-11-24/run=<run_id>/data.csv';


-- 5) Punctuality of measured arrivals per means of transport (example analysis).
SELECT vehicle_type,
       count(*) AS arrivals,
       round(avg(arrival_delay_seconds) / 60.0, 2) AS avg_delay_min,
       round(avg(IF(arrival_delay_seconds >= 180, 1.0, 0.0)) * 100, 2) AS late_3min_pct
FROM istdaten
WHERE operating_date BETWEEN DATE '2026-11-01' AND DATE '2026-11-24'
  AND arrival_usable_for_real_delay
GROUP BY vehicle_type
ORDER BY arrivals DESC;


-- Maintenance (occasionally, e.g. monthly): merge small files and drop
-- data files no longer referenced after rebuilds.
-- OPTIMIZE istdaten REWRITE DATA USING BIN_PACK;
-- VACUUM istdaten;
