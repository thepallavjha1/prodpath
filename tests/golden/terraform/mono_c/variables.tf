variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-south-1"
}

variable "environment" {
  description = "Environment name; used in resource names and secret paths."
  type        = string
  default     = "prod"
}

variable "app_name" {
  description = "Short lowercase prefix for resource names (letters, digits, hyphens)."
  type        = string
}

variable "log_retention_days" {
  description = "How long CloudWatch keeps logs."
  type        = number
  default     = 30
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "enable_nat_gateway" {
  description = "Create a NAT gateway so private services can reach the internet. It bills per hour and per GB processed; leave off unless a service needs outbound internet access."
  type        = bool
  default     = false
}

variable "image_tags" {
  description = "Image tag to run for each service id. Use the git SHA, never 'latest' (repositories are immutable)."
  type        = map(string)
}

variable "service_sizing" {
  description = "CPU units, memory (MiB) and task count per service id. Defaults are starting points, not measurements."
  type = map(object({
    cpu           = number
    memory        = number
    desired_count = number
  }))
  default = {
    "apps-billing" = {
      cpu           = 512
      memory        = 1024
      desired_count = 2
    }
    "apps-gateway" = {
      cpu           = 512
      memory        = 1024
      desired_count = 2
    }
    "apps-notifier" = {
      cpu           = 512
      memory        = 1024
      desired_count = 2
    }
    "apps-reports" = {
      cpu           = 256
      memory        = 512
      desired_count = 1
    }
    "apps-users" = {
      cpu           = 512
      memory        = 1024
      desired_count = 2
    }
    "apps-web" = {
      cpu           = 512
      memory        = 1024
      desired_count = 2
    }
  }
}

variable "service_environment" {
  description = "Non-secret environment variables per service id. Never put secrets here; use the Secrets Manager slots."
  type        = map(map(string))
  default     = {}
}

variable "certificate_arn" {
  description = "ARN of the ACM certificate for the HTTPS listener (in the same region)."
  type        = string
}

variable "domain_name" {
  description = "Base domain. Each web service is routed by host: <service-id>.<domain_name>."
  type        = string
}

variable "schedule_expressions" {
  description = "EventBridge Scheduler expression per scheduled service id, e.g. cron(0 2 * * ? *). The tool could not extract these from the code."
  type        = map(string)
}

variable "rds_instance_class" {
  description = "RDS instance class per engine."
  type        = map(string)
  default = {
    "postgres" = "db.t4g.small"
  }
}

variable "redis_node_type" {
  description = "ElastiCache node type for Redis."
  type        = string
  default     = "cache.t4g.micro"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as <org>/<repo>."
  type        = string
}

variable "github_branch" {
  description = "Branch allowed to assume the deploy role."
  type        = string
  default     = "main"
}

variable "create_github_oidc_provider" {
  description = "Set to false if the account already has the GitHub OIDC provider (only one is allowed per account)."
  type        = bool
  default     = true
}
