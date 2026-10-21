# Partial backend configuration: no bucket, key or account details are hard-coded.
# Create the state bucket and lock table first (see PLAN.md), then run:
#   terraform init \
#     -backend-config="bucket=<STATE_BUCKET>" \
#     -backend-config="key=<APP_NAME>/prod/terraform.tfstate" \
#     -backend-config="region=ap-south-1" \
#     -backend-config="dynamodb_table=<LOCK_TABLE>" \
#     -backend-config="encrypt=true"
terraform {
  backend "s3" {}
}
