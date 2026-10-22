# AWS-managed cache policy: cache by default, compress, and respect the origin's headers.
data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# ---- apps-docs (static site, build output in dist) ----
resource "aws_s3_bucket" "site_apps_docs" {
  bucket_prefix = substr("${local.name}-site-apps-docs-", 0, 37)
}

resource "aws_s3_bucket_public_access_block" "site_apps_docs" {
  bucket                  = aws_s3_bucket.site_apps_docs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site_apps_docs" {
  bucket = aws_s3_bucket.site_apps_docs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "site_apps_docs" {
  bucket = aws_s3_bucket.site_apps_docs.id

  versioning_configuration {
    status = "Enabled"
  }
}

# CloudFront signs its requests to S3, so the bucket stays private.
resource "aws_cloudfront_origin_access_control" "site_apps_docs" {
  name                              = substr("${local.name}-apps-docs", 0, 64)
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site_apps_docs" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = ["apps-docs.${var.domain_name}"]
  price_class         = "PriceClass_All"

  origin {
    domain_name              = aws_s3_bucket.site_apps_docs.bucket_regional_domain_name
    origin_id                = "site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site_apps_docs.id
  }

  default_cache_behavior {
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # The certificate must be in us-east-1 for CloudFront, whatever region this stack uses.
  viewer_certificate {
    acm_certificate_arn      = var.site_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

data "aws_iam_policy_document" "site_apps_docs" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site_apps_docs.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    # Only this distribution may read the bucket.
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site_apps_docs.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site_apps_docs" {
  bucket = aws_s3_bucket.site_apps_docs.id
  policy = data.aws_iam_policy_document.site_apps_docs.json

  depends_on = [aws_s3_bucket_public_access_block.site_apps_docs]
}

# ---- apps-marketing (static site, build output in out) ----
resource "aws_s3_bucket" "site_apps_marketing" {
  bucket_prefix = substr("${local.name}-site-apps-marketing-", 0, 37)
}

resource "aws_s3_bucket_public_access_block" "site_apps_marketing" {
  bucket                  = aws_s3_bucket.site_apps_marketing.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site_apps_marketing" {
  bucket = aws_s3_bucket.site_apps_marketing.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "site_apps_marketing" {
  bucket = aws_s3_bucket.site_apps_marketing.id

  versioning_configuration {
    status = "Enabled"
  }
}

# CloudFront signs its requests to S3, so the bucket stays private.
resource "aws_cloudfront_origin_access_control" "site_apps_marketing" {
  name                              = substr("${local.name}-apps-marketing", 0, 64)
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site_apps_marketing" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = ["apps-marketing.${var.domain_name}"]
  price_class         = "PriceClass_All"

  origin {
    domain_name              = aws_s3_bucket.site_apps_marketing.bucket_regional_domain_name
    origin_id                = "site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site_apps_marketing.id
  }

  default_cache_behavior {
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # The certificate must be in us-east-1 for CloudFront, whatever region this stack uses.
  viewer_certificate {
    acm_certificate_arn      = var.site_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

data "aws_iam_policy_document" "site_apps_marketing" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site_apps_marketing.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    # Only this distribution may read the bucket.
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site_apps_marketing.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site_apps_marketing" {
  bucket = aws_s3_bucket.site_apps_marketing.id
  policy = data.aws_iam_policy_document.site_apps_marketing.json

  depends_on = [aws_s3_bucket_public_access_block.site_apps_marketing]
}

# ---- apps-spa (static site, build output in dist) ----
resource "aws_s3_bucket" "site_apps_spa" {
  bucket_prefix = substr("${local.name}-site-apps-spa-", 0, 37)
}

resource "aws_s3_bucket_public_access_block" "site_apps_spa" {
  bucket                  = aws_s3_bucket.site_apps_spa.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site_apps_spa" {
  bucket = aws_s3_bucket.site_apps_spa.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "site_apps_spa" {
  bucket = aws_s3_bucket.site_apps_spa.id

  versioning_configuration {
    status = "Enabled"
  }
}

# CloudFront signs its requests to S3, so the bucket stays private.
resource "aws_cloudfront_origin_access_control" "site_apps_spa" {
  name                              = substr("${local.name}-apps-spa", 0, 64)
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site_apps_spa" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = ["apps-spa.${var.domain_name}"]
  price_class         = "PriceClass_All"

  origin {
    domain_name              = aws_s3_bucket.site_apps_spa.bucket_regional_domain_name
    origin_id                = "site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site_apps_spa.id
  }

  default_cache_behavior {
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
  }

  # Single-page app: unknown paths are client-side routes, so answer them with the app shell.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # The certificate must be in us-east-1 for CloudFront, whatever region this stack uses.
  viewer_certificate {
    acm_certificate_arn      = var.site_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

data "aws_iam_policy_document" "site_apps_spa" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site_apps_spa.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    # Only this distribution may read the bucket.
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site_apps_spa.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site_apps_spa" {
  bucket = aws_s3_bucket.site_apps_spa.id
  policy = data.aws_iam_policy_document.site_apps_spa.json

  depends_on = [aws_s3_bucket_public_access_block.site_apps_spa]
}
