data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  name = "${var.app_name}-${var.environment}"
}
