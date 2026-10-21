# One GitHub OIDC provider is allowed per account: set create_github_oidc_provider = false if it exists.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  github_oidc_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only this repository and branch can assume the role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${local.name}-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

resource "aws_iam_role_policy" "github_actions" {
  name = "deploy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # ecr:GetAuthorizationToken does not support resource-level permissions, so "*" is required.
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
        ]
        Resource = [
          aws_ecr_repository.apps_billing.arn,
          aws_ecr_repository.apps_gateway.arn,
          aws_ecr_repository.apps_notifier.arn,
          aws_ecr_repository.apps_reports.arn,
          aws_ecr_repository.apps_users.arn,
          aws_ecr_repository.apps_web.arn,
        ]
      },
      {
        # RegisterTaskDefinition and DescribeTaskDefinition do not support resource-level permissions.
        Effect   = "Allow"
        Action   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["ecs:UpdateService", "ecs:DescribeServices"]
        Resource = [
          aws_ecs_service.apps_billing.id,
          aws_ecs_service.apps_gateway.id,
          aws_ecs_service.apps_notifier.id,
          aws_ecs_service.apps_users.id,
          aws_ecs_service.apps_web.id,
        ]
      },
      {
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.apps_billing_execution.arn,
          aws_iam_role.apps_billing_task.arn,
          aws_iam_role.apps_gateway_execution.arn,
          aws_iam_role.apps_gateway_task.arn,
          aws_iam_role.apps_notifier_execution.arn,
          aws_iam_role.apps_notifier_task.arn,
          aws_iam_role.apps_reports_execution.arn,
          aws_iam_role.apps_reports_task.arn,
          aws_iam_role.apps_users_execution.arn,
          aws_iam_role.apps_users_task.arn,
          aws_iam_role.apps_web_execution.arn,
          aws_iam_role.apps_web_task.arn,
        ]
      },
    ]
  })
}
