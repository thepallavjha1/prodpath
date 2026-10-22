resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ---- root (web) ----
resource "aws_cloudwatch_log_group" "root" {
  name              = "/${var.app_name}/${var.environment}/root"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "root" {
  name        = "${local.name}-root"
  description = "Tasks of root"
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

resource "aws_ecs_task_definition" "root" {
  family                   = "${local.name}-root"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["root"].cpu
  memory                   = var.service_sizing["root"].memory
  execution_role_arn       = aws_iam_role.root_execution.arn
  task_role_arn            = aws_iam_role.root_task.arn

  container_definitions = jsonencode([
    {
      name      = "root"
      image     = "${aws_ecr_repository.root.repository_url}:${var.image_tags["root"]}"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "root", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_secretsmanager_secret.root_database_url.arn
        },
        {
          name      = "FLASK_SECRET"
          valueFrom = aws_secretsmanager_secret.root_flask_secret.arn
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.root.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "root" {
  name            = "root"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.root.arn
  desired_count   = var.service_sizing["root"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.root.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.root.arn
    container_name   = "root"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https]

  # CI deploys new task definition revisions and autoscaling owns the task count: Terraform
  # must not roll either back.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}
