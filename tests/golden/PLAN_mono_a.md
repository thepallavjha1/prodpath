<!-- prodpath 0.0.1 | generated 2000-01-01T00:00:00Z | input fc0b968ea948 -->

# Production plan

Target: **AWS**, region `ap-south-1`, environment `prod`. 1 services detected, 12 components planned.

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
aws rds create-db-instance --db-instance-identifier rds-postgres --engine postgres --db-instance-class <INSTANCE_CLASS> --allocated-storage 20 --storage-encrypted --multi-az --backup-retention-period 7 --manage-master-user-password --master-username <ADMIN_USER> --db-subnet-group-name <PRIVATE_SUBNET_GROUP> --no-publicly-accessible
aws s3api create-bucket --bucket <S3-ROOT_BUCKET> --region ap-south-1
```

**Verify:** Each resource shows 'available' and is not publicly accessible.

### 5. Create empty secret slots, then fill them yourself

This tool only knows variable names, never values, so it cannot and should not set them.

```bash
aws secretsmanager create-secret --name prod/root/DATABASE_URL
aws secretsmanager create-secret --name prod/root/FLASK_SECRET
# Then set each value yourself, out of band: aws secretsmanager put-secret-value ...
```

**Verify:** aws secretsmanager list-secrets shows every slot; none contain placeholder text.

### 6. Create image repositories and push the first images

Services cannot be created before an image exists. Tag with the git SHA, never 'latest'.

```bash
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com
aws ecr create-repository --repository-name ecr-root --image-scanning-configuration scanOnPush=true
docker build -t <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/ecr-root:<GIT_SHA> <PATH_TO_ROOT>
docker push <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/ecr-root:<GIT_SHA>
```

**Verify:** aws ecr describe-images --repository-name <REPO> lists the pushed tag.

### 7. Create the cluster, load balancer and services

Each service runs from its image with its own task role and its secrets injected from Secrets Manager, not baked into the image.

```bash
aws ecs create-cluster --cluster-name <CLUSTER_NAME>
aws elbv2 create-load-balancer --name <ALB_NAME> --subnets <PUBLIC_SUBNET_IDS> --security-groups <ALB_SG>
# Add an HTTPS listener with your ACM certificate; redirect HTTP to HTTPS
# ecs-svc-root: container port 8000, target-group health check /health
aws ecs create-service --cluster <CLUSTER_NAME> --service-name ecs-svc-root --launch-type FARGATE ...
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
aws logs create-log-group --log-group-name /<APP>/logs-root --region ap-south-1
aws logs put-retention-policy --log-group-name /<APP>/logs-root --retention-in-days 30
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
curl -fsS https://<HOST_FOR_ECS_SVC_ROOT>/health
# Check CloudWatch logs for errors and confirm every secret slot has a value
```

**Verify:** Every web service answers its health check; no errors in the logs for 15 minutes.


## Risks

No specific risks were derived. See the unknowns below.

## Unknowns and open questions

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
