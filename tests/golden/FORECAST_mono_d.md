<!-- prodpath 0.0.1 | generated 2000-01-01T00:00:00Z | input a791e43f6417 -->

# What will this cost me, and what can bite me?

Target: **AWS**, region `ap-south-1`, environment `prod`.

**Expected: about $260.80 per month**, ranging from $239.75 (low) to $373.09 (spike).

| Scenario | Traffic vs expected | USD per month |
|---|---|---|
| Low | 0.25x | $239.75 |
| Expected | 1x | $260.80 |
| Spike | 5x | $373.09 |

11 of 12 assumptions are defaults, not measurements: supply a `usage.toml` to replace them with your real numbers.

## Biggest cost drivers

1. `rds-postgres`: $77.00 (30%)
2. `vpc-endpoints`: $58.51 (22%)
3. `ecs-svc-apps-api`: $36.50 (14%)
4. `ecs-svc-apps-dashboard`: $36.50 (14%)
5. `alb`: $22.48 (9%)

## Assumptions

Every number below depends on these. **Source** says where each came from: `user` (your usage.toml), `default` (a placeholder), or `inferred` (from your code).

| Assumption | Value | Unit | Source | Note |
|---|---|---|---|---|
| `avg_requests_per_second` | 1 | req/s | **default** | Average external requests per second per web service. |
| `cdn_cache_hit_ratio` | 0.9 | ratio | **default** | Share of static requests answered by CloudFront without reaching S3. |
| `cloudfront_edge_geography` | 1 | geography | **inferred** | Viewers are assumed to be in the same geography as ap-south-1, so CloudFront is priced at its IN edge rates. |
| `ecr_gb_per_repo` | 2 | GB | **default** | Image storage per repository. |
| `hours_per_month` | 730 | h | **default** | AWS billing convention for a month. |
| `log_kb_per_request` | 2 | KB | **default** | Log volume per request (not extracted from code yet). |
| `response_kb` | 10 | KB | **default** | Average response size sent to the internet. |
| `rps_per_task` | 25 | req/s | **default** | Requests per second one task handles at the CPU target. |
| `scenario_low` | 0.25 | x | **default** | Traffic multiplier for the low scenario. |
| `scenario_spike` | 5 | x | **default** | Traffic multiplier for the spike scenario. |
| `site_stored_gb` | 0.5 | GB | **default** | Built files stored per static site. |
| `task_starts_per_month` | 30 | starts | **default** | Starts per task per month; each start reads its secrets. |

## Cost breakdown

Quantities are monthly (730 hours). Always-on resources do not change between scenarios because nothing here autoscales; traffic-driven lines scale with the scenario multiplier.

