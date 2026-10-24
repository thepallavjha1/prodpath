<!-- prodpath 0.0.1 | generated 2000-01-01T00:00:00Z | input 0d6f0749f98d -->

# What will this cost me, and what can bite me?

Target: **AWS**, region `ap-south-1`, environment `prod`.

**Expected: about $221.33 per month**, ranging from $202.56 (low) to $321.47 (spike).

| Scenario | Traffic vs expected | USD per month |
|---|---|---|
| Low | 0.25x | $202.56 |
| Expected | 1x | $221.33 |
| Spike | 5x | $321.47 |

14 of 14 assumptions are defaults, not measurements: supply a `usage.toml` to replace them with your real numbers.

## Biggest cost drivers

1. `rds-postgres`: $77.00 (35%)
2. `vpc-endpoints`: $58.61 (26%)
3. `ecs-svc-root`: $36.50 (16%)
4. `alb`: $23.07 (10%)
5. `logs-root`: $11.14 (5%)

## Assumptions

Every number below depends on these. **Source** says where each came from: `user` (your usage.toml), `default` (a placeholder), or `inferred` (from your code).

| Assumption | Value | Unit | Source | Note |
|---|---|---|---|---|
| `avg_requests_per_second` | 4 | req/s | **default** | Derived: peak 20 req/s divided by the peak-to-average ratio 5. Set it directly in usage.toml if you know the average. |
| `ecr_gb_per_repo` | 2 | GB | **default** | Image storage per repository. |
| `hours_per_month` | 730 | h | **default** | AWS billing convention for a month. |
| `log_kb_per_request` | 2 | KB | **default** | Log volume per request (not extracted from code yet). |
| `peak_requests_per_second` | 20 | req/s | **default** | Busiest sustained requests per second per web service (the peak, not the average). |
| `peak_to_average_ratio` | 5 | x | **default** | How many times busier the peak is than the monthly average. |
| `response_kb` | 10 | KB | **default** | Average response size sent to the internet. |
| `rps_per_task` | 25 | req/s | **default** | Requests per second one task handles at the CPU target. |
| `s3_gets_per_month` | 1e+06 | requests | **default** | S3 GET requests per bucket. |
| `s3_puts_per_month` | 100000 | requests | **default** | S3 PUT/COPY/POST/LIST requests per bucket. |
| `s3_stored_gb` | 10 | GB | **default** | Stored data per bucket. |
| `scenario_low` | 0.25 | x | **default** | Traffic multiplier for the low scenario. |
| `scenario_spike` | 5 | x | **default** | A month run at the peak: the peak divided by the average. |
| `task_starts_per_month` | 30 | starts | **default** | Starts per task per month; each start reads its secrets. |

## Cost breakdown

Quantities are monthly (730 hours). Always-on resources do not change between scenarios because nothing here autoscales; traffic-driven lines scale with the scenario multiplier.

| Component | Dimension | Expected qty | Unit | Unit price | Price ref | Low | Expected | Spike |
|---|---|---|---|---|---|---|---|---|
| `ecs-svc-root` | vCPU-hours | 730.00 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $29.20 | $29.20 | $29.20 |
| `ecs-svc-root` | memory GB-hours | 1,460.00 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $7.30 | $7.30 | $7.30 |
| `alb` | load balancer hours | 730.00 | h | $0.02 | `TEST/alb.hour/alb.hour` | $14.60 | $14.60 | $14.60 |
| `alb` | capacity units (LCU-hours) | 116.80 | LCU-h | $0.01 | `TEST/alb.lcu_hour/alb.lcu_hour` | $0.29 | $1.17 | $5.84 |
| `alb` | public IPv4 addresses (one per AZ) | 1,460.00 | address-h | $0.005 | `TEST/vpc.public_ipv4_hour/vpc.public_ipv4_hour` | $7.30 | $7.30 | $7.30 |
| `logs-root` | log ingestion | 21.02 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $2.63 | $10.51 | $52.56 |
| `logs-root` | log storage | 21.02 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.16 | $0.63 | $3.15 |
| `vpc-endpoints` | 4 interface endpoints x 2 AZs | 5,840.00 | endpoint-h | $0.01 | `TEST/vpc.endpoint_hour/vpc.endpoint_hour` | $58.40 | $58.40 | $58.40 |
| `vpc-endpoints` | data processed (logs) | 21.02 | GB | $0.01 | `TEST/vpc.endpoint_gb/vpc.endpoint_gb` | $0.05 | $0.21 | $1.05 |
| `rds-postgres` | db.t4g.small instance hours (multi_az) | 730.00 | h | $0.1 | `TEST/rds.instance.postgres.db.t4g.small.multi_az/rds.instance.postgres.db.t4g.small.multi_az` | $73.00 | $73.00 | $73.00 |
| `rds-postgres` | gp3 storage | 20.00 | GB-month | $0.2 | `TEST/rds.storage.gp3.multi_az.postgres/rds.storage.gp3.multi_az.postgres` | $4.00 | $4.00 | $4.00 |
| `s3-root` | storage | 10.00 | GB-month | $0.02 | `TEST/s3.storage_gb_month/s3.storage_gb_month` | $0.20 | $0.20 | $0.20 |
| `s3-root` | PUT/COPY/POST/LIST requests | 100,000.00 | requests | $1e-05 | `TEST/s3.put_request/s3.put_request` | $0.25 | $1.00 | $5.00 |
| `s3-root` | GET requests | 1,000,000.00 | requests | $1e-06 | `TEST/s3.get_request/s3.get_request` | $0.25 | $1.00 | $5.00 |
| `secrets` | 2 slots + 1 RDS-managed | 3.00 | secret-month | $0.5 | `TEST/secrets.secret_month/secrets.secret_month` | $1.50 | $1.50 | $1.50 |
| `secrets` | API requests at task start | 120.00 | requests | $1e-05 | `TEST/secrets.api_request/secrets.api_request` | $0.00 | $0.00 | $0.00 |
| `ecr` | 1 repositories | 2.00 | GB-month | $0.1 | `TEST/ecr.storage_gb_month/ecr.storage_gb_month` | $0.20 | $0.20 | $0.20 |
| `internet-egress` | data transfer out to the internet | 105.12 | GB | $0.1 | `TEST/dt.out_gb/dt.out_gb` | $2.63 | $10.51 | $52.56 |
| `alarms` | 6 standard alarms | 6.00 | alarm-month | $0.1 | `TEST/cloudwatch.alarm_month/cloudwatch.alarm_month` | $0.60 | $0.60 | $0.60 |
| **Total** |  |  |  |  |  | $202.56 | $221.33 | $321.47 |

