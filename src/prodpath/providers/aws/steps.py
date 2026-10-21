"""Architecture -> ordered deployment steps with AWS CLI commands.

Commands are templates with <PLACEHOLDERS> for things only the user knows (account id,
bucket names, profile). The tool never sees credentials or account ids. When the architecture
has an ECS cluster, Terraform (providers/aws/iac.py) creates most resources and these steps
wrap it; otherwise (e.g. a lone App Runner service) they are the by-hand route.
"""

from prodpath.models import Architecture, Component, Step
from prodpath.providers.aws.iac import GENERATED_TYPES, iac_gaps

Builder = list[Step]


def _of_type(arch: Architecture, *types: str) -> list[Component]:
    return [c for c in arch.components if c.type in types]


def _names(components: list[Component]) -> list[str]:
    return [c.name for c in components]


def _service_ids(arch: Architecture) -> list[str]:
    return sorted({sid for c in arch.components if c.type == "ecr" for sid in c.serves})


def _item(component: Component, key: str) -> str | None:
    for item in component.items:
        if item.startswith(key + ":"):
            return item.split(":", 1)[1]
    return None


def _account_step(arch: Architecture) -> Step:
    return Step(
        id="account",
        title="Prepare the AWS account and a budget alarm",
        why="Cost surprises are the most common first-month problem; set an alarm before "
        "creating anything billable. This tool never sees your credentials, so you run these.",
        commands=[
            "aws sso login --profile <PROFILE>   # or any login method you already use",
            "aws sts get-caller-identity --profile <PROFILE>",
            "# In the Billing console: create a monthly budget with an e-mail alert "
            "at a figure you are comfortable with.",
        ],
        verify="get-caller-identity prints the account you expect; the budget alert exists.",
        components=[],
    )


def _state_step(arch: Architecture) -> Step | None:
    state = _of_type(arch, "tf-state")
    if not state:
        return None
    region = arch.region
    location = (
        ""
        if region == "us-east-1"
        else f" --create-bucket-configuration LocationConstraint={region}"
    )
    return Step(
        id="state",
        title="Create the remote state bucket and lock table",
        why="Terraform state must be shared, versioned, encrypted and locked "
        "(needed once Terraform is applied; Phase 5 generates it).",
        commands=[
            f"aws s3api create-bucket --bucket <STATE_BUCKET> --region {region}{location}",
            "aws s3api put-bucket-versioning --bucket <STATE_BUCKET> "
            "--versioning-configuration Status=Enabled",
            "aws s3api put-bucket-encryption --bucket <STATE_BUCKET> --server-side-encryption-configuration "
            '\'{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}\'',
            "aws s3api put-public-access-block --bucket <STATE_BUCKET> --public-access-block-configuration "
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true",
            f"aws dynamodb create-table --table-name <LOCK_TABLE> --region {region} "
            "--attribute-definitions AttributeName=LockID,AttributeType=S "
            "--key-schema AttributeName=LockID,KeyType=HASH --billing-mode PAY_PER_REQUEST",
        ],
        verify="aws s3api get-bucket-versioning --bucket <STATE_BUCKET> shows Status: Enabled.",
        components=_names(state),
    )


def _network_step(arch: Architecture) -> Step | None:
    vpc = _of_type(arch, "vpc")
    if not vpc:
        return None
    region = arch.region
    return Step(
        id="network",
        title="Create the VPC, subnets and VPC endpoints",
        why="Containers and data stores live in private subnets. S3 and ECR endpoints keep image "
        "pulls and S3 traffic off the NAT gateway, which bills per hour and per GB processed.",
        commands=[
            f"aws ec2 create-vpc --cidr-block 10.0.0.0/16 --region {region}",
            "# Create 2 public and 2 private subnets in different AZs (aws ec2 create-subnet ...)",
            "# Create an internet gateway, attach it, route the public subnets to it",
            f"aws ec2 create-vpc-endpoint --vpc-id <VPC_ID> --service-name com.amazonaws.{region}.s3 "
            "--route-table-ids <PRIVATE_ROUTE_TABLE_ID>",
            f"# Interface endpoints for com.amazonaws.{region}.ecr.api, .ecr.dkr and .logs",
            "# Add a NAT gateway only if a private service must reach the public internet",
        ],
        verify="aws ec2 describe-vpc-endpoints lists the S3 and ECR endpoints as available.",
        components=_names(vpc),
    )


