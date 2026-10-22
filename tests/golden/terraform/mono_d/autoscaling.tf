resource "aws_appautoscaling_target" "apps_api" {
  max_capacity       = var.service_scaling["apps-api"].max_count
  min_capacity       = var.service_scaling["apps-api"].min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.apps_api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "apps_api_cpu" {
  name               = "${local.name}-apps-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.apps_api.resource_id
  scalable_dimension = aws_appautoscaling_target.apps_api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.apps_api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.service_scaling["apps-api"].cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_target" "apps_dashboard" {
  max_capacity       = var.service_scaling["apps-dashboard"].max_count
  min_capacity       = var.service_scaling["apps-dashboard"].min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.apps_dashboard.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "apps_dashboard_cpu" {
  name               = "${local.name}-apps-dashboard-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.apps_dashboard.resource_id
  scalable_dimension = aws_appautoscaling_target.apps_dashboard.scalable_dimension
  service_namespace  = aws_appautoscaling_target.apps_dashboard.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.service_scaling["apps-dashboard"].cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
