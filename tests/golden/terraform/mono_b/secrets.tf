# Created empty on purpose: set the value yourself, out of band. Terraform never sees it.
resource "aws_secretsmanager_secret" "api_redis_url" {
  name                    = "${var.environment}/api/REDIS_URL"
  description             = "REDIS_URL for api. Value is set outside Terraform."
  recovery_window_in_days = 30
}

# Created empty on purpose: set the value yourself, out of band. Terraform never sees it.
resource "aws_secretsmanager_secret" "worker_redis_url" {
  name                    = "${var.environment}/worker/REDIS_URL"
  description             = "REDIS_URL for worker. Value is set outside Terraform."
  recovery_window_in_days = 30
}