| Component | Dimension | Expected qty | Unit | Unit price | Price ref | Low | Expected | Spike |
|---|---|---|---|---|---|---|---|---|
| `ecs-svc-apps-api` | vCPU-hours | 730.00 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $29.20 | $29.20 | $29.20 |
| `ecs-svc-apps-api` | memory GB-hours | 1,460.00 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $7.30 | $7.30 | $7.30 |
| `ecs-svc-apps-dashboard` | vCPU-hours | 730.00 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $29.20 | $29.20 | $29.20 |
| `ecs-svc-apps-dashboard` | memory GB-hours | 1,460.00 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $7.30 | $7.30 | $7.30 |
| `alb` | load balancer hours | 730.00 | h | $0.02 | `TEST/alb.hour/alb.hour` | $14.60 | $14.60 | $14.60 |
| `alb` | capacity units (LCU-hours) | 58.40 | LCU-h | $0.01 | `TEST/alb.lcu_hour/alb.lcu_hour` | $0.15 | $0.58 | $2.92 |
| `alb` | public IPv4 addresses (one per AZ) | 1,460.00 | address-h | $0.005 | `TEST/vpc.public_ipv4_hour/vpc.public_ipv4_hour` | $7.30 | $7.30 | $7.30 |
| `logs-apps-api` | log ingestion | 5.26 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $0.66 | $2.63 | $13.14 |
| `logs-apps-api` | log storage | 5.26 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.04 | $0.16 | $0.79 |
| `logs-apps-dashboard` | log ingestion | 5.26 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $0.66 | $2.63 | $13.14 |
| `logs-apps-dashboard` | log storage | 5.26 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.04 | $0.16 | $0.79 |
| `vpc-endpoints` | 4 interface endpoints x 2 AZs | 5,840.00 | endpoint-h | $0.01 | `TEST/vpc.endpoint_hour/vpc.endpoint_hour` | $58.40 | $58.40 | $58.40 |
| `vpc-endpoints` | data processed (logs) | 10.51 | GB | $0.01 | `TEST/vpc.endpoint_gb/vpc.endpoint_gb` | $0.03 | $0.11 | $0.53 |
| `rds-postgres` | db.t4g.small instance hours (multi_az) | 730.00 | h | $0.1 | `TEST/rds.instance.postgres.db.t4g.small.multi_az/rds.instance.postgres.db.t4g.small.multi_az` | $73.00 | $73.00 | $73.00 |
| `rds-postgres` | gp3 storage | 20.00 | GB-month | $0.2 | `TEST/rds.storage.gp3.multi_az.postgres/rds.storage.gp3.multi_az.postgres` | $4.00 | $4.00 | $4.00 |
| `secrets` | 1 slots + 1 RDS-managed | 2.00 | secret-month | $0.5 | `TEST/secrets.secret_month/secrets.secret_month` | $1.00 | $1.00 | $1.00 |
| `secrets` | API requests at task start | 60.00 | requests | $1e-05 | `TEST/secrets.api_request/secrets.api_request` | $0.00 | $0.00 | $0.00 |
| `ecr` | 2 repositories | 4.00 | GB-month | $0.1 | `TEST/ecr.storage_gb_month/ecr.storage_gb_month` | $0.40 | $0.40 | $0.40 |
| `internet-egress` | data transfer out to the internet | 52.56 | GB | $0.1 | `TEST/dt.out_gb/dt.out_gb` | $1.31 | $5.26 | $26.28 |
| `cloudfront-apps-docs` | HTTPS requests | 2,628,000.00 | requests | $1e-06 | `TEST/cloudfront.requests_https.in/cloudfront.requests_https.in` | $0.66 | $2.63 | $13.14 |
| `cloudfront-apps-docs` | data transfer out | 26.28 | GB | $0.1 | `TEST/cloudfront.out_gb.in/cloudfront.out_gb.in` | $0.66 | $2.63 | $13.14 |
| `s3-site-apps-docs` | storage | 0.50 | GB-month | $0.02 | `TEST/s3.storage_gb_month/s3.storage_gb_month` | $0.01 | $0.01 | $0.01 |
| `s3-site-apps-docs` | GET requests (cache misses) | 262,800.00 | requests | $1e-06 | `TEST/s3.get_request/s3.get_request` | $0.07 | $0.26 | $1.31 |
| `cloudfront-apps-marketing` | HTTPS requests | 2,628,000.00 | requests | $1e-06 | `TEST/cloudfront.requests_https.in/cloudfront.requests_https.in` | $0.66 | $2.63 | $13.14 |
| `cloudfront-apps-marketing` | data transfer out | 26.28 | GB | $0.1 | `TEST/cloudfront.out_gb.in/cloudfront.out_gb.in` | $0.66 | $2.63 | $13.14 |
| `s3-site-apps-marketing` | storage | 0.50 | GB-month | $0.02 | `TEST/s3.storage_gb_month/s3.storage_gb_month` | $0.01 | $0.01 | $0.01 |
| `s3-site-apps-marketing` | GET requests (cache misses) | 262,800.00 | requests | $1e-06 | `TEST/s3.get_request/s3.get_request` | $0.07 | $0.26 | $1.31 |
| `cloudfront-apps-spa` | HTTPS requests | 2,628,000.00 | requests | $1e-06 | `TEST/cloudfront.requests_https.in/cloudfront.requests_https.in` | $0.66 | $2.63 | $13.14 |
| `cloudfront-apps-spa` | data transfer out | 26.28 | GB | $0.1 | `TEST/cloudfront.out_gb.in/cloudfront.out_gb.in` | $0.66 | $2.63 | $13.14 |
| `s3-site-apps-spa` | storage | 0.50 | GB-month | $0.02 | `TEST/s3.storage_gb_month/s3.storage_gb_month` | $0.01 | $0.01 | $0.01 |
| `s3-site-apps-spa` | GET requests (cache misses) | 262,800.00 | requests | $1e-06 | `TEST/s3.get_request/s3.get_request` | $0.07 | $0.26 | $1.31 |
| `alarms` | 10 standard alarms | 10.00 | alarm-month | $0.1 | `TEST/cloudwatch.alarm_month/cloudwatch.alarm_month` | $1.00 | $1.00 | $1.00 |
| **Total** |  |  |  |  |  | $239.75 | $260.80 | $373.09 |

## What can bite me

Ranked by severity, then estimated monthly impact.

### 1. autoscaling-max-cost (high)

**Where:** autoscaling.tf (var.service_scaling max_count)  
**Impact:** about $292.00/month

**Why it bites:** Services scale out on CPU (apps-api up to 10 tasks; apps-dashboard up to 10 tasks). Held at those maximums all month they would cost about $292.00 more than the expected forecast. A traffic spike, a retry storm or a slow dependency can push a service there.

**Fix:** Set max_count to what you are willing to pay for, alarm on running task count, and load-test one task to replace the default rps_per_task assumption with a real number.

