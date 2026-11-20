output "data_lake_bucket_name" {
  description = "Name of the data-lake S3 bucket."
  value       = aws_s3_bucket.data_lake.bucket
}

output "data_lake_bucket_arn" {
  description = "ARN of the data-lake S3 bucket."
  value       = aws_s3_bucket.data_lake.arn
}

output "data_lake_prefixes" {
  description = "Logical data-lake layer prefixes created by Terraform."
  value       = local.data_lake_prefixes
}

output "loader_s3_policy_arn" {
  description = "Managed policy ARN to attach to the future loader execution role."
  value       = aws_iam_policy.loader_s3.arn
}

output "terraform_state_bucket_name" {
  description = "Optional Terraform state bucket name when state bucket creation is enabled."
  value       = var.create_state_bucket ? aws_s3_bucket.terraform_state[0].bucket : null
}

output "loader_ecr_repository_url" {
  description = "ECR repository URL for the Lambda container image."
  value       = aws_ecr_repository.loader.repository_url
}

output "loader_lambda_function_name" {
  description = "Lambda function name when an image URI is configured."
  value       = try(aws_lambda_function.loader[0].function_name, null)
}

output "loader_lambda_function_arn" {
  description = "Lambda function ARN when an image URI is configured."
  value       = try(aws_lambda_function.loader[0].arn, null)
}

output "loader_state_machine_arn" {
  description = "Step Functions state machine ARN when an image URI is configured."
  value       = try(aws_sfn_state_machine.loader[0].arn, null)
}
