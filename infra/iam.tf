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
        "raw/istdaten_v2/*",
        "raw/municipality/*",
        "raw/municipality_weather/*",
        "raw/service_points/*",
        "reference/*",
      ]
    }
  }

  statement {
    sid    = "ReadReferenceAndMunicipalityInputs"
    effect = "Allow"

    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/raw/istdaten_v2/*",
      "${aws_s3_bucket.data_lake.arn}/reference/*",
      "${aws_s3_bucket.data_lake.arn}/raw/municipality/*",
      "${aws_s3_bucket.data_lake.arn}/raw/municipality_weather/*",
      "${aws_s3_bucket.data_lake.arn}/raw/service_points/*",
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
