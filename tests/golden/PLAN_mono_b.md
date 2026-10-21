<!-- prodpath 0.0.1 | generated 2000-01-01T00:00:00Z | input 89126761a2d3 -->

# Production plan

Target: **AWS**, region `ap-south-1`, environment `prod`. 2 services detected, 16 components planned.

## Services

| Service | Kind | Root | Purpose | Deployed as |
|---|---|---|---|---|
| api | web | `api` | (run `prodpath summarize` for a purpose) | ecs-svc-api |
| worker | worker | `worker` | (run `prodpath summarize` for a purpose) | ecs-svc-worker |

## Architecture

| Component | Type | Sizing | Why | Evidence |
|---|---|---|---|---|
| `tf-state` | tf-state | 1 S3 bucket (versioned, encrypted) + 1 lock table | Remote state with locking keeps Terraform safe once more than one person or pipeline applies changes (SECURITY.md section 5). | account-level, no code evidence |
| `github-oidc-role` | iam-github-oidc | 1 IAM role trusted by GitHub Actions via OIDC | CI/CD deploys by assuming a role, so no long-lived AWS keys are stored in GitHub. | account-level, no code evidence |
| `vpc` | vpc | 2 AZs, public + private subnets, S3 and ECR VPC endpoints | Containers and data stores run in private subnets; endpoints avoid NAT data charges for image pulls and S3 traffic. | `api/Dockerfile:4`<br>`worker/requirements.txt:1` |
| `ecs-cluster` | ecs-cluster | 1 Fargate-only cluster | One cluster runs every container service; Fargate means no servers to patch. | `api/Dockerfile:4`<br>`worker/requirements.txt:1` |
| `alb` | alb | 1 Application Load Balancer, host/path routing | One shared load balancer for all web services avoids paying for one per service. | `api/Dockerfile:4` |
| `ecr-api` | ecr | 1 repository, scan on push | Stores the container image for api. | `api/Dockerfile:4` |
| `ecr-worker` | ecr | 1 repository, scan on push | Stores the container image for worker. | `worker/requirements.txt:1` |
| `elasticache-redis` | elasticache | cache.t4g.micro, 2 nodes, Multi-AZ | Redis (cache, Celery/BullMQ/RQ broker) on ElastiCache. | `api/requirements.txt:3`<br>`docker-compose.yml:6` |
| `secrets-api` | secrets | 1 secret slot, no values | These variables look like credentials or connection strings. Slots are created empty; set values yourself, out of band. | `api/main.py:7` |
| `secrets-worker` | secrets | 1 secret slot, no values | These variables look like credentials or connection strings. Slots are created empty; set values yourself, out of band. | `docker-compose.yml:6` |
| `logs-api` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `api/Dockerfile:4` |
| `logs-worker` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `worker/requirements.txt:1` |
| `role-api` | iam-task-role | least-privilege task role | api gets its own role limited to the resources it uses. | `api/Dockerfile:4` |
| `role-worker` | iam-task-role | least-privilege task role | worker gets its own role limited to the resources it uses. | `worker/requirements.txt:1` |
| `ecs-svc-api` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `api/Dockerfile:4` |
| `ecs-svc-worker` | ecs-service-worker | Fargate 0.25 vCPU / 0.5 GB, 2 tasks (default) | Background worker: a Fargate service with no load balancer. | `worker/requirements.txt:1` |

## Steps

Commands use `<PLACEHOLDERS>` for values only you know. Terraform for these resources is not generated yet, so these are the by-hand route.

### 1. Prepare the AWS account and a budget alarm

Cost surprises are the most common first-month problem; set an alarm before creating anything billable. This tool never sees your credentials, so you run these.

```bash
aws sso login --profile <PROFILE>   # or any login method you already use
aws sts get-caller-identity --profile <PROFILE>
# In the Billing console: create a monthly budget with an e-mail alert at a figure you are comfortable with.
```

**Verify:** get-caller-identity prints the account you expect; the budget alert exists.

### 2. Create the remote state bucket and lock table

Terraform state must be shared, versioned, encrypted and locked (needed once Terraform is applied; Phase 5 generates it).

```bash
aws s3api create-bucket --bucket <STATE_BUCKET> --region ap-south-1 --create-bucket-configuration LocationConstraint=ap-south-1
aws s3api put-bucket-versioning --bucket <STATE_BUCKET> --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket <STATE_BUCKET> --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket <STATE_BUCKET> --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws dynamodb create-table --table-name <LOCK_TABLE> --region ap-south-1 --attribute-definitions AttributeName=LockID,AttributeType=S --key-schema AttributeName=LockID,KeyType=HASH --billing-mode PAY_PER_REQUEST
```

**Verify:** aws s3api get-bucket-versioning --bucket <STATE_BUCKET> shows Status: Enabled.

### 3. Create the VPC, subnets and VPC endpoints

Containers and data stores live in private subnets. S3 and ECR endpoints keep image pulls and S3 traffic off the NAT gateway, which bills per hour and per GB processed.

```bash
aws ec2 create-vpc --cidr-block 10.0.0.0/16 --region ap-south-1
# Create 2 public and 2 private subnets in different AZs (aws ec2 create-subnet ...)
# Create an internet gateway, attach it, route the public subnets to it
aws ec2 create-vpc-endpoint --vpc-id <VPC_ID> --service-name com.amazonaws.ap-south-1.s3 --route-table-ids <PRIVATE_ROUTE_TABLE_ID>
# Interface endpoints for com.amazonaws.ap-south-1.ecr.api, .ecr.dkr and .logs
# Add a NAT gateway only if a private service must reach the public internet
```

