data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# root: the execution role pulls the image, writes logs and reads this service's secrets.
resource "aws_iam_role" "root_execution" {
  name               = "${local.name}-root-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "root_execution" {
  role       = aws_iam_role.root_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "root_execution_secrets" {
  name = "read-own-secrets"
  role = aws_iam_role.root_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          aws_secretsmanager_secret.root_database_url.arn,
          aws_secretsmanager_secret.root_flask_secret.arn,
        ]
      }
    ]
  })
}

# The task role is what the application code runs as: only the resources it was found using.
resource "aws_iam_role" "root_task" {
  name               = "${local.name}-root-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "root_task" {
  name = "app-access"
  role = aws_iam_role.root_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = ["${aws_s3_bucket.s3_root.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.s3_root.arn]
      },
    ]
  })
}
