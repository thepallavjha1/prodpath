<!-- prodpath 0.0.1 | generated 2000-01-01T00:00:00Z | input ce452fc2f379 -->

# What will this cost me, and what can bite me?

Target: **AWS**, region `ap-south-1`, environment `prod`.

**Expected: about $402.18 per month**, ranging from $380.15 (low) to $519.68 (spike).

| Scenario | Traffic vs expected | USD per month |
|---|---|---|
| Low | 0.25x | $380.15 |
| Expected | 1x | $402.18 |
| Spike | 5x | $519.68 |

11 of 12 assumptions are defaults, not measurements: supply a `usage.toml` to replace them with your real numbers.

## Biggest cost drivers

1. `rds-postgres`: $77.00 (19%)
2. `vpc-endpoints`: $58.67 (15%)
3. `ecs-svc-apps-billing`: $36.50 (9%)
4. `ecs-svc-apps-gateway`: $36.50 (9%)
5. `ecs-svc-apps-notifier`: $36.50 (9%)

## Assumptions

Every number below depends on these. **Source** says where each came from: `user` (your usage.toml), `default` (a placeholder), or `inferred` (from your code).

| Assumption | Value | Unit | Source | Note |
|---|---|---|---|---|
| `avg_requests_per_second` | 1 | req/s | **default** | Average external requests per second per web service. |
| `cron_minutes_per_run` | 10 | min | **default** | Duration of one scheduled job run. |
| `cron_runs_per_month` | 30 | runs | **default** | Runs per scheduled job per month. |
| `ecr_gb_per_repo` | 2 | GB | **default** | Image storage per repository. |
| `hours_per_month` | 730 | h | **default** | AWS billing convention for a month. |
| `internal_http_calls_per_request` | 1 | calls | **inferred** | One internal request through the load balancer per request, for each service-to-service URL found in the code: apps-gateway->apps-billing, apps-gateway->apps-users |
| `log_kb_per_request` | 2 | KB | **default** | Log volume per request (not extracted from code yet). |
| `response_kb` | 10 | KB | **default** | Average response size sent to the internet. |
| `scenario_low` | 0.25 | x | **default** | Traffic multiplier for the low scenario. |
| `scenario_spike` | 5 | x | **default** | Traffic multiplier for the spike scenario. |
| `task_starts_per_month` | 30 | starts | **default** | Starts per task per month; each start reads its secrets. |
| `worker_log_gb_per_month` | 1 | GB | **default** | Log volume per worker or scheduled service. |

## Cost breakdown

Quantities are monthly (730 hours). Always-on resources do not change between scenarios because nothing here autoscales; traffic-driven lines scale with the scenario multiplier.