def _data_step(arch: Architecture) -> Step | None:
    data = _of_type(
        arch, "rds", "documentdb", "dynamodb", "elasticache", "sqs", "sns", "amazon-mq", "msk", "s3"
    )
    if not data:
        return None
    commands = []
    for c in data:
        if c.type == "rds":
            engine = c.name.removeprefix("rds-")
            multi = "--multi-az " if "Multi-AZ" in c.sizing else ""
            commands.append(
                f"aws rds create-db-instance --db-instance-identifier {c.name} --engine {engine} "
                f"--db-instance-class <INSTANCE_CLASS> --allocated-storage 20 --storage-encrypted "
                f"{multi}--backup-retention-period 7 --manage-master-user-password "
                "--master-username <ADMIN_USER> --db-subnet-group-name <PRIVATE_SUBNET_GROUP> "
                "--no-publicly-accessible"
            )
        elif c.type == "elasticache":
            commands.append(
                f"aws elasticache create-replication-group --replication-group-id {c.name} "
                "--replication-group-description <DESC> --engine redis --cache-node-type cache.t4g.micro "
                "--at-rest-encryption-enabled --transit-encryption-enabled "
                "--cache-subnet-group-name <PRIVATE_SUBNET_GROUP>"
            )
        elif c.type == "s3":
            commands.append(
                f"aws s3api create-bucket --bucket <{c.name.upper()}_BUCKET> --region {arch.region}"
            )
        elif c.type == "sqs":
            commands.append(
                "aws sqs create-queue --queue-name <QUEUE_NAME>   # plus a dead-letter queue"
            )
        else:
            commands.append(
                f"# {c.name}: {c.sizing}. Create it in the console or your IaC; see the reason in the table."
            )
    return Step(
        id="data",
        title="Create data stores, caches, queues and buckets",
        why="Services need these before they can start. Encryption and private access are on by "
        "default in the commands; do not turn them off to make something connect.",
        commands=commands,
        verify="Each resource shows 'available' and is not publicly accessible.",
        components=_names(data),
    )


def _secrets_step(arch: Architecture) -> Step | None:
    secrets = _of_type(arch, "secrets")
    if not secrets:
        return None
    commands = []
    for c in secrets:
        service = c.serves[0]
        for name in c.items:
            commands.append(
                f"aws secretsmanager create-secret --name {arch.environment}/{service}/{name}"
            )
    commands.append(
        "# Then set each value yourself, out of band: aws secretsmanager put-secret-value ..."
    )
    return Step(
        id="secrets",
        title="Create empty secret slots, then fill them yourself",
        why="This tool only knows variable names, never values, so it cannot and should not set them.",
        commands=commands,
        verify="aws secretsmanager list-secrets shows every slot; none contain placeholder text.",
        components=_names(secrets),
    )


def _images_step(arch: Architecture) -> Step | None:
    repos = _of_type(arch, "ecr")
    if not repos:
        return None
    commands = [
        f"aws ecr get-login-password --region {arch.region} | docker login --username AWS "
        f"--password-stdin <ACCOUNT_ID>.dkr.ecr.{arch.region}.amazonaws.com"
    ]
    for c in repos:
        sid = c.serves[0]
        uri = f"<ACCOUNT_ID>.dkr.ecr.{arch.region}.amazonaws.com/{c.name}"
        commands += [
            f"aws ecr create-repository --repository-name {c.name} --image-scanning-configuration scanOnPush=true",
            f"docker build -t {uri}:<GIT_SHA> <PATH_TO_{sid.upper().replace('-', '_')}>",
            f"docker push {uri}:<GIT_SHA>",
        ]
    return Step(
        id="images",
        title="Create image repositories and push the first images",
        why="Services cannot be created before an image exists. Tag with the git SHA, never 'latest'.",
        commands=commands,
        verify="aws ecr describe-images --repository-name <REPO> lists the pushed tag.",
        components=_names(repos),
    )


