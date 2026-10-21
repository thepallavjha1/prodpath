resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_security_group" "redis" {
  name        = "${local.name}-redis"
  description = "Redis access from the services that use it"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from the services that use it"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id, aws_security_group.worker.id]
  }
}

# Encryption in transit is ON: clients must connect with TLS (rediss://), or connections fail.
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = substr("${local.name}-redis", 0, 40)
  description                = "Redis for ${local.name}"
  engine                     = "redis"
  node_type                  = var.redis_node_type
  port                       = 6379
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.redis.id]
}
