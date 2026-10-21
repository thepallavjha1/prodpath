<!-- prodpath 0.0.1 | generated 2000-01-01T00:00:00Z | input 6aa111e46cc7 -->

# Production plan

Target: **AWS**, region `ap-south-1`, environment `prod`. 8 services detected, 33 components planned.

## Services

| Service | Kind | Root | Purpose | Deployed as |
|---|---|---|---|---|
| apps-billing | web | `apps/billing` | (run `prodpath summarize` for a purpose) | ecs-svc-apps-billing |
| apps-gateway | web | `apps/gateway` | (run `prodpath summarize` for a purpose) | ecs-svc-apps-gateway |
| apps-notifier | web | `apps/notifier` | (run `prodpath summarize` for a purpose) | ecs-svc-apps-notifier |
| apps-reports | cron | `apps/reports` | (run `prodpath summarize` for a purpose) | cron-apps-reports |
| apps-users | web | `apps/users` | (run `prodpath summarize` for a purpose) | ecs-svc-apps-users |
| apps-web | web | `apps/web` | (run `prodpath summarize` for a purpose) | ecs-svc-apps-web |
| packages-py-common | lib | `packages/py-common` | (run `prodpath summarize` for a purpose) | not deployed |
| packages-shared-utils | lib | `packages/shared-utils` | (run `prodpath summarize` for a purpose) | not deployed |

## Architecture

| Component | Type | Sizing | Why | Evidence |
|---|---|---|---|---|
| `tf-state` | tf-state | 1 S3 bucket (versioned, encrypted) + 1 lock table | Remote state with locking keeps Terraform safe once more than one person or pipeline applies changes (SECURITY.md section 5). | account-level, no code evidence |
| `github-oidc-role` | iam-github-oidc | 1 IAM role trusted by GitHub Actions via OIDC | CI/CD deploys by assuming a role, so no long-lived AWS keys are stored in GitHub. | account-level, no code evidence |
| `vpc` | vpc | 2 AZs, public + private subnets, S3 and ECR VPC endpoints | Containers and data stores run in private subnets; endpoints avoid NAT data charges for image pulls and S3 traffic. | `apps/billing/Dockerfile:3`<br>`apps/gateway/Dockerfile:3`<br>`apps/notifier/Dockerfile:3` |
| `ecs-cluster` | ecs-cluster | 1 Fargate-only cluster | One cluster runs every container service; Fargate means no servers to patch. | `apps/billing/Dockerfile:3`<br>`apps/gateway/Dockerfile:3`<br>`apps/notifier/Dockerfile:3` |
| `alb` | alb | 1 Application Load Balancer, host/path routing | One shared load balancer for all web services avoids paying for one per service. | `apps/billing/Dockerfile:3`<br>`apps/gateway/Dockerfile:3`<br>`apps/notifier/Dockerfile:3` |
| `ecr-apps-billing` | ecr | 1 repository, scan on push | Stores the container image for apps-billing. | `apps/billing/Dockerfile:3` |
| `ecr-apps-gateway` | ecr | 1 repository, scan on push | Stores the container image for apps-gateway. | `apps/gateway/Dockerfile:3` |
| `ecr-apps-notifier` | ecr | 1 repository, scan on push | Stores the container image for apps-notifier. | `apps/notifier/Dockerfile:3` |
| `ecr-apps-reports` | ecr | 1 repository, scan on push | Stores the container image for apps-reports. | `apps/reports/Dockerfile:1` |
| `ecr-apps-users` | ecr | 1 repository, scan on push | Stores the container image for apps-users. | `apps/users/Dockerfile:3` |
| `ecr-apps-web` | ecr | 1 repository, scan on push | Stores the container image for apps-web. | `apps/web/Dockerfile:3` |
| `rds-postgres` | rds | db.t4g.small, 20 GB gp3, Multi-AZ, backups on | postgres is a managed relational database on RDS. One instance serves every service that uses it (give each its own database and user). | `apps/billing/requirements.txt:2` |
| `elasticache-redis` | elasticache | cache.t4g.micro, 2 nodes, Multi-AZ | Redis (cache, Celery/BullMQ/RQ broker) on ElastiCache. | `apps/users/app.py:1` |
| `secrets-apps-billing` | secrets | 1 secret slot, no values | These variables look like credentials or connection strings. Slots are created empty; set values yourself, out of band. | `apps/billing/app.py:6` |
| `secrets-apps-gateway` | secrets | 2 secret slots, no values | These variables look like credentials or connection strings. Slots are created empty; set values yourself, out of band. | `apps/gateway/server.js:5`<br>`apps/gateway/server.js:6` |
| `logs-apps-billing` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `apps/billing/Dockerfile:3` |
| `logs-apps-gateway` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `apps/gateway/Dockerfile:3` |
| `logs-apps-notifier` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `apps/notifier/Dockerfile:3` |
| `logs-apps-reports` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `apps/reports/Dockerfile:1` |
| `logs-apps-users` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `apps/users/Dockerfile:3` |
| `logs-apps-web` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `apps/web/Dockerfile:3` |
| `role-apps-billing` | iam-task-role | least-privilege task role | apps-billing gets its own role limited to the resources it uses. | `apps/billing/Dockerfile:3` |
| `role-apps-gateway` | iam-task-role | least-privilege task role | apps-gateway gets its own role limited to the resources it uses. | `apps/gateway/Dockerfile:3` |
| `role-apps-notifier` | iam-task-role | least-privilege task role | apps-notifier gets its own role limited to the resources it uses. | `apps/notifier/Dockerfile:3` |
| `role-apps-reports` | iam-task-role | least-privilege task role | apps-reports gets its own role limited to the resources it uses. | `apps/reports/Dockerfile:1` |
| `role-apps-users` | iam-task-role | least-privilege task role | apps-users gets its own role limited to the resources it uses. | `apps/users/Dockerfile:3` |
| `role-apps-web` | iam-task-role | least-privilege task role | apps-web gets its own role limited to the resources it uses. | `apps/web/Dockerfile:3` |
| `ecs-svc-apps-billing` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `apps/billing/Dockerfile:3` |
| `ecs-svc-apps-gateway` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `apps/gateway/Dockerfile:3` |
| `ecs-svc-apps-notifier` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `apps/notifier/Dockerfile:3` |
| `ecs-svc-apps-users` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `apps/users/Dockerfile:3` |
| `ecs-svc-apps-web` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `apps/web/Dockerfile:3` |
| `cron-apps-reports` | scheduled-task | Fargate 0.25 vCPU / 0.5 GB per run | Scheduled job: EventBridge Scheduler starts a one-off Fargate task. | `apps/reports/Dockerfile:1` |

