# One-off historical backfill of municipality weather from the Open-Meteo
# archive API. Open-Meteo's free tier allows 10,000 calls per day (600 per
# minute), and one location counts as one call per two weeks of data, so the
# history is loaded one calendar month per run with a wait between months
# (input interval_hours, default 24) and between batches. Started manually,
# never scheduled. Input:
#   {"since": "2025-08-01", "until": "2026-11-21", "point_snapshot": "points-v1"}
# Optional: "batch_size" (default 50), "interval_hours" (default 24).
# Restarting with the same input skips months that are already completed.
resource "aws_sfn_state_machine" "weather_backfill" {
  count    = var.lambda_image_uri == null ? 0 : 1
  name     = "${var.project_name}-${var.environment}-weather-backfill"
  role_arn = aws_iam_role.step_functions[0].arn

  definition = jsonencode({
    Comment = "Backfill municipality weather month by month within the Open-Meteo limits."
    # 16 months with a day between them; generous upper bound
    TimeoutSeconds = 3888000
    StartAt        = "PlanMonths"
    States = {
      PlanMonths = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.loader[0].arn
          Payload = {
            action           = "plan_weather_backfill"
            "input.$"        = "$"
            "execution_id.$" = "$$.Execution.Name"
          }
        }
        OutputPath = "$.Payload"
        Retry = [{
          ErrorEquals     = local.lambda_service_errors
          IntervalSeconds = 2
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        Next = "LoadMonths"
      }
      LoadMonths = {
        Type           = "Map"
        ItemsPath      = "$.items"
        MaxConcurrency = 1
        ItemProcessor = {
          ProcessorConfig = {
            Mode = "INLINE"
          }
          StartAt = "WaitBeforeMonth"
          States = {
            WaitBeforeMonth = {
              Type        = "Wait"
              SecondsPath = "$.wait_seconds"
              Next        = "InvokeBatch"
            }
            InvokeBatch = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                FunctionName = aws_lambda_function.loader[0].arn
                Payload = {
                  "source.$"           = "$.source"
                  "run_id.$"           = "$.run_id"
                  "execution_id.$"     = "$.execution_id"
                  "observation_date.$" = "$.observation_date"
                  "end_date.$"         = "$.end_date"
                  "point_snapshot.$"   = "$.point_snapshot"
                  "batch.$"            = "$.batch"
                  "batch_size.$"       = "$.batch_size"
                }
              }
              ResultSelector = {
                "next_batch.$" = "$.Payload.next_batch"
              }
              ResultPath = "$.lambda"
              Retry = [
                {
                  ErrorEquals     = local.lambda_service_errors
                  IntervalSeconds = 2
                  MaxAttempts     = 3
                  BackoffRate     = 2
                },
                {
                  # HTTP 429 or a slow archive response: back off for minutes
                  ErrorEquals     = ["States.TaskFailed"]
                  IntervalSeconds = 300
                  MaxAttempts     = 3
                  BackoffRate     = 2
                }
              ]
              Next = "HasNextBatch"
            }
            HasNextBatch = {
              Type = "Choice"
              Choices = [{
                And = [
                  {
                    Variable  = "$.lambda.next_batch"
                    IsPresent = true
                  },
                  {
                    Variable = "$.lambda.next_batch"
                    IsNull   = false
                  }
                ]
                Next = "PrepareNextBatch"
              }]
              Default = "FinalizeMonth"
            }
            PrepareNextBatch = {
              Type = "Pass"
              Parameters = {
                "source.$"           = "$.source"
                "run_id.$"           = "$.run_id"
                "execution_id.$"     = "$.execution_id"
                "observation_date.$" = "$.observation_date"
                "end_date.$"         = "$.end_date"
                "point_snapshot.$"   = "$.point_snapshot"
                "batch.$"            = "$.lambda.next_batch"
                "batch_size.$"       = "$.batch_size"
              }
              Next = "WaitBetweenBatches"
            }
            WaitBetweenBatches = {
              Type    = "Wait"
              Seconds = var.weather_backfill_batch_wait_seconds
              Next    = "InvokeBatch"
            }
            FinalizeMonth = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                FunctionName = aws_lambda_function.loader[0].arn
                Payload = {
                  action               = "finalize"
                  "source.$"           = "$.source"
                  "run_id.$"           = "$.run_id"
                  "observation_date.$" = "$.observation_date"
                  "end_date.$"         = "$.end_date"
                  "execution_id.$"     = "$.execution_id"
                  "point_snapshot.$"   = "$.point_snapshot"
                }
              }
              ResultSelector = {
                "status.$" = "$.Payload.status"
                "run_id.$" = "$.Payload.run_id"
              }
              Retry = [{
                ErrorEquals     = local.lambda_service_errors
                IntervalSeconds = 2
                MaxAttempts     = 3
                BackoffRate     = 2
              }]
              Next = "MonthCompleted"
            }
            MonthCompleted = {
              Type = "Choice"
              Choices = [{
                Variable     = "$.status"
                StringEquals = "completed"
                Next         = "MonthDone"
              }]
              Default = "MonthIncomplete"
            }
            MonthDone = {
              Type = "Succeed"
            }
            MonthIncomplete = {
              Type  = "Fail"
              Error = "WeatherMonthIncomplete"
              Cause = "The final manifest of a backfill month is not completed."
            }
          }
        }
        # The manifests in S3 are the record of what was loaded.
        ResultPath = null
        End        = true
      }
    }
  })

  tags = {
    Component = "orchestration"
  }
}
