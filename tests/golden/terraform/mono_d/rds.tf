resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_security_group" "rds_postgres" {
  name        = "${local.name}-rds-postgres"
  description = "postgres access from the services that use it"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "postgres from the services that use it"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.apps_api.id]
  }
}

# One instance for every service that uses postgres: give each service its own database
# and user inside it. The master password is generated and kept in Secrets Manager by AWS.
resource "aws_db_instance" "postgres" {
  identifier                  = "${local.name}-postgres"
  engine                      = "postgres"
  instance_class              = var.rds_instance_class["postgres"]
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  multi_az                    = true
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.rds_postgres.id]
  publicly_accessible         = false
  username                    = "dbadmin"
  manage_master_user_password = true
  backup_retention_period     = 7
  auto_minor_version_upgrade  = true
  deletion_protection         = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${local.name}-postgres-final"
}