## Steps

Commands use `<PLACEHOLDERS>` for values only you know.

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

### 3. Review and apply the generated Terraform

One reviewed plan creates the network, load balancer, data stores, repositories, roles, secret slots and services together. Read the plan before applying; this tool has not touched your account.

```bash
cd .prodpath/out/terraform
cp terraform.tfvars.example terraform.tfvars   # then fill in every <PLACEHOLDER>
terraform init -backend-config="bucket=<STATE_BUCKET>" -backend-config="key=<APP_NAME>/prod/terraform.tfstate" -backend-config="region=ap-south-1" -backend-config="dynamodb_table=<LOCK_TABLE>" -backend-config="encrypt=true"
terraform plan -out=tfplan
terraform apply tfplan
```

**Verify:** `terraform plan` shows only what you expect; `terraform output` lists ECR repository URLs, secret slots and data store endpoints.

### 4. Fill the secret slots yourself

The slots exist but are empty: this tool only knows variable names, never values. Read values from a file, not the command line, so they stay out of shell history. Database URLs: use the host from `terraform output data_store_endpoints` and the master credentials from `rds_master_secret_arns`, ideally a separate user per service.

```bash
aws secretsmanager put-secret-value --secret-id prod/apps-billing/DATABASE_URL --secret-string file://<PATH_TO_FILE_HOLDING_THE_VALUE>
aws secretsmanager put-secret-value --secret-id prod/apps-gateway/BILLING_URL --secret-string file://<PATH_TO_FILE_HOLDING_THE_VALUE>
aws secretsmanager put-secret-value --secret-id prod/apps-gateway/USERS_URL --secret-string file://<PATH_TO_FILE_HOLDING_THE_VALUE>
```

**Verify:** aws secretsmanager list-secrets shows every slot; none hold placeholder text.

### 5. Build and push the first images

Services stay pending until their image tag exists in ECR. Tag with the git SHA (repositories are immutable, so 'latest' cannot be reused).

