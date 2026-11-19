data "aws_iam_policy_document" "loader_s3" {
  statement {
    sid    = "ListRelevantPrefixes"
    effect = "Allow"

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data_lake.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "raw/municipality/*",
        "raw/municipality_weather/*",
        "reference/*",
      ]
    }
  }

  statement {
    sid    = "ReadReferenceAndMunicipalityInputs"
    effect = "Allow"

    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/reference/*",
      "${aws_s3_bucket.data_lake.arn}/raw/municipality/*",
    ]
  }

  statement {
    sid    = "WriteRawIngestionObjects"
    effect = "Allow"

    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/raw/*",
    ]
  }
}

resource "aws_iam_policy" "loader_s3" {
  name        = "${var.project_name}-${var.environment}-loader-s3"
  description = "Least-privilege S3 access for the data-lake ingestion loader"
  policy      = data.aws_iam_policy_document.loader_s3.json
}