## What can bite me

Ranked by severity, then estimated monthly impact.

### 1. interface-endpoint-fixed-cost (high)

**Where:** network.tf (aws_vpc_endpoint.interface)  
**Impact:** about $58.40/month

**Why it bites:** Interface VPC endpoints bill for every AZ-hour whether or not traffic flows. For a small system this fixed cost can exceed the compute it supports.

**Fix:** Keep only the endpoints you need, run one AZ in non-production, or compare against a NAT gateway for your traffic before deciding.

### 2. autoscaling-max-cost (medium)

**Where:** autoscaling.tf (var.service_scaling max_count)  
**Impact:** about $146.00/month

**Why it bites:** Services scale out on CPU (root up to 10 tasks). Held at those maximums all month they would cost about $146.00 more than the expected forecast. A traffic spike, a retry storm or a slow dependency can push a service there.

**Fix:** Set max_count to what you are willing to pay for, alarm on running task count, and load-test one task to replace the default rps_per_task assumption with a real number.

### 3. internet-egress (medium)

**Where:** alb.tf / static_site.tf (every service that serves users)  
**Impact:** about $10.51/month

**Why it bites:** Data transferred out to the internet is billed per GB and scales with traffic and response size. At the spike scenario it is about $52.56/month.

**Fix:** Compress responses, cache at a CDN, and avoid returning large payloads by default.

### 4. log-ingestion (medium)

**Where:** ecs.tf (aws_cloudwatch_log_group)  
**Impact:** about $10.51/month

**Why it bites:** CloudWatch bills every GB of logs ingested, and ingestion grows with traffic and log verbosity. At the spike scenario ingestion alone is about $52.56/month.

**Fix:** Log at INFO or above in production, do not log request bodies, sample noisy lines, and keep retention short (set to 30 days here).

### 5. alarm-subscription-unconfirmed (medium)

**Where:** alarms.tf (aws_sns_topic_subscription.alerts_email)  
**Impact:** not priced

**Why it bites:** AWS sends a confirmation e-mail to alert_email when the subscription is created. Until someone clicks the link, every alarm fires into a topic with no listeners and nobody is told that something is wrong.

**Fix:** Apply, open the confirmation e-mail immediately, and test with `aws cloudwatch set-alarm-state` on one alarm. Consider a shared mailbox so alerts do not depend on one person.

### 6. public-ipv4 (low)

**Where:** alb.tf (aws_lb.main)  
**Impact:** about $7.30/month

**Why it bites:** Every public IPv4 address bills per hour; an internet-facing load balancer uses one per AZ.

**Fix:** Accept it for the one shared load balancer; never add a load balancer per service.

### 7. container-insights (low)

**Where:** ecs.tf (aws_ecs_cluster.main, containerInsights = enabled)  
**Impact:** not priced

**Why it bites:** Container Insights publishes extra metrics and log events that are billed separately and are not in this forecast.

**Fix:** Set the setting to disabled until you need the dashboards, or budget for it.

### 8. cross-az-traffic (low)

**Where:** ecs.tf / rds.tf / elasticache.tf  
**Impact:** not priced

**Why it bites:** Tasks, load balancer nodes and data store replicas spread across two AZs; traffic that crosses AZs is billed in both directions and is not in this forecast.

**Fix:** Keep chatty paths within one AZ where you can; watch inter-AZ bytes in Cost Explorer.


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
