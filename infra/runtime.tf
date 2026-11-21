resource "aws_ecr_repository" "loader" {
  name                 = "${var.project_name}-${var.environment}-loader"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Component = "runtime"
  }
}

resource "aws_cloudwatch_log_group" "loader" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-loader"
  retention_in_days = var.lambda_log_retention_days
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "lambda_runtime" {
  name               = "${var.project_name}-${var.environment}-lambda-runtime"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_runtime.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_s3" {
  role       = aws_iam_role.lambda_runtime.name
  policy_arn = aws_iam_policy.loader_s3.arn
}

locals {
  lambda_environment = merge(
    var.lambda_environment,
    {
      S3_BUCKET = var.data_bucket_name
    },
    var.municipality_weather_points_uri == null ? {} : {
      MUNICIPALITY_WEATHER_POINTS = var.municipality_weather_points_uri
    },
    var.ckan_api_key_secret_arn == null ? {} : {
      CKAN_API_KEY_SECRET_ID = var.ckan_api_key_secret_arn
    }
  )
}

data "aws_iam_policy_document" "lambda_read_ckan_secret" {
  count = var.ckan_api_key_secret_arn == null ? 0 : 1

  statement {
    sid       = "ReadCkanApiKey"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.ckan_api_key_secret_arn]
  }
}

resource "aws_iam_role_policy" "lambda_read_ckan_secret" {
  count  = var.ckan_api_key_secret_arn == null ? 0 : 1
  name   = "read-ckan-api-key"
  role   = aws_iam_role.lambda_runtime.id
  policy = data.aws_iam_policy_document.lambda_read_ckan_secret[0].json
}

resource "aws_lambda_function" "loader" {
  count = var.lambda_image_uri == null ? 0 : 1

  function_name = "${var.project_name}-${var.environment}-loader"
  role          = aws_iam_role.lambda_runtime.arn
  package_type  = "Image"
  image_uri     = var.lambda_image_uri
  architectures = [var.lambda_architecture]
  memory_size   = var.lambda_memory_size
  timeout       = var.lambda_timeout_seconds
  publish       = true

  image_config {
    command = ["src.run.handler"]
  }

  environment {
    variables = local.lambda_environment
  }

  depends_on = [aws_cloudwatch_log_group.loader]

  tags = {
    Component = "runtime"
  }
}

data "aws_iam_policy_document" "step_functions_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "step_functions" {
  count              = var.lambda_image_uri == null ? 0 : 1
  name               = "${var.project_name}-${var.environment}-step-functions"
  assume_role_policy = data.aws_iam_policy_document.step_functions_assume_role.json
}

data "aws_iam_policy_document" "step_functions_invoke_lambda" {
  count = var.lambda_image_uri == null ? 0 : 1

  statement {
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.loader[0].arn]
  }
}

resource "aws_iam_role_policy" "step_functions_invoke_lambda" {
  count  = var.lambda_image_uri == null ? 0 : 1
  name   = "invoke-loader"
  role   = aws_iam_role.step_functions[0].id
  policy = data.aws_iam_policy_document.step_functions_invoke_lambda[0].json
}

resource "aws_sfn_state_machine" "loader" {
  count    = var.lambda_image_uri == null ? 0 : 1
  name     = "${var.project_name}-${var.environment}-loader"
  role_arn = aws_iam_role.step_functions[0].arn

  definition = jsonencode({
    Comment = "Loop Lambda batches and finalize the deterministic S3 manifest."
    StartAt = "HasObservationDate"
    States = {
      HasObservationDate = {
        Type = "Choice"
        Choices = [{
          And = [
            {
              Variable  = "$.observation_date"
              IsPresent = true
            },
            {
              Variable = "$.observation_date"
              IsNull   = false
            }
          ]
          Next = "InvokeBatch"
        }]
        Default = "PrepareDailyInput"
      }
      PrepareDailyInput = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.loader[0].arn
          Payload = {
            action                   = "prepare_daily"
            "source.$"               = "$.source"
            "execution_id.$"         = "$$.Execution.Name"
            "execution_start_date.$" = "States.ArrayGetItem(States.StringSplit($$.Execution.StartTime, 'T'), 0)"
            "point_snapshot.$"       = "$.point_snapshot"
            "batch.$"                = "$.batch"
            "batch_size.$"           = "$.batch_size"
          }
        }
        OutputPath = "$.Payload"
        Next       = "InvokeBatch"
      }
      InvokeBatch = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.loader[0].arn
          "Payload.$"  = "$"
        }
        ResultSelector = {
          "result.$" = "$.Payload"
        }
        ResultPath = "$.lambda"
        Retry = [{
          ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
          IntervalSeconds = 2
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        Next = "HasNextBatch"
      }
      HasNextBatch = {
        Type = "Choice"
        Choices = [{
          And = [
            {
              Variable  = "$.lambda.result.next_batch"
              IsPresent = true
            },
            {
              Variable = "$.lambda.result.next_batch"
              IsNull   = false
            }
          ]
          Next = "PrepareNextBatch"
        }]
        Default = "HasRunContext"
      }
      PrepareNextBatch = {
        Type = "Pass"
        Parameters = {
          "source.$"           = "$.source"
          "run_id.$"           = "$.run_id"
          "execution_id.$"     = "$.execution_id"
          "observation_date.$" = "$.observation_date"
          "point_snapshot.$"   = "$.point_snapshot"
          "batch.$"            = "$.lambda.result.next_batch"
          "batch_size.$"       = "$.batch_size"
        }
        Next = "InvokeBatch"
      }
      HasRunContext = {
        Type = "Choice"
        Choices = [{
          Variable  = "$.run_id"
          IsPresent = true
          Next      = "FinalizeManifest"
        }]
        Default = "Succeeded"
      }
      FinalizeManifest = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.loader[0].arn
          Payload = {
            action               = "finalize"
            "source.$"           = "$.source"
            "run_id.$"           = "$.run_id"
            "observation_date.$" = "$.observation_date"
            "execution_id.$"     = "$.execution_id"
            "point_snapshot.$"   = "$.point_snapshot"
          }
        }
        OutputPath = "$.Payload"
        Next       = "Succeeded"
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
