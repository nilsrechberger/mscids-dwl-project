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
