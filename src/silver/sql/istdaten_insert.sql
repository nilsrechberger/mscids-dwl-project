-- Build one operating day of silver.istdaten from exactly one raw file version.
-- The delay rules mirror scripts/delay_quality.py:
--   missing_time          scheduled or forecast time missing/unparseable
--   unknown_status        status not REAL, PROGNOSE or GESCHAETZT
--   cross_day_or_invalid  scheduled and forecast time on different dates
--   extreme_outlier       |delay| > 6 h (delay is kept, but not usable)
--   valid                 usable for the real-delay analysis only if status = REAL
-- Timestamps are Swiss local time (no time zone), as in the source.
INSERT INTO {silver_db}.istdaten
WITH src AS (
  SELECT
    r.*,
    coalesce(try(date_parse(ankunftszeit, '%d.%m.%Y %H:%i:%s')),
             try(date_parse(ankunftszeit, '%d.%m.%Y %H:%i'))) AS sched_arr,
    coalesce(try(date_parse(an_prognose, '%d.%m.%Y %H:%i:%s')),
             try(date_parse(an_prognose, '%d.%m.%Y %H:%i'))) AS fc_arr,
    coalesce(try(date_parse(abfahrtszeit, '%d.%m.%Y %H:%i:%s')),
             try(date_parse(abfahrtszeit, '%d.%m.%Y %H:%i'))) AS sched_dep,
    coalesce(try(date_parse(ab_prognose, '%d.%m.%Y %H:%i:%s')),
             try(date_parse(ab_prognose, '%d.%m.%Y %H:%i'))) AS fc_dep,
    upper(trim(coalesce(an_prognose_status, ''))) AS st_arr,
    upper(trim(coalesce(ab_prognose_status, ''))) AS st_dep,
    (trim(coalesce(ankunftszeit, '')) <> '' OR trim(coalesce(an_prognose, '')) <> '') AS has_arrival
  FROM {raw_db}.istdaten_v2 r
  WHERE r.dt = '{operating_day}'
    AND r."$path" = '{source_path}'
),
q AS (
  SELECT
    src.*,
    CASE
      WHEN sched_arr IS NULL OR fc_arr IS NULL THEN 'missing_time'
      WHEN st_arr NOT IN ('REAL', 'PROGNOSE', 'GESCHAETZT') THEN 'unknown_status'
      WHEN date(sched_arr) <> date(fc_arr) THEN 'cross_day_or_invalid'
      WHEN abs(date_diff('second', sched_arr, fc_arr)) > 21600 THEN 'extreme_outlier'
      ELSE 'valid'
    END AS q_arr,
    CASE
      WHEN sched_dep IS NULL OR fc_dep IS NULL THEN 'missing_time'
      WHEN st_dep NOT IN ('REAL', 'PROGNOSE', 'GESCHAETZT') THEN 'unknown_status'
      WHEN date(sched_dep) <> date(fc_dep) THEN 'cross_day_or_invalid'
      WHEN abs(date_diff('second', sched_dep, fc_dep)) > 21600 THEN 'extreme_outlier'
      ELSE 'valid'
    END AS q_dep
  FROM src
),
classified AS (
  SELECT
    q.*,
    CASE q_arr
      WHEN 'missing_time' THEN 'missing_time'
      WHEN 'unknown_status' THEN 'status_not_supported'
      WHEN 'cross_day_or_invalid' THEN 'timestamp_dates_differ'
      WHEN 'extreme_outlier' THEN 'absolute_delay_exceeds_threshold'
    END AS reason_arr,
    CASE q_dep
      WHEN 'missing_time' THEN 'missing_time'
      WHEN 'unknown_status' THEN 'status_not_supported'
      WHEN 'cross_day_or_invalid' THEN 'timestamp_dates_differ'
      WHEN 'extreme_outlier' THEN 'absolute_delay_exceeds_threshold'
    END AS reason_dep
  FROM q
)
SELECT
  DATE '{operating_day}'                                   AS operating_date,
  nullif(trim(fahrt_bezeichner), '')                       AS trip_id,
  nullif(trim(betreiber_id), '')                           AS operator_id,
  nullif(trim(betreiber_abk), '')                          AS operator_abbreviation,
  nullif(trim(betreiber_name), '')                         AS operator_name,
  nullif(trim(produkt_id), '')                             AS product_id,
  nullif(trim(linien_id), '')                              AS line_id,
  nullif(trim(linien_text), '')                            AS line_text,
  nullif(trim(umlauf_id), '')                              AS circulation_id,
  nullif(trim(verkehrsmittel_text), '')                    AS vehicle_type,
  CASE WHEN lower(trim(zusatzfahrt_tf)) IN ('true', '1', 'yes', 'ja') THEN true
       WHEN lower(trim(zusatzfahrt_tf)) IN ('false', '0', 'no', 'nein') THEN false
  END                                                      AS is_additional_trip,
  CASE WHEN lower(trim(faellt_aus_tf)) IN ('true', '1', 'yes', 'ja') THEN true
       WHEN lower(trim(faellt_aus_tf)) IN ('false', '0', 'no', 'nein') THEN false
  END                                                      AS is_cancelled,
  CASE WHEN lower(trim(durchfahrt_tf)) IN ('true', '1', 'yes', 'ja') THEN true
       WHEN lower(trim(durchfahrt_tf)) IN ('false', '0', 'no', 'nein') THEN false
  END                                                      AS is_pass_through,
  nullif(trim(bpuic), '')                                  AS stop_id_bpuic,
  nullif(trim(sloid), '')                                  AS stop_id_sloid,
  nullif(trim(haltestellen_name), '')                      AS stop_name,
  sched_arr                                                AS scheduled_arrival,
  fc_arr                                                   AS predicted_arrival,
  nullif(st_arr, '')                                       AS arrival_forecast_status,
  CASE WHEN q_arr IN ('valid', 'extreme_outlier')
       THEN CAST(date_diff('second', sched_arr, fc_arr) AS integer)
  END                                                      AS arrival_delay_seconds,
  q_arr                                                    AS arrival_delay_quality,
  reason_arr                                               AS arrival_exclusion_reason,
  (q_arr = 'valid' AND st_arr = 'REAL')                    AS arrival_usable_for_real_delay,
  sched_dep                                                AS scheduled_departure,
  fc_dep                                                   AS predicted_departure,
  nullif(st_dep, '')                                       AS departure_forecast_status,
  CASE WHEN q_dep IN ('valid', 'extreme_outlier')
       THEN CAST(date_diff('second', sched_dep, fc_dep) AS integer)
  END                                                      AS departure_delay_seconds,
  q_dep                                                    AS departure_delay_quality,
  reason_dep                                               AS departure_exclusion_reason,
  (q_dep = 'valid' AND st_dep = 'REAL')                    AS departure_usable_for_real_delay,
  IF(has_arrival, q_arr, q_dep)                            AS delay_quality,
  IF(has_arrival, reason_arr, reason_dep)                  AS delay_exclusion_reason,
  '{source_run_id}'                                        AS source_run_id,
  '{source_md5}'                                           AS source_md5
FROM classified
