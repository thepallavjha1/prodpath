data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# apps-api: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "apps_api_execution" {
  name               = "${local.name}-apps-api-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "apps_api_execution" {
  role       = aws_iam_role.apps_api_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "apps_api_execution_secrets" {
  name = "read-own-secrets"
  role = aws_iam_role.apps_api_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.apps_api_database_url.arn,
        ]
      }
    ]
  })
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "apps_api_task" {
  name               = "${local.name}-apps-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# apps-dashboard: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "apps_dashboard_execution" {
  name               = "${local.name}-apps-dashboard-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "apps_dashboard_execution" {
  role       = aws_iam_role.apps_dashboard_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "apps_dashboard_task" {
  name               = "${local.name}-apps-dashboard-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}
