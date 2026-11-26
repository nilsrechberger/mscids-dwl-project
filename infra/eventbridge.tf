locals {
  eventbridge_schedule_name_prefix = "${var.project_name}-${var.environment}-daily"
}

resource "aws_iam_role" "eventbridge_step_functions" {
  count = var.eventbridge_schedule_enabled && var.lambda_image_uri != null ? 1 : 0

  name = "${var.project_name}-${var.environment}-eventbridge-sfn"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "events.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_step_functions" {
  count = var.eventbridge_schedule_enabled && var.lambda_image_uri != null ? 1 : 0

  name = "start-loader-state-machine"
  role = aws_iam_role.eventbridge_step_functions[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "states:StartExecution"
      Resource = [
        aws_sfn_state_machine.loader[0].arn,
        aws_sfn_state_machine.istdaten_sync[0].arn,
        aws_sfn_state_machine.silver_istdaten[0].arn,
      ]
    }]
  })
}

resource "aws_cloudwatch_event_rule" "daily_istdaten_v2" {
  count = var.eventbridge_schedule_enabled && var.lambda_image_uri != null ? 1 : 0

  name                = "${local.eventbridge_schedule_name_prefix}-istdaten-v2"
  description         = "Daily Ist-Daten-v2 CKAN sync (missing and replaced days)."
  schedule_expression = var.eventbridge_schedule_expression
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "daily_istdaten_v2" {
  count = var.eventbridge_schedule_enabled && var.lambda_image_uri != null ? 1 : 0

  rule     = aws_cloudwatch_event_rule.daily_istdaten_v2[0].name
  arn      = aws_sfn_state_machine.istdaten_sync[0].arn
  role_arn = aws_iam_role.eventbridge_step_functions[0].arn
  input    = jsonencode({})
}

resource "aws_cloudwatch_event_rule" "daily_municipality_weather" {
  count = var.eventbridge_schedule_enabled && var.lambda_image_uri != null ? 1 : 0

  name                = "${local.eventbridge_schedule_name_prefix}-municipality-weather"
  description         = "Daily municipality weather Step Functions run."
  schedule_expression = var.eventbridge_schedule_expression
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "daily_municipality_weather" {
  count = var.eventbridge_schedule_enabled && var.lambda_image_uri != null ? 1 : 0

  rule     = aws_cloudwatch_event_rule.daily_municipality_weather[0].name
  arn      = aws_sfn_state_machine.loader[0].arn
  role_arn = aws_iam_role.eventbridge_step_functions[0].arn
  input = jsonencode({
    source         = "municipality_weather"
    batch          = 0
    batch_size     = 50
    point_snapshot = "points-v1"
  })
}

resource "aws_cloudwatch_event_rule" "daily_silver_istdaten" {
  count = var.eventbridge_schedule_enabled && var.lambda_image_uri != null ? 1 : 0

  name                = "${local.eventbridge_schedule_name_prefix}-silver-istdaten"
  description         = "Daily Silver Ist-Daten build (new and replaced days) after the CKAN sync."
  schedule_expression = var.silver_schedule_expression
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "daily_silver_istdaten" {
  count = var.eventbridge_schedule_enabled && var.lambda_image_uri != null ? 1 : 0

  rule     = aws_cloudwatch_event_rule.daily_silver_istdaten[0].name
  arn      = aws_sfn_state_machine.silver_istdaten[0].arn
  role_arn = aws_iam_role.eventbridge_step_functions[0].arn
  input    = jsonencode({})
}