| Component | Dimension | Expected qty | Unit | Unit price | Price ref | Low | Expected | Spike |
|---|---|---|---|---|---|---|---|---|
| `cron-apps-reports` | vCPU-hours | 1.25 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $0.05 | $0.05 | $0.05 |
| `cron-apps-reports` | memory GB-hours | 2.50 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $0.01 | $0.01 | $0.01 |
| `ecs-svc-apps-billing` | vCPU-hours | 730.00 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $29.20 | $29.20 | $29.20 |
| `ecs-svc-apps-billing` | memory GB-hours | 1,460.00 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $7.30 | $7.30 | $7.30 |
| `ecs-svc-apps-gateway` | vCPU-hours | 730.00 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $29.20 | $29.20 | $29.20 |
| `ecs-svc-apps-gateway` | memory GB-hours | 1,460.00 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $7.30 | $7.30 | $7.30 |
| `ecs-svc-apps-notifier` | vCPU-hours | 730.00 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $29.20 | $29.20 | $29.20 |
| `ecs-svc-apps-notifier` | memory GB-hours | 1,460.00 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $7.30 | $7.30 | $7.30 |
| `ecs-svc-apps-users` | vCPU-hours | 730.00 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $29.20 | $29.20 | $29.20 |
| `ecs-svc-apps-users` | memory GB-hours | 1,460.00 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $7.30 | $7.30 | $7.30 |
| `ecs-svc-apps-web` | vCPU-hours | 730.00 | vCPU-h | $0.04 | `TEST/fargate.vcpu_hour/fargate.vcpu_hour` | $29.20 | $29.20 | $29.20 |
| `ecs-svc-apps-web` | memory GB-hours | 1,460.00 | GB-h | $0.005 | `TEST/fargate.gb_hour/fargate.gb_hour` | $7.30 | $7.30 | $7.30 |
| `alb` | load balancer hours | 730.00 | h | $0.02 | `TEST/alb.hour/alb.hour` | $14.60 | $14.60 | $14.60 |
| `alb` | capacity units (LCU-hours) | 204.40 | LCU-h | $0.01 | `TEST/alb.lcu_hour/alb.lcu_hour` | $0.51 | $2.04 | $10.22 |
| `alb` | public IPv4 addresses (one per AZ) | 1,460.00 | address-h | $0.005 | `TEST/vpc.public_ipv4_hour/vpc.public_ipv4_hour` | $7.30 | $7.30 | $7.30 |
| `logs-apps-billing` | log ingestion | 5.26 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $0.66 | $2.63 | $13.14 |
| `logs-apps-billing` | log storage | 5.26 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.04 | $0.16 | $0.79 |
| `logs-apps-gateway` | log ingestion | 5.26 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $0.66 | $2.63 | $13.14 |
| `logs-apps-gateway` | log storage | 5.26 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.04 | $0.16 | $0.79 |
| `logs-apps-notifier` | log ingestion | 5.26 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $0.66 | $2.63 | $13.14 |
| `logs-apps-notifier` | log storage | 5.26 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.04 | $0.16 | $0.79 |
| `logs-apps-reports` | log ingestion | 1.00 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $0.50 | $0.50 | $0.50 |
| `logs-apps-reports` | log storage | 1.00 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.03 | $0.03 | $0.03 |
| `logs-apps-users` | log ingestion | 5.26 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $0.66 | $2.63 | $13.14 |
| `logs-apps-users` | log storage | 5.26 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.04 | $0.16 | $0.79 |
| `logs-apps-web` | log ingestion | 5.26 | GB | $0.5 | `TEST/cloudwatch.logs_ingest_gb/cloudwatch.logs_ingest_gb` | $0.66 | $2.63 | $13.14 |
| `logs-apps-web` | log storage | 5.26 | GB-month | $0.03 | `TEST/cloudwatch.logs_storage_gb_month/cloudwatch.logs_storage_gb_month` | $0.04 | $0.16 | $0.79 |
| `vpc-endpoints` | 4 interface endpoints x 2 AZs | 5,840.00 | endpoint-h | $0.01 | `TEST/vpc.endpoint_hour/vpc.endpoint_hour` | $58.40 | $58.40 | $58.40 |
| `vpc-endpoints` | data processed (logs) | 27.28 | GB | $0.01 | `TEST/vpc.endpoint_gb/vpc.endpoint_gb` | $0.08 | $0.27 | $1.32 |
| `rds-postgres` | db.t4g.small instance hours (multi_az) | 730.00 | h | $0.1 | `TEST/rds.instance.postgres.db.t4g.small.multi_az/rds.instance.postgres.db.t4g.small.multi_az` | $73.00 | $73.00 | $73.00 |
| `rds-postgres` | gp3 storage | 20.00 | GB-month | $0.2 | `TEST/rds.storage.gp3.multi_az.postgres/rds.storage.gp3.multi_az.postgres` | $4.00 | $4.00 | $4.00 |
| `elasticache-redis` | cache.t4g.micro node hours x 2 | 1,460.00 | node-h | $0.02 | `TEST/elasticache.node.redis.cache.t4g.micro/elasticache.node.redis.cache.t4g.micro` | $29.20 | $29.20 | $29.20 |
| `secrets` | 3 slots + 1 RDS-managed | 4.00 | secret-month | $0.5 | `TEST/secrets.secret_month/secrets.secret_month` | $2.00 | $2.00 | $2.00 |
| `secrets` | API requests at task start | 180.00 | requests | $1e-05 | `TEST/secrets.api_request/secrets.api_request` | $0.00 | $0.00 | $0.00 |
| `ecr` | 6 repositories | 12.00 | GB-month | $0.1 | `TEST/ecr.storage_gb_month/ecr.storage_gb_month` | $1.20 | $1.20 | $1.20 |
| `internet-egress` | data transfer out to the internet | 131.40 | GB | $0.1 | `TEST/dt.out_gb/dt.out_gb` | $3.29 | $13.14 | $65.70 |
| **Total** |  |  |  |  |  | $380.15 | $402.18 | $519.68 |

