data "aws_iam_policy_document" "scheduler_assume_apps_reports" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apps_reports_scheduler" {
  name               = "${local.name}-apps-reports-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_apps_reports.json
}

resource "aws_iam_role_policy" "apps_reports_scheduler" {
  name = "run-own-task"
  role = aws_iam_role.apps_reports_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = ["${aws_ecs_task_definition.apps_reports.arn_without_revision}:*"]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.apps_reports_execution.arn, aws_iam_role.apps_reports_task.arn]
      }
    ]
  })
}

resource "aws_scheduler_schedule" "apps_reports" {
  name                = "${local.name}-apps-reports"
  schedule_expression = var.schedule_expressions["apps-reports"]

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.apps_reports_scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.apps_reports.arn
      launch_type         = "FARGATE"

      network_configuration {
        subnets          = aws_subnet.private[*].id
        security_groups  = [aws_security_group.apps_reports.id]
        assign_public_ip = false
      }
    }
  }
}