def _services_step(arch: Architecture) -> Step | None:
    services = _of_type(
        arch, "ecs-service-web", "ecs-service-worker", "apprunner", "ecs-cluster", "alb"
    )
    if not services:
        return None
    commands = []
    if _of_type(arch, "ecs-cluster"):
        commands.append("aws ecs create-cluster --cluster-name <CLUSTER_NAME>")
    if _of_type(arch, "alb"):
        commands += [
            "aws elbv2 create-load-balancer --name <ALB_NAME> --subnets <PUBLIC_SUBNET_IDS> --security-groups <ALB_SG>",
            "# Add an HTTPS listener with your ACM certificate; redirect HTTP to HTTPS",
        ]
    for c in services:
        if c.type == "ecs-service-web":
            port, health = _item(c, "port"), _item(c, "health")
            commands.append(
                f"# {c.name}: container port {port or '<PORT?>'}, target-group health check "
                f"{health or '<HEALTH_PATH?>'}"
            )
            commands.append(
                f"aws ecs create-service --cluster <CLUSTER_NAME> --service-name {c.name} --launch-type FARGATE ..."
            )
        elif c.type == "ecs-service-worker":
            commands.append(
                f"aws ecs create-service --cluster <CLUSTER_NAME> --service-name {c.name} --launch-type FARGATE ..."
            )
        elif c.type == "apprunner":
            commands.append(
                f"aws apprunner create-service --service-name {c.name} --source-configuration <ECR_IMAGE_CONFIG>"
            )
    return Step(
        id="services",
        title="Create the cluster, load balancer and services",
        why="Each service runs from its image with its own task role and its secrets injected "
        "from Secrets Manager, not baked into the image.",
        commands=commands,
        verify="Services reach steady state; target groups report healthy.",
        components=_names(services),
    )


def _cron_step(arch: Architecture) -> Step | None:
    cron = _of_type(arch, "scheduled-task")
    if not cron:
        return None
    return Step(
        id="schedules",
        title="Create the scheduled jobs",
        why="EventBridge Scheduler starts a Fargate task on a schedule. The schedule itself was not "
        "found in the code, so you must provide it.",
        commands=[
            f"aws scheduler create-schedule --name {c.name} --schedule-expression '<CRON_EXPRESSION>' ..."
            for c in cron
        ],
        verify="Trigger one run by hand and check the task exits with code 0 in CloudWatch logs.",
        components=_names(cron),
    )


def _cicd_step(arch: Architecture) -> Step | None:
    oidc = _of_type(arch, "iam-github-oidc")
    if not oidc:
        return None
    return Step(
        id="cicd",
        title="Set up GitHub Actions deploys through OIDC",
        why="A role assumed through OIDC means no AWS keys stored in GitHub.",
        commands=[
            "aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com "
            "--client-id-list sts.amazonaws.com",
            "# Create a role trusted by that provider, restricted to your repo and branch "
            "(sub = repo:<ORG>/<REPO>:ref:refs/heads/main), with permission to push to ECR and update the services",
        ],
        verify="A workflow run assumes the role (aws-actions/configure-aws-credentials) and pushes an image.",
        components=_names(oidc),
    )


