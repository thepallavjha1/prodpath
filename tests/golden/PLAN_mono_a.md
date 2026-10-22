<!-- prodpath 0.0.1 | generated 2000-01-01T00:00:00Z | input c967c44e8eb8 -->

# Production plan

Target: **AWS**, region `ap-south-1`, environment `prod`. 1 services detected, 15 components planned.

## Services

| Service | Kind | Root | Purpose | Deployed as |
|---|---|---|---|---|
| root | web | `.` | (run `prodpath summarize` for a purpose) | ecs-svc-root |

## Architecture

| Component | Type | Sizing | Why | Evidence |
|---|---|---|---|---|
| `tf-state` | tf-state | 1 S3 bucket (versioned, encrypted) + 1 lock table | Remote state with locking keeps Terraform safe once more than one person or pipeline applies changes (SECURITY.md section 5). | account-level, no code evidence |
| `github-oidc-role` | iam-github-oidc | 1 IAM role trusted by GitHub Actions via OIDC | CI/CD deploys by assuming a role, so no long-lived AWS keys are stored in GitHub. | account-level, no code evidence |
| `vpc` | vpc | 2 AZs, public + private subnets, S3 and ECR VPC endpoints | Containers and data stores run in private subnets; endpoints avoid NAT data charges for image pulls and S3 traffic. | `Dockerfile:5` |
| `ecs-cluster` | ecs-cluster | 1 Fargate-only cluster | One cluster runs every container service; Fargate means no servers to patch. | `Dockerfile:5` |
| `alb` | alb | 1 Application Load Balancer, host/path routing | One shared load balancer for all web services avoids paying for one per service. | `Dockerfile:5` |
| `ecr-root` | ecr | 1 repository, scan on push | Stores the container image for root. | `Dockerfile:5` |
| `rds-postgres` | rds | db.t4g.small, 20 GB gp3, Multi-AZ, backups on | postgres is a managed relational database on RDS. One instance serves every service that uses it (give each its own database and user). | `requirements.txt:2` |
| `s3-root` | s3 | private bucket, encryption on, versioning on | Code uses object storage (S3). Bucket names were not extracted. | `app/config.py:4` |
| `secrets-root` | secrets | 2 secret slots, no values | These variables look like credentials or connection strings. Slots are created empty; set values yourself, out of band. | `.env:1`<br>`.env:2` |
| `logs-root` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `Dockerfile:5` |
| `role-root` | iam-task-role | least-privilege task role | root gets its own role limited to the resources it uses. | `Dockerfile:5` |
| `ecs-svc-root` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `Dockerfile:5` |
| `autoscaling-root` | autoscaling | 2 to 10 tasks, target CPU 60% | Scales root with load instead of a fixed task count; the bounds are defaults and live in var.service_scaling. | `Dockerfile:5` |
| `alerts` | sns-alerts | 1 topic, e-mail subscription | One place where every alarm is delivered. The topic is not KMS-encrypted because CloudWatch cannot publish to a topic that uses the AWS-managed key. | `Dockerfile:5` |
| `alarms` | alarms | CloudWatch alarms on errors, saturation, storage and queue depth | Without alarms nobody is told when a service, database or queue starts failing. | `Dockerfile:5` |

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
aws secretsmanager put-secret-value --secret-id prod/root/DATABASE_URL --secret-string file://<PATH_TO_FILE_HOLDING_THE_VALUE>
aws secretsmanager put-secret-value --secret-id prod/root/FLASK_SECRET --secret-string file://<PATH_TO_FILE_HOLDING_THE_VALUE>
```

**Verify:** aws secretsmanager list-secrets shows every slot; none hold placeholder text.

### 5. Build and push the first images

Services stay pending until their image tag exists in ECR. Tag with the git SHA (repositories are immutable, so 'latest' cannot be reused).

```bash
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com
docker build -t <ECR_URL_FOR_ROOT>:<GIT_SHA> <PATH_TO_ROOT>
docker push <ECR_URL_FOR_ROOT>:<GIT_SHA>
aws ecs update-service --cluster <CLUSTER_NAME> --service root --force-new-deployment
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

### 7. Confirm alert notifications and check autoscaling

Terraform created the alarms, the alerts topic and the autoscaling policies. The e-mail subscription is the one manual part: AWS only starts delivering after the confirmation link in alert_email's inbox is clicked. Thresholds are defaults; tune them once you know normal behaviour.

```bash
# Open the e-mail AWS sent to the alert_email address in terraform.tfvars and click 'Confirm subscription'. Until you do, no alarm reaches anyone.
aws sns list-subscriptions-by-topic --topic-arn <ALERTS_TOPIC_ARN>   # SubscriptionArn must not say PendingConfirmation
aws cloudwatch set-alarm-state --alarm-name <ALARM_NAME> --state-value ALARM --state-reason "notification test"
aws application-autoscaling describe-scaling-policies --service-namespace ecs   # one CPU policy per service; min/max come from var.service_scaling
```

**Verify:** A test alarm e-mail arrives, and each scalable service shows a scaling policy.

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
curl -fsS https://<HOST_FOR_ECS_SVC_ROOT>/health
# Check CloudWatch logs for errors and confirm every secret slot has a value
```

**Verify:** Every web service answers its health check; no errors in the logs for 15 minutes.


## Terraform

18 files were written to `.prodpath/out/terraform/`: `README.md`, `alarms.tf`, `alb.tf`, `autoscaling.tf`, `backend.tf`, `ecr.tf`, `ecs.tf`, `github_oidc.tf`, `iam.tf`, `main.tf`, `network.tf`, `outputs.tf`, `rds.tf`, `s3.tf`, `secrets.tf`, `terraform.tfvars.example`, `variables.tf`, `versions.tf`.

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

- Alarm thresholds are defaults, and alerts reach nobody until the e-mail subscription for var.alert_email is confirmed.
- Domain name and ACM certificate are needed for HTTPS on the load balancer.
- Traffic and data volume are unknown: all sizing is a default starting point.
- root: writes local files; container disk is ephemeral. Move that state to S3 or a database before relying on it.
- Confirm the AWS region (assumed `ap-south-1`).

## Not analyzed

- nothing was skipped

## What this plan is based on

- 1 of 11 extracted facts are heuristic (pattern matches, not parsed).
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
