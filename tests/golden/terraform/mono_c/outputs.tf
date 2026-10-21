output "ecr_repository_urls" {
  description = "Repository URL per service id; push images here."
  value = {
    "apps-billing"  = aws_ecr_repository.apps_billing.repository_url
    "apps-gateway"  = aws_ecr_repository.apps_gateway.repository_url
    "apps-notifier" = aws_ecr_repository.apps_notifier.repository_url
    "apps-reports"  = aws_ecr_repository.apps_reports.repository_url
    "apps-users"    = aws_ecr_repository.apps_users.repository_url
    "apps-web"      = aws_ecr_repository.apps_web.repository_url
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
    "apps-billing" = [aws_secretsmanager_secret.apps_billing_database_url.name]
    "apps-gateway" = [aws_secretsmanager_secret.apps_gateway_billing_url.name, aws_secretsmanager_secret.apps_gateway_users_url.name]
  }
}

output "data_store_endpoints" {
  description = "Hostnames to put in your connection strings (stored in the secret slots, not here)."
  value = {
    "postgres" = aws_db_instance.postgres.address
    "redis"    = aws_elasticache_replication_group.redis.primary_endpoint_address
  }
}

output "rds_master_secret_arns" {
  description = "AWS-managed secrets holding each database's master credentials."
  value = {
    "postgres" = aws_db_instance.postgres.master_user_secret[0].secret_arn
  }
}
