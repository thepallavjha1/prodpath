resource "aws_appautoscaling_target" "root" {
  max_capacity       = var.service_scaling["root"].max_count
  min_capacity       = var.service_scaling["root"].min_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.root.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "root_cpu" {
  name               = "${local.name}-root-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.root.resource_id
  scalable_dimension = aws_appautoscaling_target.root.scalable_dimension
  service_namespace  = aws_appautoscaling_target.root.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = var.service_scaling["root"].cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 300

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
