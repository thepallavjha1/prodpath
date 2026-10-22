resource "aws_appautoscaling_target" "apps_billing" {
  max_capacity       = var.service_scaling["apps-billing"].max_count
  min_capacity       = var.service_scaling["apps-billing"].min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.apps_billing.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "apps_billing_cpu" {
  name               = "${local.name}-apps-billing-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.apps_billing.resource_id
  scalable_dimension = aws_appautoscaling_target.apps_billing.scalable_dimension
  service_namespace  = aws_appautoscaling_target.apps_billing.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.service_scaling["apps-billing"].cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_target" "apps_gateway" {
  max_capacity       = var.service_scaling["apps-gateway"].max_count
  min_capacity       = var.service_scaling["apps-gateway"].min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.apps_gateway.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "apps_gateway_cpu" {
  name               = "${local.name}-apps-gateway-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.apps_gateway.resource_id
  scalable_dimension = aws_appautoscaling_target.apps_gateway.scalable_dimension
  service_namespace  = aws_appautoscaling_target.apps_gateway.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.service_scaling["apps-gateway"].cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_target" "apps_notifier" {
  max_capacity       = var.service_scaling["apps-notifier"].max_count
  min_capacity       = var.service_scaling["apps-notifier"].min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.apps_notifier.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "apps_notifier_cpu" {
  name               = "${local.name}-apps-notifier-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.apps_notifier.resource_id
  scalable_dimension = aws_appautoscaling_target.apps_notifier.scalable_dimension
  service_namespace  = aws_appautoscaling_target.apps_notifier.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.service_scaling["apps-notifier"].cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_target" "apps_users" {
  max_capacity       = var.service_scaling["apps-users"].max_count
  min_capacity       = var.service_scaling["apps-users"].min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.apps_users.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "apps_users_cpu" {
  name               = "${local.name}-apps-users-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.apps_users.resource_id
  scalable_dimension = aws_appautoscaling_target.apps_users.scalable_dimension
  service_namespace  = aws_appautoscaling_target.apps_users.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.service_scaling["apps-users"].cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_target" "apps_web" {
  max_capacity       = var.service_scaling["apps-web"].max_count
  min_capacity       = var.service_scaling["apps-web"].min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.apps_web.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "apps_web_cpu" {
  name               = "${local.name}-apps-web-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.apps_web.resource_id
  scalable_dimension = aws_appautoscaling_target.apps_web.scalable_dimension
  service_namespace  = aws_appautoscaling_target.apps_web.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.service_scaling["apps-web"].cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
