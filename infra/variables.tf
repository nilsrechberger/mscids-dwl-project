variable "project_name" {
  description = "Short project identifier used in resource names and tags."
  type        = string
  default     = "mscids-dwl"
}

variable "environment" {
  description = "Deployment environment, for example test or prod."
  type        = string
  default     = "test"
}

variable "aws_region" {
  description = "AWS region for the data lake."
  type        = string
  default     = "us-east-1"
}

variable "data_bucket_name" {
  description = "Globally unique S3 bucket name for the data lake."
  type        = string
}

variable "state_bucket_name" {
  description = "Globally unique S3 bucket name for Terraform state."
  type        = string
  default     = null
  nullable    = true
}

variable "create_state_bucket" {
  description = "Create the separately bootstrapped Terraform state bucket."
  type        = bool
  default     = false
}

variable "enable_versioning" {
  description = "Enable S3 object versioning on managed buckets."
  type        = bool
  default     = true
}

variable "raw_noncurrent_expiration_days" {
  description = "Days after which noncurrent object versions may expire."
  type        = number
  default     = 90
}

variable "lambda_image_uri" {
  description = "Fully qualified ECR image URI. Leave null to provision only the ECR repository and IAM resources."
  type        = string
  default     = null
  nullable    = true
}

variable "lambda_architecture" {
  description = "Lambda instruction set architecture. Must match the image platform (x86_64 = docker --platform linux/amd64, arm64 = linux/arm64)."
  type        = string
  default     = "x86_64"
  validation {
    condition     = contains(["arm64", "x86_64"], var.lambda_architecture)
    error_message = "lambda_architecture must be arm64 or x86_64."
  }
}

variable "lambda_memory_size" {
  description = "Lambda memory in MB."
  type        = number
  default     = 1024
}

variable "lambda_timeout_seconds" {
  description = "Maximum Lambda execution time."
  type        = number
  default     = 900
}

variable "lambda_log_retention_days" {
  description = "CloudWatch log retention for the runtime Lambda."
  type        = number
  default     = 30
}

variable "lambda_environment" {
  description = "Additional non-secret environment variables for the Lambda container. Do not put API tokens here."
  type        = map(string)
  default     = {}
}

variable "municipality_weather_points_uri" {
  description = "S3 URI of the immutable municipality_weather reference snapshot, for example s3://bucket/reference/municipality_weather/points-v1.csv."
  type        = string
  default     = null
  nullable    = true
}

variable "eventbridge_schedule_enabled" {
  description = "Enable the daily EventBridge schedules. Keep false until the schedule has been reviewed and observed in the test environment."
  type        = bool
  default     = false
}

variable "eventbridge_schedule_expression" {
  description = "UTC EventBridge schedule expression for the daily ingestion trigger."
  type        = string
  default     = "cron(0 6 * * ? *)"
}

variable "ckan_api_key_secret_arn" {
  description = "ARN of the manually created Secrets Manager secret holding the opentransportdata CKAN API key. The key value itself never goes into Terraform."
  type        = string
  default     = null
  nullable    = true
}

variable "istdaten_sync_max_concurrency" {
  description = "Maximum number of Ist-Daten v2 days loaded in parallel by the sync state machine."
  type        = number
  default     = 2
  validation {
    condition     = var.istdaten_sync_max_concurrency >= 1 && var.istdaten_sync_max_concurrency <= 5
    error_message = "istdaten_sync_max_concurrency must be between 1 and 5."
  }
}

variable "istdaten_archive_max_concurrency" {
  description = "Maximum number of archive days imported in parallel by the istdaten-archive state machine."
  type        = number
  default     = 3
  validation {
    condition     = var.istdaten_archive_max_concurrency >= 1 && var.istdaten_archive_max_concurrency <= 10
    error_message = "istdaten_archive_max_concurrency must be between 1 and 10."
  }
}

variable "silver_max_concurrency" {
  description = "Maximum number of days the silver-istdaten state machine builds in parallel (Athena queries; Iceberg commits retry on conflicts)."
  type        = number
  default     = 3
  validation {
    condition     = var.silver_max_concurrency >= 1 && var.silver_max_concurrency <= 10
    error_message = "silver_max_concurrency must be between 1 and 10."
  }
}

variable "silver_schedule_expression" {
  description = "UTC EventBridge schedule for the daily Silver build; after the Ist-Daten sync (eventbridge_schedule_expression)."
  type        = string
  default     = "cron(0 8 * * ? *)"
}

variable "service_points_schedule_expression" {
  description = "UTC EventBridge schedule for the atlas service point load (stop to municipality reference)."
  type        = string
  default     = "cron(0 5 ? * MON *)"
}

variable "weather_backfill_batch_wait_seconds" {
  description = "Pause between two weather backfill batches. A batch of 50 points over one month counts as about 110 Open-Meteo calls; the free tier allows 600 per minute."
  type        = number
  default     = 15
  validation {
    condition     = var.weather_backfill_batch_wait_seconds >= 0 && var.weather_backfill_batch_wait_seconds <= 600
    error_message = "weather_backfill_batch_wait_seconds must be between 0 and 600."
  }
}

variable "alarm_emails" {
  description = "E-mail addresses for pipeline alarms and budget notifications (at most 10). Leave empty to create the SNS topic without subscriptions and without a budget."
  type        = list(string)
  default     = []
  validation {
    condition     = length(var.alarm_emails) <= 10 && alltrue([for email in var.alarm_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", email))])
    error_message = "alarm_emails must contain at most 10 valid e-mail addresses."
  }
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget in USD. Notifications go to alarm_emails at 80 % actual and 100 % forecasted spend."
  type        = number
  default     = 100
}

variable "athena_results_expiration_days" {
  description = "Days after which Athena query results under athena-results/ expire."
  type        = number
  default     = 30
}

variable "athena_bytes_scanned_cutoff" {
  description = "Maximum bytes one Athena query in the workgroup may scan (cost guard, minimum 10 MB). Default 50 GB, about 0.25 USD per query."
  type        = number
  default     = 53687091200
  validation {
    condition     = var.athena_bytes_scanned_cutoff >= 10485760
    error_message = "athena_bytes_scanned_cutoff must be at least 10 MB (10485760 bytes)."
  }
}
