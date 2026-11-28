-- Stop -> municipality mapping (database mscids_dwl_<environment>_silver).
-- service_points is the atlas export, one row per validity period of a
-- service point (TSV, rewritten by the service_points load). Ist-Daten stops
-- join on the 7-digit BPUIC: istdaten.stop_id_bpuic = service_points.number.
-- Run each statement on its own.


-- 1) Overview of the reference: versions, stop numbers, municipalities.
SELECT count(*) AS versions,
       count(DISTINCT number) AS stop_numbers,
       count_if(is_latest_version) AS latest_versions,
       count_if(is_stop_point) AS stop_point_versions,
       count_if(municipality_gdenr IS NULL) AS without_municipality,
       count(DISTINCT municipality_gdenr) AS municipalities,
       min(source_run_id) AS source_run_id
FROM service_points;


-- 2) Stop numbers with more than one municipality over time (mergers,
--    corrections). These are the stops where the operating date matters.
SELECT number, designation_official,
       array_agg(DISTINCT municipality_gdenr) AS gdenrs,
       count(*) AS versions
FROM service_points
WHERE municipality_gdenr IS NOT NULL
GROUP BY number, designation_official
HAVING count(DISTINCT municipality_gdenr) > 1
ORDER BY versions DESC
LIMIT 50;


-- 3) Coverage for one week: share of stop events with a municipality.
--    Version valid on the operating day first, newest version as fallback.
WITH events AS (
    SELECT operating_date, stop_id_bpuic
    FROM istdaten
    WHERE operating_date BETWEEN DATE '2026-11-01' AND DATE '2026-11-07'
)
SELECT count(*) AS stop_events,
       count(v.number) AS matched_by_validity,
       count(coalesce(v.municipality_gdenr, l.municipality_gdenr)) AS with_municipality,
       round(100.0 * count(coalesce(v.municipality_gdenr, l.municipality_gdenr))
             / count(*), 2) AS pct_with_municipality
FROM events e
LEFT JOIN service_points v
  ON v.number = e.stop_id_bpuic
 AND e.operating_date BETWEEN v.valid_from AND v.valid_to
LEFT JOIN service_points l
  ON l.number = e.stop_id_bpuic
 AND l.is_latest_version;


-- 4) Unmatched stops with the most events (candidates for a closer look).
SELECT e.stop_id_bpuic, arbitrary(e.stop_name) AS stop_name, count(*) AS events
FROM istdaten e
LEFT JOIN service_points sp ON sp.number = e.stop_id_bpuic
WHERE e.operating_date BETWEEN DATE '2026-11-01' AND DATE '2026-11-07'
  AND sp.number IS NULL
GROUP BY e.stop_id_bpuic
ORDER BY events DESC
LIMIT 30;


-- 5) Delays per municipality for one month (example for the Gold layer).
--    Weather points use the 2026 BFS municipality snapshot; compare the
--    gdenr of merged municipalities before joining weather.
SELECT coalesce(v.municipality_gdenr, l.municipality_gdenr) AS gdenr,
       arbitrary(coalesce(v.municipality_name, l.municipality_name)) AS municipality,
       count_if(e.arrival_usable_for_real_delay) AS usable_arrivals,
       round(avg(IF(e.arrival_usable_for_real_delay, e.arrival_delay_seconds)), 1)
           AS avg_arrival_delay_seconds
FROM istdaten e
LEFT JOIN service_points v
  ON v.number = e.stop_id_bpuic
 AND e.operating_date BETWEEN v.valid_from AND v.valid_to
LEFT JOIN service_points l
  ON l.number = e.stop_id_bpuic
 AND l.is_latest_version
WHERE e.operating_date BETWEEN DATE '2026-10-01' AND DATE '2026-10-31'
GROUP BY 1
ORDER BY usable_arrivals DESC
LIMIT 30;
