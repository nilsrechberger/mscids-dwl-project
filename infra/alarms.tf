resource "aws_sns_topic" "alarms" {
  name = "${var.project_name}-${var.environment}-alarms"

  tags = {
    Component = "monitoring"
  }
}

# AWS sends a confirmation e-mail to each address; alarms are delivered only
# after the subscription has been confirmed by clicking the link.
resource "aws_sns_topic_subscription" "alarm_email" {
  for_each = toset(var.alarm_emails)

  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  count = var.lambda_image_uri == null ? 0 : 1

  alarm_name          = "${var.project_name}-${var.environment}-loader-errors"
  alarm_description   = "The loader Lambda reported at least one error."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.loader[0].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

locals {
  monitored_state_machines = var.lambda_image_uri == null ? {} : {
    loader        = aws_sfn_state_machine.loader[0].arn
    istdaten-sync = aws_sfn_state_machine.istdaten_sync[0].arn
  }
  state_machine_failure_metrics = ["ExecutionsFailed", "ExecutionsTimedOut", "ExecutionsAborted"]
  state_machine_alarms = {
    for pair in setproduct(keys(local.monitored_state_machines), local.state_machine_failure_metrics) :
    "${pair[0]}-${pair[1]}" => {
      state_machine = pair[0]
      metric        = pair[1]
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "state_machine_failures" {
  for_each = local.state_machine_alarms

  alarm_name          = "${var.project_name}-${var.environment}-${each.key}"
  alarm_description   = "Step Functions ${each.value.state_machine}: ${each.value.metric} > 0."
  namespace           = "AWS/States"
  metric_name         = each.value.metric
  dimensions          = { StateMachineArn = local.monitored_state_machines[each.value.state_machine] }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_budgets_budget" "monthly" {
  count = length(var.alarm_emails) == 0 ? 0 : 1

  name         = "${var.project_name}-${var.environment}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alarm_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.alarm_emails
  }
}
