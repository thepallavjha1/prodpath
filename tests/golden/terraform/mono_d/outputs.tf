output "ecr_repository_urls" {
  description = "Repository URL per service id; push images here."
  value = {
    "apps-api"       = aws_ecr_repository.apps_api.repository_url
    "apps-dashboard" = aws_ecr_repository.apps_dashboard.repository_url
  }
}

output "alb_dns_name" {
  description = "Point your DNS records (<service-id>.<domain_name>) at this name."
  value       = aws_lb.main.dns_name
}

output "github_actions_role_arn" {
  description = "Role for GitHub Actions to assume with OIDC (role-to-assume)."
  value       = aws_iam_role.github_actions.arn
}

output "secret_slots" {
  description = "Secrets Manager slots created empty. Set each value yourself, out of band."
  value = {
    "apps-api" = [aws_secretsmanager_secret.apps_api_database_url.name]
  }
}

output "data_store_endpoints" {
  description = "Hostnames to put in your connection strings (stored in the secret slots, not here)."
  value = {
    "postgres" = aws_db_instance.postgres.address
  }
}

output "rds_master_secret_arns" {
  description = "AWS-managed secrets holding each database's master credentials."
  value = {
    "postgres" = aws_db_instance.postgres.master_user_secret[0].secret_arn
  }
}

output "site_distributions" {
  description = "CloudFront distribution per static site. Point <service-id>.<domain_name> at the domain name."
  value = {
    "apps-docs" = {
      id          = aws_cloudfront_distribution.site_apps_docs.id
      domain_name = aws_cloudfront_distribution.site_apps_docs.domain_name
    }
    "apps-marketing" = {
      id          = aws_cloudfront_distribution.site_apps_marketing.id
      domain_name = aws_cloudfront_distribution.site_apps_marketing.domain_name
    }
    "apps-spa" = {
      id          = aws_cloudfront_distribution.site_apps_spa.id
      domain_name = aws_cloudfront_distribution.site_apps_spa.domain_name
    }
  }
}

output "site_buckets" {
  description = "Bucket per static site; upload the build output here."
  value = {
    "apps-docs"      = aws_s3_bucket.site_apps_docs.id
    "apps-marketing" = aws_s3_bucket.site_apps_marketing.id
    "apps-spa"       = aws_s3_bucket.site_apps_spa.id
  }
}
