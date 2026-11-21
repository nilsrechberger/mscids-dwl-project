locals {
  lambda_service_errors = [
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
  ]
}

# Plans the Ist-Daten v2 days that are missing or were replaced in the CKAN
# catalogue, loads each of them with one Lambda invocation, and fails the
# execution when the newest published file is older than the allowed age.
# The first execution in a fresh bucket therefore backfills the whole CKAN
# window (about 50 days). Optional execution input: {"since": "YYYY-MM-DD",
# "max_days": 10}.
resource "aws_sfn_state_machine" "istdaten_sync" {
  count    = var.lambda_image_uri == null ? 0 : 1
  name     = "${var.project_name}-${var.environment}-istdaten-sync"
  role_arn = aws_iam_role.step_functions[0].arn

  definition = jsonencode({
    Comment        = "Sync raw/istdaten_v2 with the opentransportdata CKAN catalogue."
    TimeoutSeconds = 21600
    StartAt        = "PlanSync"
    States = {
      PlanSync = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.loader[0].arn
          Payload = {
            action    = "plan_istdaten_sync"
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
        ItemsPath      = "$.operating_days"
        MaxConcurrency = var.istdaten_sync_max_concurrency
        ItemSelector = {
          source            = "istdaten_v2"
          "operating_day.$" = "$$.Map.Item.Value"
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
        ResultPath = "$.loaded"
        Next       = "CheckFreshness"
      }
      CheckFreshness = {
        Type = "Choice"
        Choices = [{
          Variable      = "$.stale"
          BooleanEquals = true
          Next          = "SourceStale"
        }]
        Default = "Succeeded"
      }
      SourceStale = {
        Type  = "Fail"
        Error = "IstdatenSourceStale"
        Cause = "The newest Ist-Daten v2 file in the CKAN catalogue is older than ISTDATEN_V2_MAX_AGE_DAYS."
      }
      Succeeded = {
        Type = "Succeed"
      }
    }
  })

  tags = {
    Component = "orchestration"
  }
}