**Verify:** aws ec2 describe-vpc-endpoints lists the S3 and ECR endpoints as available.

### 4. Create data stores, caches, queues and buckets

Services need these before they can start. Encryption and private access are on by default in the commands; do not turn them off to make something connect.

```bash
aws elasticache create-replication-group --replication-group-id elasticache-redis --replication-group-description <DESC> --engine redis --cache-node-type cache.t4g.micro --at-rest-encryption-enabled --transit-encryption-enabled --cache-subnet-group-name <PRIVATE_SUBNET_GROUP>
```

**Verify:** Each resource shows 'available' and is not publicly accessible.

### 5. Create empty secret slots, then fill them yourself

This tool only knows variable names, never values, so it cannot and should not set them.

```bash
aws secretsmanager create-secret --name prod/api/REDIS_URL
aws secretsmanager create-secret --name prod/worker/REDIS_URL
# Then set each value yourself, out of band: aws secretsmanager put-secret-value ...
```

**Verify:** aws secretsmanager list-secrets shows every slot; none contain placeholder text.

### 6. Create image repositories and push the first images

Services cannot be created before an image exists. Tag with the git SHA, never 'latest'.

```bash
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com
aws ecr create-repository --repository-name ecr-api --image-scanning-configuration scanOnPush=true
docker build -t <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/ecr-api:<GIT_SHA> <PATH_TO_API>
docker push <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/ecr-api:<GIT_SHA>
aws ecr create-repository --repository-name ecr-worker --image-scanning-configuration scanOnPush=true
docker build -t <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/ecr-worker:<GIT_SHA> <PATH_TO_WORKER>
docker push <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/ecr-worker:<GIT_SHA>
```

**Verify:** aws ecr describe-images --repository-name <REPO> lists the pushed tag.

### 7. Create the cluster, load balancer and services

Each service runs from its image with its own task role and its secrets injected from Secrets Manager, not baked into the image.

```bash
aws ecs create-cluster --cluster-name <CLUSTER_NAME>
aws elbv2 create-load-balancer --name <ALB_NAME> --subnets <PUBLIC_SUBNET_IDS> --security-groups <ALB_SG>
# Add an HTTPS listener with your ACM certificate; redirect HTTP to HTTPS
# ecs-svc-api: container port 8000, target-group health check <HEALTH_PATH?>
aws ecs create-service --cluster <CLUSTER_NAME> --service-name ecs-svc-api --launch-type FARGATE ...
aws ecs create-service --cluster <CLUSTER_NAME> --service-name ecs-svc-worker --launch-type FARGATE ...
```

**Verify:** Services reach steady state; target groups report healthy.

### 8. Set up GitHub Actions deploys through OIDC

A role assumed through OIDC means no AWS keys stored in GitHub.

```bash
aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com
# Create a role trusted by that provider, restricted to your repo and branch (sub = repo:<ORG>/<REPO>:ref:refs/heads/main), with permission to push to ECR and update the services
```

**Verify:** A workflow run assumes the role (aws-actions/configure-aws-credentials) and pushes an image.

### 9. Set log retention and basic alarms

Logs without retention grow and bill forever; an alarm on 5xx and unhealthy targets tells you before users do.

```bash
aws logs create-log-group --log-group-name /<APP>/logs-api --region ap-south-1
aws logs create-log-group --log-group-name /<APP>/logs-worker --region ap-south-1
aws logs put-retention-policy --log-group-name /<APP>/logs-api --retention-in-days 30
aws logs put-retention-policy --log-group-name /<APP>/logs-worker --retention-in-days 30
```

**Verify:** aws logs describe-log-groups shows retentionInDays on every group.

### 10. Know how to roll back before you need to

Rollback is easiest when decided in advance.

```bash
# Services: aws ecs update-service --cluster <CLUSTER_NAME> --service <SERVICE> --task-definition <PREVIOUS_TASK_DEFINITION_ARN>
# Databases: take a manual snapshot before every migration (aws rds create-db-snapshot ...); never run a destructive migration without one
```

**Verify:** Practice one rollback in a non-production environment.

### 11. Verify the deployment end to end

Health endpoints and logs are the first evidence the system works.

```bash
curl -fsS https://<HOST_FOR_ECS_SVC_API>/<HEALTH_PATH?>
# Check CloudWatch logs for errors and confirm every secret slot has a value
```

**Verify:** Every web service answers its health check; no errors in the logs for 15 minutes.


## Risks

- `elasticache-redis` is shared by api, worker: one outage or heavy query affects all of them. Split it if you need isolation.

## Unknowns and open questions

- Domain name and ACM certificate are needed for HTTPS on the load balancer.
- Traffic and data volume are unknown: all sizing is a default starting point.
- Confirm the AWS region (assumed `ap-south-1`).

## Not analyzed

- nothing was skipped

## What this plan is based on

- 0 of 12 extracted facts are heuristic (pattern matches, not parsed).
- All sizing and counts are defaults; there is no traffic data (see unknowns).
- No model summaries were used (`.prodpath/summaries.json` not found).
- Environment assumed: `prod`; region: `ap-south-1`.

## Not verified by this tool

- Load and performance: sizing is a default, not a measurement.
- Compliance and legal requirements (data residency, audit, PCI/HIPAA and similar).
- Account-level controls: organizations, SCPs, guardrails, existing networking.
- Real traffic patterns, data growth, and anything that only shows up at runtime.
- That the commands run unchanged in your account: placeholders must be filled and limits/quotas checked.
- Security of your application code. This plan covers infrastructure defaults only.
