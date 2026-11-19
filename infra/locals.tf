locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  data_lake_prefixes = [
    "raw/",
    "reference/",
    "silver/",
    "gold/",
  ]
}
