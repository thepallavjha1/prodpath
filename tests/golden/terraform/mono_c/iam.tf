data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# apps-billing: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "apps_billing_execution" {
  name               = "${local.name}-apps-billing-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "apps_billing_execution" {
  role       = aws_iam_role.apps_billing_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "apps_billing_execution_secrets" {
  name = "read-own-secrets"
  role = aws_iam_role.apps_billing_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.apps_billing_database_url.arn,
        ]
      }
    ]
  })
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "apps_billing_task" {
  name               = "${local.name}-apps-billing-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# apps-gateway: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "apps_gateway_execution" {
  name               = "${local.name}-apps-gateway-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "apps_gateway_execution" {
  role       = aws_iam_role.apps_gateway_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "apps_gateway_execution_secrets" {
  name = "read-own-secrets"
  role = aws_iam_role.apps_gateway_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.apps_gateway_billing_url.arn,
          aws_secretsmanager_secret.apps_gateway_users_url.arn,
        ]
      }
    ]
  })
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "apps_gateway_task" {
  name               = "${local.name}-apps-gateway-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# apps-notifier: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "apps_notifier_execution" {
  name               = "${local.name}-apps-notifier-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "apps_notifier_execution" {
  role       = aws_iam_role.apps_notifier_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "apps_notifier_task" {
  name               = "${local.name}-apps-notifier-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# apps-reports: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "apps_reports_execution" {
  name               = "${local.name}-apps-reports-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "apps_reports_execution" {
  role       = aws_iam_role.apps_reports_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "apps_reports_task" {
  name               = "${local.name}-apps-reports-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# apps-users: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "apps_users_execution" {
  name               = "${local.name}-apps-users-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "apps_users_execution" {
  role       = aws_iam_role.apps_users_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "apps_users_task" {
  name               = "${local.name}-apps-users-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# apps-web: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "apps_web_execution" {
  name               = "${local.name}-apps-web-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "apps_web_execution" {
  role       = aws_iam_role.apps_web_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "apps_web_task" {
  name               = "${local.name}-apps-web-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}
