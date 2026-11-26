# Silver layer: typed Ist-Daten in an Iceberg table, built with Athena.
#
# Terraform owns the Glue database and the permissions. The Iceberg table
# itself is created by the Lambda with Athena DDL (src/silver/sql/
# istdaten_create.sql, CREATE TABLE IF NOT EXISTS), because Athena sets up the
# Iceberg metadata and the partition spec; the Glue API does not.
#
# The silver-istdaten state machine plans the days whose Silver data is missing
# or built from an older raw run and rebuilds each day (DELETE + INSERT, so a
# rebuild is idempotent). It runs daily after the Ist-Daten sync and can be
# started manually, e.g. {"since": "2025-08-01", "until": "2025-08-31"} or
# {"force": true, "since": "...", "until": "..."} to rebuild after an SQL change.

data "aws_caller_identity" "current" {}

locals {
  glue_catalog_arn = "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog"
  glue_database_arns = [
    aws_glue_catalog_database.raw.arn,
    aws_glue_catalog_database.silver.arn,
  ]
  glue_table_arns = [
    "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.raw.name}/*",
    "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.silver.name}/*",
  ]
}

resource "aws_glue_catalog_database" "silver" {
  name        = "${local.catalog_prefix}_silver"
  description = "Silver layer of the ${var.environment} data lake: typed, cleaned Iceberg tables built from the raw files."
}

# The Lambda runs the Silver statements with Athena, which uses the caller's
# permissions for Glue and S3.
data "aws_iam_policy_document" "lambda_silver" {
  statement {
    sid    = "RunAthenaInWorkgroup"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
    ]
    resources = [aws_athena_workgroup.main.arn]
  }

  statement {
    sid    = "ReadAndWriteCatalog"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:CreateTable",
      "glue:UpdateTable",
    ]
    resources = concat([local.glue_catalog_arn], local.glue_database_arns, local.glue_table_arns)
  }

  statement {
    sid       = "BucketLocation"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [aws_s3_bucket.data_lake.arn]
  }

  statement {
    sid       = "ListSilverAndResults"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data_lake.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["silver/*", "${local.athena_results_prefix}*"]
    }
  }

  statement {
    sid    = "WriteSilverAndResults"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/silver/*",
      "${aws_s3_bucket.data_lake.arn}/${local.athena_results_prefix}*",
    ]
  }
}

resource "aws_iam_role_policy" "lambda_silver" {
  name   = "silver-athena"
  role   = aws_iam_role.lambda_runtime.id
  policy = data.aws_iam_policy_document.lambda_silver.json
}

resource "aws_sfn_state_machine" "silver_istdaten" {
  count    = var.lambda_image_uri == null ? 0 : 1
  name     = "${var.project_name}-${var.environment}-silver-istdaten"
  role_arn = aws_iam_role.step_functions[0].arn

  definition = jsonencode({
    Comment        = "Rebuild missing or outdated days of the Silver Ist-Daten table."
    TimeoutSeconds = 43200
    StartAt        = "PlanDays"
    States = {
      PlanDays = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.loader[0].arn
          Payload = {
            action    = "plan_silver_istdaten"
            "input.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Retry = [{
          ErrorEquals     = local.lambda_service_errors
          IntervalSeconds = 2
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        Next = "BuildDays"
      }
      BuildDays = {
        Type           = "Map"
        ItemsPath      = "$.items"
        MaxConcurrency = var.silver_max_concurrency
        ItemSelector = {
          action            = "build_silver_istdaten"
          "operating_day.$" = "$$.Map.Item.Value"
        }
        ItemProcessor = {
          ProcessorConfig = {
            Mode = "INLINE"
          }
          StartAt = "BuildDay"
          States = {
            BuildDay = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                FunctionName = aws_lambda_function.loader[0].arn
                "Payload.$"  = "$"
              }
              OutputPath = "$.Payload"
              Retry = [
                {
                  ErrorEquals     = local.lambda_service_errors
                  IntervalSeconds = 2
                  MaxAttempts     = 3
                  BackoffRate     = 2
                },
                {
                  # Concurrent Iceberg commits can conflict; a rebuild is idempotent.
                  ErrorEquals     = ["States.TaskFailed"]
                  IntervalSeconds = 30
                  MaxAttempts     = 3
                  BackoffRate     = 2
                }
              ]
              End = true
            }
          }
        }
        # The build markers in S3 are the record of what was built.
        ResultPath = null
        End        = true
      }
    }
  })

  tags = {
    Component = "orchestration"
  }
}
