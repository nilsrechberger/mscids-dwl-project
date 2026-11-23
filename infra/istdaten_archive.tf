# One-off historical import of Ist-Daten v2 from the monthly ZIP archives on
# archive.opentransportdata.swiss. PlanImport reads the ZIP central directories
# and lists every day in the range that has no loaded version yet; LoadDays
# streams each day out of its ZIP into the same raw layout as the CKAN sync.
# Started manually, never scheduled. Input:
#   {"since": "2025-08-01", "until": "2026-10-31", "max_days": 31}
# (max_days is optional and limits the run, oldest days first).
resource "aws_sfn_state_machine" "istdaten_archive" {
  count    = var.lambda_image_uri == null ? 0 : 1
  name     = "${var.project_name}-${var.environment}-istdaten-archive"
  role_arn = aws_iam_role.step_functions[0].arn

  definition = jsonencode({
    Comment        = "Import historical Ist-Daten v2 days from the monthly ZIP archives."
    TimeoutSeconds = 43200
    StartAt        = "PlanImport"
    States = {
      PlanImport = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.loader[0].arn
          Payload = {
            action    = "plan_istdaten_archive"
            "input.$" = "$"
          }
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
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 60
            MaxAttempts     = 2
            BackoffRate     = 2
          }
        ]
        Next = "LoadDays"
      }
      LoadDays = {
        Type           = "Map"
        ItemsPath      = "$.items"
        MaxConcurrency = var.istdaten_archive_max_concurrency
        ItemSelector = {
          source            = "istdaten_v2"
          "operating_day.$" = "$$.Map.Item.Value.operating_day"
          "archive_month.$" = "$$.Map.Item.Value.archive_month"
        }
        ItemProcessor = {
          ProcessorConfig = {
            Mode = "INLINE"
          }
          StartAt = "LoadDay"
          States = {
            LoadDay = {
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
                  ErrorEquals     = ["States.TaskFailed"]
                  IntervalSeconds = 120
                  MaxAttempts     = 2
                  BackoffRate     = 2
                }
              ]
              End = true
            }
          }
        }
        # Hundreds of per-day results would approach the 256 KB state limit;
        # the manifests in S3 are the record of what was loaded.
        ResultPath = null
        End        = true
      }
    }
  })

  tags = {
    Component = "orchestration"
  }
}
