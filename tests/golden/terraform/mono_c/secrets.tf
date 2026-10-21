# Created empty on purpose: set the value yourself, out of band. Terraform never sees it.
resource "aws_secretsmanager_secret" "apps_billing_database_url" {
  name                    = "${var.environment}/apps-billing/DATABASE_URL"
  description             = "DATABASE_URL for apps-billing. Value is set outside Terraform."
  recovery_window_in_days = 30
}

# Created empty on purpose: set the value yourself, out of band. Terraform never sees it.
resource "aws_secretsmanager_secret" "apps_gateway_billing_url" {
  name                    = "${var.environment}/apps-gateway/BILLING_URL"
  description             = "BILLING_URL for apps-gateway. Value is set outside Terraform."
  recovery_window_in_days = 30
}

# Created empty on purpose: set the value yourself, out of band. Terraform never sees it.
resource "aws_secretsmanager_secret" "apps_gateway_users_url" {
  name                    = "${var.environment}/apps-gateway/USERS_URL"
  description             = "USERS_URL for apps-gateway. Value is set outside Terraform."
  recovery_window_in_days = 30
}
