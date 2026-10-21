# The only security group open to the internet, and only on 80 and 443.
resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public HTTP and HTTPS entry point"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP from anywhere (redirected to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Forward to targets inside the VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [aws_vpc.main.cidr_block]
  }
}

resource "aws_lb" "main" {
  name                       = substr("${local.name}-alb", 0, 32)
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Not found"
      status_code  = "404"
    }
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# No health endpoint was found for apps-billing; "/" is an assumption. Point it at a real health check.
resource "aws_lb_target_group" "apps_billing" {
  name_prefix          = "appsb-"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path    = "/"
    matcher = "200-399"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener_rule" "apps_billing" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.apps_billing.arn
  }

  condition {
    host_header {
      values = ["apps-billing.${var.domain_name}"]
    }
  }
}

resource "aws_lb_target_group" "apps_gateway" {
  name_prefix          = "appsg-"
  port                 = 3000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path    = "/health"
    matcher = "200-399"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener_rule" "apps_gateway" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 101

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.apps_gateway.arn
  }

  condition {
    host_header {
      values = ["apps-gateway.${var.domain_name}"]
    }
  }
}

resource "aws_lb_target_group" "apps_notifier" {
  name_prefix          = "appsn-"
  port                 = 3000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path    = "/health"
    matcher = "200-399"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener_rule" "apps_notifier" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 102

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.apps_notifier.arn
  }

  condition {
    host_header {
      values = ["apps-notifier.${var.domain_name}"]
    }
  }
}

# No health endpoint was found for apps-users; "/" is an assumption. Point it at a real health check.
resource "aws_lb_target_group" "apps_users" {
  name_prefix          = "appsu-"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path    = "/"
    matcher = "200-399"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener_rule" "apps_users" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 103

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.apps_users.arn
  }

  condition {
    host_header {
      values = ["apps-users.${var.domain_name}"]
    }
  }
}

resource "aws_lb_target_group" "apps_web" {
  name_prefix          = "appsw-"
  port                 = 3000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path    = "/health"
    matcher = "200-399"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_lb_listener_rule" "apps_web" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 104

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.apps_web.arn
  }

  condition {
    host_header {
      values = ["apps-web.${var.domain_name}"]
    }
  }
}
