# Glue Data Catalog and Athena workgroup for querying the data lake.
#
# The raw tables describe the files exactly as the loaders store them. A raw
# day folder can contain more than the current data file (the run manifest,
# older runs of a replaced file and, in the test bucket, files of the earlier
# permalink loader). Queries that need one clean version per day therefore
# filter on the "$path" pseudo-column with the data_key from the run manifest;
# see sql/README.md.

locals {
  catalog_prefix         = replace("${var.project_name}_${var.environment}", "-", "_")
  athena_results_prefix  = "athena-results/"
  istdaten_v2_raw_prefix = "s3://${aws_s3_bucket.data_lake.bucket}/raw/istdaten_v2/"

  # Column order of the Ist-Daten v2 CSV header (BETRIEBSTAG;FAHRT_BEZEICHNER;...).
  istdaten_v2_columns = [
    "betriebstag",
    "fahrt_bezeichner",
    "betreiber_id",
    "betreiber_abk",
    "betreiber_name",
    "produkt_id",
    "linien_id",
    "linien_text",
    "umlauf_id",
    "verkehrsmittel_text",
    "zusatzfahrt_tf",
    "faellt_aus_tf",
    "bpuic",
    "haltestellen_name",
    "ankunftszeit",
    "an_prognose",
    "an_prognose_status",
    "abfahrtszeit",
    "ab_prognose",
    "ab_prognose_status",
    "durchfahrt_tf",
    "sloid",
  ]
}

resource "aws_glue_catalog_database" "raw" {
  name        = "${local.catalog_prefix}_raw"
  description = "Raw (bronze) layer of the ${var.environment} data lake: files as fetched, no transformation."
}

resource "aws_glue_catalog_table" "istdaten_v2_raw" {
  database_name = aws_glue_catalog_database.raw.name
  name          = "istdaten_v2"
  description   = "Ist-Daten v2 daily CSV files (all columns as strings). Filter on \"$path\" with the manifest data_key for one clean version per day."
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"              = "csv"
    "skip.header.line.count"      = "1"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.range"         = "2024-01-01,NOW"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "storage.location.template"   = "${local.istdaten_v2_raw_prefix}dt=$${dt}/"
  }

  partition_keys {
    name    = "dt"
    type    = "string"
    comment = "Operating day (BETRIEBSTAG) as yyyy-MM-dd"
  }

  storage_descriptor {
    location      = local.istdaten_v2_raw_prefix
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "istdaten-v2-csv"
      serialization_library = "org.apache.hadoop.hive.serde2.OpenCSVSerde"
      parameters = {
        "separatorChar" = ";"
        "quoteChar"     = "\""
        "escapeChar"    = "\\"
      }
    }

    dynamic "columns" {
      for_each = local.istdaten_v2_columns
      content {
        name = columns.value
        type = "string"
      }
    }
  }
}

resource "aws_athena_workgroup" "main" {
  name          = "${var.project_name}-${var.environment}"
  description   = "Athena queries on the ${var.environment} data lake. Results expire after ${var.athena_results_expiration_days} days."
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data_lake.bucket}/${local.athena_results_prefix}"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
