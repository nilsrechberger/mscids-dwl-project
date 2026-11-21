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
  default     = "eu-central-1"
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
  description = "Lambda instruction set architecture used by the container image."
  type        = string
  default     = "arm64"
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

variable "alarm_email" {
  description = "E-mail address for pipeline alarms and budget notifications. Leave null to create the SNS topic without a subscription."
  type        = string
  default     = null
  nullable    = true
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget in USD. Notifications go to alarm_email at 80 % actual and 100 % forecasted spend."
  type        = number
  default     = 100
}