### 2. interface-endpoint-fixed-cost (medium)

**Where:** network.tf (aws_vpc_endpoint.interface)  
**Impact:** about $58.40/month

**Why it bites:** Interface VPC endpoints bill for every AZ-hour whether or not traffic flows. For a small system this fixed cost can exceed the compute it supports.

**Fix:** Keep only the endpoints you need, run one AZ in non-production, or compare against a NAT gateway for your traffic before deciding.

### 3. internet-egress (medium)

**Where:** alb.tf / static_site.tf (every service that serves users)  
**Impact:** about $13.14/month

**Why it bites:** Data transferred out to the internet is billed per GB and scales with traffic and response size. At the spike scenario it is about $65.70/month.

**Fix:** Compress responses, cache at a CDN, and avoid returning large payloads by default.

### 4. alarm-subscription-unconfirmed (medium)

**Where:** alarms.tf (aws_sns_topic_subscription.alerts_email)  
**Impact:** not priced

**Why it bites:** AWS sends a confirmation e-mail to alert_email when the subscription is created. Until someone clicks the link, every alarm fires into a topic with no listeners and nobody is told that something is wrong.

**Fix:** Apply, open the confirmation e-mail immediately, and test with `aws cloudwatch set-alarm-state` on one alarm. Consider a shared mailbox so alerts do not depend on one person.

### 5. cloudfront-certificate-region (medium)

**Where:** variables.tf (site_certificate_arn), static_site.tf  
**Impact:** not priced

**Why it bites:** CloudFront only accepts ACM certificates from us-east-1, whatever region the rest of the stack uses, and Terraform does not create it. Without one, apps-docs, apps-marketing, apps-spa cannot be served on its own domain.

**Fix:** Request one certificate in us-east-1 covering <service-id>.<domain_name> for each site (or a wildcard), validate it by DNS, and pass its ARN as site_certificate_arn.

### 6. public-ipv4 (low)

**Where:** alb.tf (aws_lb.main)  
**Impact:** about $7.30/month

**Why it bites:** Every public IPv4 address bills per hour; an internet-facing load balancer uses one per AZ.

**Fix:** Accept it for the one shared load balancer; never add a load balancer per service.

### 7. log-ingestion (low)

**Where:** ecs.tf (aws_cloudwatch_log_group)  
**Impact:** about $5.26/month

**Why it bites:** CloudWatch bills every GB of logs ingested, and ingestion grows with traffic and log verbosity. At the spike scenario ingestion alone is about $26.28/month.

**Fix:** Log at INFO or above in production, do not log request bodies, sample noisy lines, and keep retention short (set to 30 days here).

### 8. container-insights (low)

**Where:** ecs.tf (aws_ecs_cluster.main, containerInsights = enabled)  
**Impact:** not priced

**Why it bites:** Container Insights publishes extra metrics and log events that are billed separately and are not in this forecast.

**Fix:** Set the setting to disabled until you need the dashboards, or budget for it.

### 9. cross-az-traffic (low)

**Where:** ecs.tf / rds.tf / elasticache.tf  
**Impact:** not priced

**Why it bites:** Tasks, load balancer nodes and data store replicas spread across two AZs; traffic that crosses AZs is billed in both directions and is not in this forecast.

**Fix:** Keep chatty paths within one AZ where you can; watch inter-AZ bytes in Cost Explorer.

### 10. spa-fallback-hides-404s (low)

**Where:** static_site.tf (custom_error_response)  
**Impact:** not priced

**Why it bites:** apps-spa answer every unknown path with /index.html and status 200, so broken links and missing assets look like successes and never show up as 404s in monitoring.

**Fix:** Have the app render its own not-found page, and watch for missing assets with client-side error reporting. Turn the fallback off for multi-page sites.


## Not priced

- nothing: every planned component with a price model was priced

## Not included in any figure

- NAT gateway (not in the downloaded price files; the generated Terraform has none by default).
- KMS, Route 53, ACM, WAF, CloudWatch metrics and alarms, Container Insights metrics.
- Cross-AZ and service-to-service data transfer; image pull traffic through VPC endpoints.
- RDS backup storage beyond the free allowance; RDS IOPS and throughput above baseline.
- Always-free allowances and credits are not applied, so figures lean high.
- Taxes, support plans, reserved or savings-plan discounts, volume discounts.

## What this forecast is based on

- Prices: AWS Price List, region ap-south-1, fetched 2000-01-01T00:00:00Z (TESTOFFER test).
- On-demand, first paid tier prices only. Every cost line cites its `price_ref` (`<offer>/<sku>/<rateCode>`) in that public price file.
- Quantities come from the architecture and the assumptions above, not from measured traffic. Treat the range as an order-of-magnitude guide until calibrated against a real bill.
