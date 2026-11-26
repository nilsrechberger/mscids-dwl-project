-- Silver Ist-Daten: one row per stop event, typed and with delay quality.
-- Iceberg (Parquet, zstd) so a day can be deleted and rebuilt idempotently.
-- Placeholders (names in curly braces) are filled by src/silver/istdaten.py.
CREATE TABLE IF NOT EXISTS {silver_db}.istdaten (
  operating_date                  date,
  trip_id                         string,
  operator_id                     string,
  operator_abbreviation           string,
  operator_name                   string,
  product_id                      string,
  line_id                         string,
  line_text                       string,
  circulation_id                  string,
  vehicle_type                    string,
  is_additional_trip              boolean,
  is_cancelled                    boolean,
  is_pass_through                 boolean,
  stop_id_bpuic                   string,
  stop_id_sloid                   string,
  stop_name                       string,
  scheduled_arrival               timestamp,
  predicted_arrival               timestamp,
  arrival_forecast_status         string,
  arrival_delay_seconds           int,
  arrival_delay_quality           string,
  arrival_exclusion_reason        string,
  arrival_usable_for_real_delay   boolean,
  scheduled_departure             timestamp,
  predicted_departure             timestamp,
  departure_forecast_status       string,
  departure_delay_seconds         int,
  departure_delay_quality         string,
  departure_exclusion_reason      string,
  departure_usable_for_real_delay boolean,
  delay_quality                   string,
  delay_exclusion_reason          string,
  source_run_id                   string,
  source_md5                      string
)
PARTITIONED BY (day(operating_date))
LOCATION '{silver_location}'
TBLPROPERTIES (
  'table_type' = 'ICEBERG',
  'format' = 'parquet',
  'write_compression' = 'zstd'
)
