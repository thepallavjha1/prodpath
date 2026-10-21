resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ---- api (web) ----
resource "aws_cloudwatch_log_group" "api" {
  name              = "/${var.app_name}/${var.environment}/api"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "api" {
  name        = "${local.name}-api"
  description = "Tasks of api"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Traffic from the load balancer only"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  # Egress is open; reachability is limited by routing (VPC endpoints, optional NAT).
  egress {
    description = "Outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["api"].cpu
  memory                   = var.service_sizing["api"].memory
  execution_role_arn       = aws_iam_role.api_execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:${var.image_tags["api"]}"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "api", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
        {
          name      = "REDIS_URL"
          valueFrom = aws_secretsmanager_secret.api_redis_url.arn
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.service_sizing["api"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https]

  # CI deploys new task definition revisions; Terraform must not roll them back.
  lifecycle {
    ignore_changes = [task_definition]
  }
}

# ---- worker (worker) ----
resource "aws_cloudwatch_log_group" "worker" {
  name              = "/${var.app_name}/${var.environment}/worker"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "worker" {
  name        = "${local.name}-worker"
  description = "Tasks of worker"
  vpc_id      = aws_vpc.main.id

  # Egress is open; reachability is limited by routing (VPC endpoints, optional NAT).
  egress {
    description = "Outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["worker"].cpu
  memory                   = var.service_sizing["worker"].memory
  execution_role_arn       = aws_iam_role.worker_execution.arn
  task_role_arn            = aws_iam_role.worker_task.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = "${aws_ecr_repository.worker.repository_url}:${var.image_tags["worker"]}"
      essential = true
      environment = [
        for key, value in lookup(var.service_environment, "worker", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
        {
          name      = "REDIS_URL"
          valueFrom = aws_secretsmanager_secret.worker_redis_url.arn
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.service_sizing["worker"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # CI deploys new task definition revisions; Terraform must not roll them back.
  lifecycle {
    ignore_changes = [task_definition]
  }
}
