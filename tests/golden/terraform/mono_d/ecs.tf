resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ---- apps-api (web) ----
resource "aws_cloudwatch_log_group" "apps_api" {
  name              = "/${var.app_name}/${var.environment}/apps-api"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "apps_api" {
  name        = "${local.name}-apps-api"
  description = "Tasks of apps-api"
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

resource "aws_ecs_task_definition" "apps_api" {
  family                   = "${local.name}-apps-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["apps-api"].cpu
  memory                   = var.service_sizing["apps-api"].memory
  execution_role_arn       = aws_iam_role.apps_api_execution.arn
  task_role_arn            = aws_iam_role.apps_api_task.arn

  container_definitions = jsonencode([
    {
      name      = "apps-api"
      image     = "${aws_ecr_repository.apps_api.repository_url}:${var.image_tags["apps-api"]}"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "apps-api", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_secretsmanager_secret.apps_api_database_url.arn
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.apps_api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "apps_api" {
  name            = "apps-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.apps_api.arn
  desired_count   = var.service_sizing["apps-api"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.apps_api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.apps_api.arn
    container_name   = "apps-api"
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

# ---- apps-dashboard (web) ----
# The listening port was not found in the code; 8080 is an assumption. Fix it here and in the Dockerfile.
resource "aws_cloudwatch_log_group" "apps_dashboard" {
  name              = "/${var.app_name}/${var.environment}/apps-dashboard"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "apps_dashboard" {
  name        = "${local.name}-apps-dashboard"
  description = "Tasks of apps-dashboard"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Traffic from the load balancer only"
    from_port       = 8080
    to_port         = 8080
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

resource "aws_ecs_task_definition" "apps_dashboard" {
  family                   = "${local.name}-apps-dashboard"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["apps-dashboard"].cpu
  memory                   = var.service_sizing["apps-dashboard"].memory
  execution_role_arn       = aws_iam_role.apps_dashboard_execution.arn
  task_role_arn            = aws_iam_role.apps_dashboard_task.arn

  container_definitions = jsonencode([
    {
      name      = "apps-dashboard"
      image     = "${aws_ecr_repository.apps_dashboard.repository_url}:${var.image_tags["apps-dashboard"]}"
      essential = true
      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "apps-dashboard", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.apps_dashboard.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "apps_dashboard" {
  name            = "apps-dashboard"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.apps_dashboard.arn
  desired_count   = var.service_sizing["apps-dashboard"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.apps_dashboard.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.apps_dashboard.arn
    container_name   = "apps-dashboard"
    container_port   = 8080
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