def _observability_step(arch: Architecture) -> Step | None:
    logs = _of_type(arch, "log-group")
    if not logs:
        return None
    return Step(
        id="observability",
        title="Set log retention and basic alarms",
        why="Logs without retention grow and bill forever; an alarm on 5xx and unhealthy targets "
        "tells you before users do.",
        commands=[
            f"aws logs create-log-group --log-group-name /<APP>/{c.name} --region {arch.region}"
            for c in logs
        ]
        + [
            f"aws logs put-retention-policy --log-group-name /<APP>/{c.name} --retention-in-days 30"
            for c in logs
        ],
        verify="aws logs describe-log-groups shows retentionInDays on every group.",
        components=_names(logs),
    )


def _rollback_step(arch: Architecture) -> Step:
    return Step(
        id="rollback",
        title="Know how to roll back before you need to",
        why="Rollback is easiest when decided in advance.",
        commands=[
            "# Services: aws ecs update-service --cluster <CLUSTER_NAME> --service <SERVICE> "
            "--task-definition <PREVIOUS_TASK_DEFINITION_ARN>",
            "# Databases: take a manual snapshot before every migration "
            "(aws rds create-db-snapshot ...); never run a destructive migration without one",
        ],
        verify="Practice one rollback in a non-production environment.",
        components=[],
    )


def _verify_step(arch: Architecture) -> Step:
    web = _of_type(arch, "ecs-service-web", "apprunner")
    commands = []
    for c in web:
        health = _item(c, "health")
        commands.append(
            f"curl -fsS https://<HOST_FOR_{c.name.upper().replace('-', '_')}>{health or '/<HEALTH_PATH?>'}"
        )
    commands.append("# Check CloudWatch logs for errors and confirm every secret slot has a value")
    return Step(
        id="verify",
        title="Verify the deployment end to end",
        why="Health endpoints and logs are the first evidence the system works.",
        commands=commands,
        verify="Every web service answers its health check; no errors in the logs for 15 minutes.",
        components=[],
    )


TF_DIR = ".prodpath/out/terraform"


def _terraform_step(arch: Architecture) -> Step:
    generated = [c for c in arch.components if c.type in GENERATED_TYPES - {"tf-state"}]
    backend = (
        'terraform init -backend-config="bucket=<STATE_BUCKET>" '
        f'-backend-config="key=<APP_NAME>/{arch.environment}/terraform.tfstate" '
        f'-backend-config="region={arch.region}" '
        '-backend-config="dynamodb_table=<LOCK_TABLE>" -backend-config="encrypt=true"'
    )
    return Step(
        id="terraform",
        title="Review and apply the generated Terraform",
        why="One reviewed plan creates the network, load balancer, data stores, repositories, "
        "roles, secret slots and services together. Read the plan before applying; this tool "
        "has not touched your account.",
        commands=[
            f"cd {TF_DIR}",
            "cp terraform.tfvars.example terraform.tfvars   # then fill in every <PLACEHOLDER>",
            backend,
            "terraform plan -out=tfplan",
            "terraform apply tfplan",
        ],
        verify="`terraform plan` shows only what you expect; `terraform output` lists ECR "
        "repository URLs, secret slots and data store endpoints.",
        components=_names(generated),
    )


def _secret_values_step(arch: Architecture) -> Step | None:
    secrets = _of_type(arch, "secrets")
    if not secrets:
        return None
    commands = [
        f"aws secretsmanager put-secret-value --secret-id {arch.environment}/{c.serves[0]}/{name} "
        "--secret-string file://<PATH_TO_FILE_HOLDING_THE_VALUE>"
        for c in secrets
        for name in c.items
    ]
    hint = ""
    if _of_type(arch, "rds"):
        hint = (
            " Database URLs: use the host from `terraform output data_store_endpoints` and the "
            "master credentials from `rds_master_secret_arns`, ideally a separate user per service."
        )
    return Step(
        id="secret-values",
        title="Fill the secret slots yourself",
        why="The slots exist but are empty: this tool only knows variable names, never values. "
        "Read values from a file, not the command line, so they stay out of shell history." + hint,
        commands=commands,
        verify="aws secretsmanager list-secrets shows every slot; none hold placeholder text.",
        components=_names(secrets),
    )


