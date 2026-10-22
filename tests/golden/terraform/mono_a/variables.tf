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
    "root" = {
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

variable "service_scaling" {
  description = "Autoscaling bounds per service id: task count range and the CPU percentage to hold. Defaults are starting points; max_count is also your cost ceiling."
  type = map(object({
    min_count  = number
    max_count  = number
    cpu_target = number
  }))
  default = {
    "root" = {
      min_count  = 2
      max_count  = 10
      cpu_target = 60
    }
  }
}

variable "alert_email" {
  description = "E-mail address for alarm notifications. AWS sends a confirmation link first; alarms reach nobody until it is clicked."
  type        = string
}

variable "certificate_arn" {
  description = "ARN of the ACM certificate for the HTTPS listener (in the same region)."
  type        = string
}

variable "domain_name" {
  description = "Base domain. Each web service and static site is served at <service-id>.<domain_name>."
  type        = string
}

variable "rds_instance_class" {
  description = "RDS instance class per engine."
  type        = map(string)
  default = {
    "postgres" = "db.t4g.small"
  }
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
