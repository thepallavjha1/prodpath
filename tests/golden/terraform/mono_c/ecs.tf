resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ---- apps-billing (web) ----
resource "aws_cloudwatch_log_group" "apps_billing" {
  name              = "/${var.app_name}/${var.environment}/apps-billing"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "apps_billing" {
  name        = "${local.name}-apps-billing"
  description = "Tasks of apps-billing"
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

resource "aws_ecs_task_definition" "apps_billing" {
  family                   = "${local.name}-apps-billing"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["apps-billing"].cpu
  memory                   = var.service_sizing["apps-billing"].memory
  execution_role_arn       = aws_iam_role.apps_billing_execution.arn
  task_role_arn            = aws_iam_role.apps_billing_task.arn

  container_definitions = jsonencode([
    {
      name      = "apps-billing"
      image     = "${aws_ecr_repository.apps_billing.repository_url}:${var.image_tags["apps-billing"]}"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "apps-billing", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_secretsmanager_secret.apps_billing_database_url.arn
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.apps_billing.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "apps_billing" {
  name            = "apps-billing"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.apps_billing.arn
  desired_count   = var.service_sizing["apps-billing"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.apps_billing.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.apps_billing.arn
    container_name   = "apps-billing"
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

# ---- apps-gateway (web) ----
# Non-secret variables found in the code (set their values in var.service_environment["apps-gateway"]):
# PORT
resource "aws_cloudwatch_log_group" "apps_gateway" {
  name              = "/${var.app_name}/${var.environment}/apps-gateway"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "apps_gateway" {
  name        = "${local.name}-apps-gateway"
  description = "Tasks of apps-gateway"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Traffic from the load balancer only"
    from_port       = 3000
    to_port         = 3000
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

resource "aws_ecs_task_definition" "apps_gateway" {
  family                   = "${local.name}-apps-gateway"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["apps-gateway"].cpu
  memory                   = var.service_sizing["apps-gateway"].memory
  execution_role_arn       = aws_iam_role.apps_gateway_execution.arn
  task_role_arn            = aws_iam_role.apps_gateway_task.arn

  container_definitions = jsonencode([
    {
      name      = "apps-gateway"
      image     = "${aws_ecr_repository.apps_gateway.repository_url}:${var.image_tags["apps-gateway"]}"
      essential = true
      portMappings = [
        {
          containerPort = 3000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "apps-gateway", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
        {
          name      = "BILLING_URL"
          valueFrom = aws_secretsmanager_secret.apps_gateway_billing_url.arn
        },
        {
          name      = "USERS_URL"
          valueFrom = aws_secretsmanager_secret.apps_gateway_users_url.arn
        },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.apps_gateway.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "apps_gateway" {
  name            = "apps-gateway"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.apps_gateway.arn
  desired_count   = var.service_sizing["apps-gateway"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.apps_gateway.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.apps_gateway.arn
    container_name   = "apps-gateway"
    container_port   = 3000
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

# ---- apps-notifier (web) ----
# Non-secret variables found in the code (set their values in var.service_environment["apps-notifier"]):
# PORT
resource "aws_cloudwatch_log_group" "apps_notifier" {
  name              = "/${var.app_name}/${var.environment}/apps-notifier"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "apps_notifier" {
  name        = "${local.name}-apps-notifier"
  description = "Tasks of apps-notifier"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Traffic from the load balancer only"
    from_port       = 3000
    to_port         = 3000
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

resource "aws_ecs_task_definition" "apps_notifier" {
  family                   = "${local.name}-apps-notifier"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["apps-notifier"].cpu
  memory                   = var.service_sizing["apps-notifier"].memory
  execution_role_arn       = aws_iam_role.apps_notifier_execution.arn
  task_role_arn            = aws_iam_role.apps_notifier_task.arn

  container_definitions = jsonencode([
    {
      name      = "apps-notifier"
      image     = "${aws_ecr_repository.apps_notifier.repository_url}:${var.image_tags["apps-notifier"]}"
      essential = true
      portMappings = [
        {
          containerPort = 3000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "apps-notifier", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.apps_notifier.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "apps_notifier" {
  name            = "apps-notifier"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.apps_notifier.arn
  desired_count   = var.service_sizing["apps-notifier"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.apps_notifier.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.apps_notifier.arn
    container_name   = "apps-notifier"
    container_port   = 3000
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

# ---- apps-reports (cron) ----
resource "aws_cloudwatch_log_group" "apps_reports" {
  name              = "/${var.app_name}/${var.environment}/apps-reports"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "apps_reports" {
  name        = "${local.name}-apps-reports"
  description = "Tasks of apps-reports"
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

resource "aws_ecs_task_definition" "apps_reports" {
  family                   = "${local.name}-apps-reports"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["apps-reports"].cpu
  memory                   = var.service_sizing["apps-reports"].memory
  execution_role_arn       = aws_iam_role.apps_reports_execution.arn
  task_role_arn            = aws_iam_role.apps_reports_task.arn

  container_definitions = jsonencode([
    {
      name      = "apps-reports"
      image     = "${aws_ecr_repository.apps_reports.repository_url}:${var.image_tags["apps-reports"]}"
      essential = true
      environment = [
        for key, value in lookup(var.service_environment, "apps-reports", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.apps_reports.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

# ---- apps-users (web) ----
resource "aws_cloudwatch_log_group" "apps_users" {
  name              = "/${var.app_name}/${var.environment}/apps-users"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "apps_users" {
  name        = "${local.name}-apps-users"
  description = "Tasks of apps-users"
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

resource "aws_ecs_task_definition" "apps_users" {
  family                   = "${local.name}-apps-users"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["apps-users"].cpu
  memory                   = var.service_sizing["apps-users"].memory
  execution_role_arn       = aws_iam_role.apps_users_execution.arn
  task_role_arn            = aws_iam_role.apps_users_task.arn

  container_definitions = jsonencode([
    {
      name      = "apps-users"
      image     = "${aws_ecr_repository.apps_users.repository_url}:${var.image_tags["apps-users"]}"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "apps-users", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.apps_users.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "apps_users" {
  name            = "apps-users"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.apps_users.arn
  desired_count   = var.service_sizing["apps-users"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.apps_users.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.apps_users.arn
    container_name   = "apps-users"
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

# ---- apps-web (web) ----
# Non-secret variables found in the code (set their values in var.service_environment["apps-web"]):
# PORT
resource "aws_cloudwatch_log_group" "apps_web" {
  name              = "/${var.app_name}/${var.environment}/apps-web"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "apps_web" {
  name        = "${local.name}-apps-web"
  description = "Tasks of apps-web"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Traffic from the load balancer only"
    from_port       = 3000
    to_port         = 3000
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

resource "aws_ecs_task_definition" "apps_web" {
  family                   = "${local.name}-apps-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.service_sizing["apps-web"].cpu
  memory                   = var.service_sizing["apps-web"].memory
  execution_role_arn       = aws_iam_role.apps_web_execution.arn
  task_role_arn            = aws_iam_role.apps_web_task.arn

  container_definitions = jsonencode([
    {
      name      = "apps-web"
      image     = "${aws_ecr_repository.apps_web.repository_url}:${var.image_tags["apps-web"]}"
      essential = true
      portMappings = [
        {
          containerPort = 3000
          protocol      = "tcp"
        }
      ]
      environment = [
        for key, value in lookup(var.service_environment, "apps-web", {}) : {
          name  = key
          value = value
        }
      ]
      secrets = [
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.apps_web.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "apps_web" {
  name            = "apps-web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.apps_web.arn
  desired_count   = var.service_sizing["apps-web"].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.apps_web.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.apps_web.arn
    container_name   = "apps-web"
    container_port   = 3000
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
