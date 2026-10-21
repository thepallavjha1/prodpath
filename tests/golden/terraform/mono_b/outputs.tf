output "ecr_repository_urls" {
  description = "Repository URL per service id; push images here."
  value = {
    "api"    = aws_ecr_repository.api.repository_url
    "worker" = aws_ecr_repository.worker.repository_url
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
    "api"    = [aws_secretsmanager_secret.api_redis_url.name]
    "worker" = [aws_secretsmanager_secret.worker_redis_url.name]
  }
}

output "data_store_endpoints" {
  description = "Hostnames to put in your connection strings (stored in the secret slots, not here)."
  value = {
    "redis" = aws_elasticache_replication_group.redis.primary_endpoint_address
  }
}
