<!-- prodpath 0.0.1 | generated 2000-01-01T00:00:00Z | input 3c55f899e877 -->

# Production plan

Target: **AWS**, region `ap-south-1`, environment `prod`. 5 services detected, 21 components planned.

## Services

| Service | Kind | Root | Purpose | Deployed as |
|---|---|---|---|---|
| apps-api | web | `apps/api` | (run `prodpath summarize` for a purpose) | ecs-svc-apps-api |
| apps-dashboard | web | `apps/dashboard` | (run `prodpath summarize` for a purpose) | ecs-svc-apps-dashboard |
| apps-docs | static | `apps/docs` | (run `prodpath summarize` for a purpose) | cloudfront-apps-docs |
| apps-marketing | static | `apps/marketing` | (run `prodpath summarize` for a purpose) | cloudfront-apps-marketing |
| apps-spa | static | `apps/spa` | (run `prodpath summarize` for a purpose) | cloudfront-apps-spa |

## Architecture

| Component | Type | Sizing | Why | Evidence |
|---|---|---|---|---|
| `tf-state` | tf-state | 1 S3 bucket (versioned, encrypted) + 1 lock table | Remote state with locking keeps Terraform safe once more than one person or pipeline applies changes (SECURITY.md section 5). | account-level, no code evidence |
| `github-oidc-role` | iam-github-oidc | 1 IAM role trusted by GitHub Actions via OIDC | CI/CD deploys by assuming a role, so no long-lived AWS keys are stored in GitHub. | account-level, no code evidence |
| `vpc` | vpc | 2 AZs, public + private subnets, S3 and ECR VPC endpoints | Containers and data stores run in private subnets; endpoints avoid NAT data charges for image pulls and S3 traffic. | `apps/api/Dockerfile:4`<br>`apps/dashboard/package.json:4` |
| `ecs-cluster` | ecs-cluster | 1 Fargate-only cluster | One cluster runs every container service; Fargate means no servers to patch. | `apps/api/Dockerfile:4`<br>`apps/dashboard/package.json:4` |
| `alb` | alb | 1 Application Load Balancer, host/path routing | One shared load balancer for all web services avoids paying for one per service. | `apps/api/Dockerfile:4`<br>`apps/dashboard/package.json:4` |
| `ecr-apps-api` | ecr | 1 repository, scan on push | Stores the container image for apps-api. | `apps/api/Dockerfile:4` |
| `ecr-apps-dashboard` | ecr | 1 repository, scan on push | Stores the container image for apps-dashboard. | `apps/dashboard/package.json:4` |
| `rds-postgres` | rds | db.t4g.small, 20 GB gp3, Multi-AZ, backups on | postgres is a managed relational database on RDS. One instance serves every service that uses it (give each its own database and user). | `apps/api/requirements.txt:2` |
| `s3-site-apps-docs` | s3-site | private bucket, encryption on, versioning on | Holds the built files of apps-docs; only CloudFront can read them. | `apps/docs/Dockerfile:8` |
| `s3-site-apps-marketing` | s3-site | private bucket, encryption on, versioning on | Holds the built files of apps-marketing; only CloudFront can read them. | `apps/marketing/package.json:4` |
| `s3-site-apps-spa` | s3-site | private bucket, encryption on, versioning on | Holds the built files of apps-spa; only CloudFront can read them. | `apps/spa/package.json:4` |
| `cloudfront-apps-docs` | cloudfront | 1 distribution, HTTPS only, TLS 1.2+, compression, PriceClass_All | apps-docs is a static build: a CDN in front of S3 gives HTTPS, caching and low latency with no servers to run. | `apps/docs/Dockerfile:8` |
| `cloudfront-apps-marketing` | cloudfront | 1 distribution, HTTPS only, TLS 1.2+, compression, PriceClass_All | apps-marketing is a static build: a CDN in front of S3 gives HTTPS, caching and low latency with no servers to run. | `apps/marketing/package.json:4` |
| `cloudfront-apps-spa` | cloudfront | 1 distribution, HTTPS only, TLS 1.2+, compression, PriceClass_All | apps-spa is a static build: a CDN in front of S3 gives HTTPS, caching and low latency with no servers to run. | `apps/spa/package.json:4` |
| `secrets-apps-api` | secrets | 1 secret slot, no values | These variables look like credentials or connection strings. Slots are created empty; set values yourself, out of band. | `apps/api/app.py:6` |
| `logs-apps-api` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `apps/api/Dockerfile:4` |
| `logs-apps-dashboard` | log-group | retention 30 days | CloudWatch logs with an explicit retention so they cannot grow forever. | `apps/dashboard/package.json:4` |
| `role-apps-api` | iam-task-role | least-privilege task role | apps-api gets its own role limited to the resources it uses. | `apps/api/Dockerfile:4` |
| `role-apps-dashboard` | iam-task-role | least-privilege task role | apps-dashboard gets its own role limited to the resources it uses. | `apps/dashboard/package.json:4` |
| `ecs-svc-apps-api` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `apps/api/Dockerfile:4` |
| `ecs-svc-apps-dashboard` | ecs-service-web | Fargate 0.5 vCPU / 1 GB, 2 tasks (default) | Stateless HTTP container behind the shared load balancer. | `apps/dashboard/package.json:4` |

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
aws secretsmanager put-secret-value --secret-id prod/apps-api/DATABASE_URL --secret-string file://<PATH_TO_FILE_HOLDING_THE_VALUE>
```

**Verify:** aws secretsmanager list-secrets shows every slot; none hold placeholder text.

### 5. Build and push the first images

Services stay pending until their image tag exists in ECR. Tag with the git SHA (repositories are immutable, so 'latest' cannot be reused).

```bash
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com
docker build -t <ECR_URL_FOR_APPS_API>:<GIT_SHA> <PATH_TO_APPS_API>
docker push <ECR_URL_FOR_APPS_API>:<GIT_SHA>
docker build -t <ECR_URL_FOR_APPS_DASHBOARD>:<GIT_SHA> <PATH_TO_APPS_DASHBOARD>
docker push <ECR_URL_FOR_APPS_DASHBOARD>:<GIT_SHA>
aws ecs update-service --cluster <CLUSTER_NAME> --service apps-api --force-new-deployment
aws ecs update-service --cluster <CLUSTER_NAME> --service apps-dashboard --force-new-deployment
```

**Verify:** aws ecr describe-images lists the tag; services reach steady state.

### 6. Build and publish the static sites

Static sites are plain files in a private bucket behind CloudFront. Upload the build output, invalidate the cache so visitors get it, and point your domain at the distribution.

```bash
# apps-docs: build and upload
cd <PATH_TO_APPS_DOCS>
npm ci && npm run build
aws s3 sync dist/ s3://<BUCKET_FOR_APPS_DOCS> --delete   # terraform output site_buckets
aws cloudfront create-invalidation --distribution-id <DISTRIBUTION_ID_FOR_APPS_DOCS> --paths "/*"
# DNS: point apps-docs.<YOUR_DOMAIN> at <DISTRIBUTION_DOMAIN_FOR_APPS_DOCS> (terraform output site_distributions): a CNAME, or an alias record in Route 53
# apps-marketing: build and upload
cd <PATH_TO_APPS_MARKETING>
npm ci && npm run build
aws s3 sync out/ s3://<BUCKET_FOR_APPS_MARKETING> --delete   # terraform output site_buckets
aws cloudfront create-invalidation --distribution-id <DISTRIBUTION_ID_FOR_APPS_MARKETING> --paths "/*"
# DNS: point apps-marketing.<YOUR_DOMAIN> at <DISTRIBUTION_DOMAIN_FOR_APPS_MARKETING> (terraform output site_distributions): a CNAME, or an alias record in Route 53
# apps-spa: build and upload
cd <PATH_TO_APPS_SPA>
npm ci && npm run build
aws s3 sync dist/ s3://<BUCKET_FOR_APPS_SPA> --delete   # terraform output site_buckets
aws cloudfront create-invalidation --distribution-id <DISTRIBUTION_ID_FOR_APPS_SPA> --paths "/*"
# DNS: point apps-spa.<YOUR_DOMAIN> at <DISTRIBUTION_DOMAIN_FOR_APPS_SPA> (terraform output site_distributions): a CNAME, or an alias record in Route 53
```

**Verify:** Each site loads over HTTPS on its own domain and a deep link returns the app.

### 7. Wire GitHub Actions to the deploy role

Terraform created a role that only your repository and branch can assume through OIDC, so no AWS keys are stored in GitHub.

```bash
# In your workflow: permissions: { id-token: write, contents: read }
# uses: aws-actions/configure-aws-credentials with role-to-assume: <terraform output github_actions_role_arn>
# Then: build, push the image tagged with the git SHA, register a new task definition revision, aws ecs update-service
```

**Verify:** A workflow run on the allowed branch assumes the role and deploys; other branches are denied.

### 8. Add alarms (not generated yet)

Log groups and their retention come from Terraform. Alarms are not generated in this version; without them nobody is told when something breaks.

```bash
# Suggested minimum: ALB 5xx rate and unhealthy host count, ECS service CPU and memory, RDS CPU, free storage and connections, and an SNS topic or chat webhook
```

**Verify:** Trigger a test alarm and confirm you receive the notification.

### 9. Know how to roll back before you need to

Rollback is easiest when decided in advance.

```bash
# Services: aws ecs update-service --cluster <CLUSTER_NAME> --service <SERVICE> --task-definition <PREVIOUS_TASK_DEFINITION_ARN>
# Databases: take a manual snapshot before every migration (aws rds create-db-snapshot ...); never run a destructive migration without one
```

**Verify:** Practice one rollback in a non-production environment.

### 10. Verify the deployment end to end

Health endpoints and logs are the first evidence the system works.

```bash
curl -fsS https://<HOST_FOR_ECS_SVC_APPS_API>/health
curl -fsS https://<HOST_FOR_ECS_SVC_APPS_DASHBOARD>/<HEALTH_PATH?>
curl -fsS https://apps-docs.<YOUR_DOMAIN>/
curl -fsS https://apps-marketing.<YOUR_DOMAIN>/
curl -fsS https://apps-spa.<YOUR_DOMAIN>/
# Check CloudWatch logs for errors and confirm every secret slot has a value
```

**Verify:** Every web service answers its health check; no errors in the logs for 15 minutes.


## Terraform

16 files were written to `.prodpath/out/terraform/`: `README.md`, `alb.tf`, `backend.tf`, `ecr.tf`, `ecs.tf`, `github_oidc.tf`, `iam.tf`, `main.tf`, `network.tf`, `outputs.tf`, `rds.tf`, `secrets.tf`, `static_site.tf`, `terraform.tfvars.example`, `variables.tf`, `versions.tf`.

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
- Traffic and data volume are unknown: all sizing is a default starting point.
- apps-dashboard: no listening port found; set the container port.
- apps-docs: build output directory not detected; assumed dist.
- apps-docs: needs a domain (served at apps-docs.<domain_name>) and a CloudFront ACM certificate created in us-east-1, which Terraform does not create.
- apps-marketing: needs a domain (served at apps-marketing.<domain_name>) and a CloudFront ACM certificate created in us-east-1, which Terraform does not create.
- apps-spa: assumed a single-page app (403/404 answered with /index.html); turn the fallback off for multi-page sites.
- apps-spa: needs a domain (served at apps-spa.<domain_name>) and a CloudFront ACM certificate created in us-east-1, which Terraform does not create.
- Confirm the AWS region (assumed `ap-south-1`).

## Not analyzed

- nothing was skipped

## What this plan is based on

- 0 of 14 extracted facts are heuristic (pattern matches, not parsed).
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