## What can bite me

Ranked by severity, then estimated monthly impact.

### 1. no-outbound-path (high)

**Where:** network.tf (enable_nat_gateway = false by default)  
**Impact:** not priced

**Why it bites:** Private tasks have no route to the internet or to AWS APIs that lack an endpoint: services call each other by URL (apps-gateway->apps-billing, apps-gateway->apps-users), i.e. through the public load balancer. Those calls will time out in production.

**Fix:** Either set enable_nat_gateway = true (a NAT gateway bills per hour and per GB processed; its price is not in this forecast), add VPC endpoints for the AWS services you use, or route service-to-service calls through an internal address.

### 2. interface-endpoint-fixed-cost (medium)

**Where:** network.tf (aws_vpc_endpoint.interface)  
**Impact:** about $58.40/month

**Why it bites:** Interface VPC endpoints bill for every AZ-hour whether or not traffic flows. For a small system this fixed cost can exceed the compute it supports.

**Fix:** Keep only the endpoints you need, run one AZ in non-production, or compare against a NAT gateway for your traffic before deciding.

### 3. log-ingestion (medium)

**Where:** ecs.tf (aws_cloudwatch_log_group)  
**Impact:** about $13.64/month

**Why it bites:** CloudWatch bills every GB of logs ingested, and ingestion grows with traffic and log verbosity. At the spike scenario ingestion alone is about $66.20/month.

**Fix:** Log at INFO or above in production, do not log request bodies, sample noisy lines, and keep retention short (set to 30 days here).

### 4. internet-egress (medium)

**Where:** alb.tf / static_site.tf (every service that serves users)  
**Impact:** about $13.14/month

**Why it bites:** Data transferred out to the internet is billed per GB and scales with traffic and response size. At the spike scenario it is about $65.70/month.

**Fix:** Compress responses, cache at a CDN, and avoid returning large payloads by default.

### 5. no-autoscaling (medium)

**Where:** ecs.tf (aws_ecs_service desired_count)  
**Impact:** not priced

**Why it bites:** Task counts are fixed (apps-billing=2, apps-gateway=2, apps-notifier=2, apps-users=2, apps-web=2) and nothing scales them. A traffic spike can saturate the tasks, and quiet periods still pay for full capacity.

**Fix:** Add aws_appautoscaling_target and a target-tracking policy on CPU or request count per service, with sensible minimum and maximum counts.

### 6. redis-replica (low)

**Where:** elasticache.tf (num_cache_clusters)  
**Impact:** about $14.60/month

**Why it bites:** 2 Redis nodes means paying for 1 replica(s) for failover.

**Fix:** Use one node if Redis is only a rebuildable cache; keep replicas if it is a broker or holds data you cannot lose.

### 7. public-ipv4 (low)

**Where:** alb.tf (aws_lb.main)  
**Impact:** about $7.30/month

**Why it bites:** Every public IPv4 address bills per hour; an internet-facing load balancer uses one per AZ.

**Fix:** Accept it for the one shared load balancer; never add a load balancer per service.

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