def _push_images_step(arch: Architecture) -> Step | None:
    repos = _of_type(arch, "ecr")
    if not repos:
        return None
    commands = [
        f"aws ecr get-login-password --region {arch.region} | docker login --username AWS "
        f"--password-stdin <ACCOUNT_ID>.dkr.ecr.{arch.region}.amazonaws.com"
    ]
    for c in repos:
        label = c.serves[0].upper().replace("-", "_")
        url = f"<ECR_URL_FOR_{label}>"
        commands += [
            f"docker build -t {url}:<GIT_SHA> <PATH_TO_{label}>",
            f"docker push {url}:<GIT_SHA>",
        ]
    for c in _of_type(arch, "ecs-service-web", "ecs-service-worker"):
        commands.append(
            "aws ecs update-service --cluster <CLUSTER_NAME> "
            f"--service {c.serves[0]} --force-new-deployment"
        )
    return Step(
        id="images",
        title="Build and push the first images",
        why="Services stay pending until their image tag exists in ECR. Tag with the git SHA "
        "(repositories are immutable, so 'latest' cannot be reused).",
        commands=commands,
        verify="aws ecr describe-images lists the tag; services reach steady state.",
        components=[],
    )


def _gaps_step(arch: Architecture) -> Step | None:
    gaps = iac_gaps(arch)
    if not gaps:
        return None
    return Step(
        id="manual",
        title="Create what Terraform does not cover yet",
        why="These components have no template in this version. They are part of the plan, so "
        "create them by hand or with your own IaC before the services that need them.",
        commands=[f"# {gap}: see its row in the architecture table" for gap in gaps],
        verify="Each listed component exists and the services can reach it.",
        components=[g.split(" (")[0] for g in gaps],
    )


def _cicd_terraform_step(arch: Architecture) -> Step | None:
    if not _of_type(arch, "iam-github-oidc"):
        return None
    return Step(
        id="cicd",
        title="Wire GitHub Actions to the deploy role",
        why="Terraform created a role that only your repository and branch can assume through "
        "OIDC, so no AWS keys are stored in GitHub.",
        commands=[
            "# In your workflow: permissions: { id-token: write, contents: read }",
            "# uses: aws-actions/configure-aws-credentials with "
            "role-to-assume: <terraform output github_actions_role_arn>",
            "# Then: build, push the image tagged with the git SHA, register a new task "
            "definition revision, aws ecs update-service",
        ],
        verify="A workflow run on the allowed branch assumes the role and deploys; "
        "other branches are denied.",
        components=[],
    )


def _alarms_step(arch: Architecture) -> Step | None:
    if not _of_type(arch, "log-group"):
        return None
    return Step(
        id="observability",
        title="Add alarms (not generated yet)",
        why="Log groups and their retention come from Terraform. Alarms are not generated in this "
        "version; without them nobody is told when something breaks.",
        commands=[
            "# Suggested minimum: ALB 5xx rate and unhealthy host count, ECS service CPU and "
            "memory, RDS CPU, free storage and connections, and an SNS topic or chat webhook",
        ],
        verify="Trigger a test alarm and confirm you receive the notification.",
        components=[],
    )


def build_steps(arch: Architecture) -> Builder:
    if not arch.components:
        return []
    if _of_type(arch, "ecs-cluster"):  # Terraform covers this architecture
        builders = [
            _account_step, _state_step, _terraform_step, _secret_values_step, _push_images_step,
            _gaps_step, _cicd_terraform_step, _alarms_step, _rollback_step, _verify_step,
        ]  # fmt: skip
    else:  # e.g. a lone App Runner service: by-hand commands, no Terraform templates
        builders = [
            _account_step, _state_step, _network_step, _data_step, _secrets_step, _images_step,
            _services_step, _cron_step, _cicd_step, _observability_step, _rollback_step,
            _verify_step,
        ]  # fmt: skip
    return [step for build in builders if (step := build(arch)) is not None]
