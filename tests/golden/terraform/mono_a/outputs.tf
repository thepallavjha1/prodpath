output "ecr_repository_urls" {
  description = "Repository URL per service id; push images here."
  value = {
    "root" = aws_ecr_repository.root.repository_url
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
    "root" = [aws_secretsmanager_secret.root_database_url.name, aws_secretsmanager_secret.root_flask_secret.name]
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