```bash
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com
docker build -t <ECR_URL_FOR_APPS_BILLING>:<GIT_SHA> <PATH_TO_APPS_BILLING>
docker push <ECR_URL_FOR_APPS_BILLING>:<GIT_SHA>
docker build -t <ECR_URL_FOR_APPS_GATEWAY>:<GIT_SHA> <PATH_TO_APPS_GATEWAY>
docker push <ECR_URL_FOR_APPS_GATEWAY>:<GIT_SHA>
docker build -t <ECR_URL_FOR_APPS_NOTIFIER>:<GIT_SHA> <PATH_TO_APPS_NOTIFIER>
docker push <ECR_URL_FOR_APPS_NOTIFIER>:<GIT_SHA>
docker build -t <ECR_URL_FOR_APPS_REPORTS>:<GIT_SHA> <PATH_TO_APPS_REPORTS>
docker push <ECR_URL_FOR_APPS_REPORTS>:<GIT_SHA>
docker build -t <ECR_URL_FOR_APPS_USERS>:<GIT_SHA> <PATH_TO_APPS_USERS>
docker push <ECR_URL_FOR_APPS_USERS>:<GIT_SHA>
docker build -t <ECR_URL_FOR_APPS_WEB>:<GIT_SHA> <PATH_TO_APPS_WEB>
docker push <ECR_URL_FOR_APPS_WEB>:<GIT_SHA>
aws ecs update-service --cluster <CLUSTER_NAME> --service apps-billing --force-new-deployment
aws ecs update-service --cluster <CLUSTER_NAME> --service apps-gateway --force-new-deployment
aws ecs update-service --cluster <CLUSTER_NAME> --service apps-notifier --force-new-deployment
aws ecs update-service --cluster <CLUSTER_NAME> --service apps-users --force-new-deployment
aws ecs update-service --cluster <CLUSTER_NAME> --service apps-web --force-new-deployment
```

**Verify:** aws ecr describe-images lists the tag; services reach steady state.

### 6. Wire GitHub Actions to the deploy role

Terraform created a role that only your repository and branch can assume through OIDC, so no AWS keys are stored in GitHub.

```bash
# In your workflow: permissions: { id-token: write, contents: read }
# uses: aws-actions/configure-aws-credentials with role-to-assume: <terraform output github_actions_role_arn>
# Then: build, push the image tagged with the git SHA, register a new task definition revision, aws ecs update-service
```

**Verify:** A workflow run on the allowed branch assumes the role and deploys; other branches are denied.

### 7. Add alarms (not generated yet)

Log groups and their retention come from Terraform. Alarms are not generated in this version; without them nobody is told when something breaks.

```bash
# Suggested minimum: ALB 5xx rate and unhealthy host count, ECS service CPU and memory, RDS CPU, free storage and connections, and an SNS topic or chat webhook
```

**Verify:** Trigger a test alarm and confirm you receive the notification.

### 8. Know how to roll back before you need to

Rollback is easiest when decided in advance.

```bash
# Services: aws ecs update-service --cluster <CLUSTER_NAME> --service <SERVICE> --task-definition <PREVIOUS_TASK_DEFINITION_ARN>
# Databases: take a manual snapshot before every migration (aws rds create-db-snapshot ...); never run a destructive migration without one
```

**Verify:** Practice one rollback in a non-production environment.

### 9. Verify the deployment end to end

Health endpoints and logs are the first evidence the system works.

```bash
curl -fsS https://<HOST_FOR_ECS_SVC_APPS_BILLING>/<HEALTH_PATH?>
curl -fsS https://<HOST_FOR_ECS_SVC_APPS_GATEWAY>/health
curl -fsS https://<HOST_FOR_ECS_SVC_APPS_NOTIFIER>/health
curl -fsS https://<HOST_FOR_ECS_SVC_APPS_USERS>/<HEALTH_PATH?>
curl -fsS https://<HOST_FOR_ECS_SVC_APPS_WEB>/health
# Check CloudWatch logs for errors and confirm every secret slot has a value
```

**Verify:** Every web service answers its health check; no errors in the logs for 15 minutes.


## Terraform

17 files were written to `.prodpath/out/terraform/`: `README.md`, `alb.tf`, `backend.tf`, `ecr.tf`, `ecs.tf`, `elasticache.tf`, `github_oidc.tf`, `iam.tf`, `main.tf`, `network.tf`, `outputs.tf`, `rds.tf`, `scheduler.tf`, `secrets.tf`, `terraform.tfvars.example`, `variables.tf`, `versions.tf`.

**Checks run by this tool**

- self-scan: passed: no account ids, keys or literal secrets found
- terraform fmt: not run: terraform is not on PATH
- terraform validate: not run: terraform is not on PATH

**Terraform coverage**

Every planned component has a template.

`terraform validate` checks syntax and provider schema, not whether the design is right or safe for your account. Read `terraform plan` before applying.

## Risks

No specific risks were derived. See the unknowns below.

## Unknowns and open questions

- Domain name and ACM certificate are needed for HTTPS on the load balancer.
- Redis: in-transit encryption is on, so clients must connect with TLS (rediss://); check each service's Redis client settings.
- Traffic and data volume are unknown: all sizing is a default starting point.
- apps-reports: the schedule was not extracted; set the cron expression yourself.
- apps-reports: writes local files; container disk is ephemeral. Move that state to S3 or a database before relying on it.
- apps-web: writes local files; container disk is ephemeral. Move that state to S3 or a database before relying on it.
- Confirm the AWS region (assumed `ap-south-1`).

## Not analyzed

- nothing was skipped

## What this plan is based on

- 2 of 29 extracted facts are heuristic (pattern matches, not parsed).
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
