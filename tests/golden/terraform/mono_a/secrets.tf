# Created empty on purpose: set the value yourself, out of band. Terraform never sees it.
resource "aws_secretsmanager_secret" "root_database_url" {
  name                    = "${var.environment}/root/DATABASE_URL"
  description             = "DATABASE_URL for root. Value is set outside Terraform."
  recovery_window_in_days = 30
}

# Created empty on purpose: set the value yourself, out of band. Terraform never sees it.
resource "aws_secretsmanager_secret" "root_flask_secret" {
  name                    = "${var.environment}/root/FLASK_SECRET"
  description             = "FLASK_SECRET for root. Value is set outside Terraform."
  recovery_window_in_days = 30
}
