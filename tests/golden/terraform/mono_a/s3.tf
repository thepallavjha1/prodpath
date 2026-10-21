# Bucket for root. The name is generated (prefix + suffix) because S3 names are global.
resource "aws_s3_bucket" "s3_root" {
  bucket_prefix = substr("${local.name}-root-", 0, 37)
}

resource "aws_s3_bucket_public_access_block" "s3_root" {
  bucket                  = aws_s3_bucket.s3_root.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "s3_root" {
  bucket = aws_s3_bucket.s3_root.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "s3_root" {
  bucket = aws_s3_bucket.s3_root.id

  versioning_configuration {
    status = "Enabled"
  }
}
