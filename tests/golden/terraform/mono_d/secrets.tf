# Created empty on purpose: set the value yourself, out of band. Terraform never sees it.
resource "aws_secretsmanager_secret" "apps_api_database_url" {
  name                    = "${var.environment}/apps-api/DATABASE_URL"
  description             = "DATABASE_URL for apps-api. Value is set outside Terraform."
  recovery_window_in_days = 30
}
