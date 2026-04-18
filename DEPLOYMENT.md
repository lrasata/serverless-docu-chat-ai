# Deployment Guide

This guide covers configuration and deployment of the Serverless Document Chat AI application to AWS.

## Prerequisites

Before you begin, ensure you have:

1. **AWS Account** with administrator access
2. **AWS CLI** configured with credentials
3. **Terraform** >= 1.12.x installed
4. **Node.js** >= 22.x for frontend development
5. **Docker** (required to build Python Lambda dependencies via SAM build container)
6. **Domain name** (optional, but recommended)
7. **Bedrock Model Access** enabled in your AWS account

### Enable Bedrock Model Access

1. Navigate to AWS Bedrock console
2. Go to "Model access" in the left sidebar
3. Request access to:
   - **Amazon Titan Multimodal Embeddings G1** (`amazon.titan-embed-image-v1`, default) — or any other Bedrock embedding model you set via `embedding_model`
   - **Anthropic Claude 4.6 Sonnet** (recommended for chat). Refer to [Claude LLMs documentation](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)

Access is usually granted within minutes.

## Terraform Layers

The infrastructure is split into four independent Terraform layers that must be deployed in order:

| Layer      | Path                        | Description                      |
|------------|-----------------------------|----------------------------------|
| `secrets`  | `terraform/layers/secrets`  | API keys and application secrets |
| `cognito`  | `terraform/layers/cognito`  | Cognito User Pool + Google IdP   |
| `backend`  | `terraform/layers/backend`  | Lambda, API Gateway, RDS, VPC    |
| `frontend` | `terraform/layers/frontend` | S3, CloudFront, Route53          |

## Deployment Steps

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd serverless-docu-chat-ai
```

### 2. Configure Terraform Variables

```bash
cd terraform/environments
cp staging.tfvars.example staging.tfvars
```

Edit `staging.tfvars` with your values:

```hcl
environment = "staging"
region      = "eu-central-1"

# Domain configuration
api_backend_custom_domain_name = "staging-backend-api.your-domain.com"
api_file_upload_domain_name    = "staging-file-upload-api.your-domain.com"
cloudfront_domain_name         = "staging.your-domain.com"
route53_zone_name              = "your-domain.com"

# SSL Certificate ARN (must be in us-east-1 for CloudFront)
backend_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/your-cert-id"

# Notification email
notification_email = "your-email@your-domain.com"

# Bedrock inference profile ARN — the model the Lambda calls at runtime.
# A cross-region inference profile routes requests across regions for availability.
# Find in: AWS Bedrock → Inference and assessment → Inference profiles
bedrock_model_inference_profile_arn = "arn:aws:bedrock:eu-central-1:123456789012:inference-profile/..."

# IAM: foundation model ARNs that Bedrock is allowed to invoke on your behalf.
# Required because cross-region inference profiles route internally to underlying
# foundation models in other regions — IAM must permit those calls too.
# The default wildcard allows any model and supports LLM portability.
# Lock this down to specific ARNs in production for least-privilege.
bedrock_foundation_model_arns = ["arn:aws:bedrock:*::foundation-model/*"]

# RDS instance size
db_instance_class    = "db.t4g.micro"
availability_zones   = ["eu-central-1a", "eu-central-1b"]
max_search_results   = 5

# Embedding model (optional — default shown)
# Both s3-ingestion and query-document use the same model.
# Must stay consistent for the lifetime of the vector store — changing it requires full re-ingestion.
embedding_model = "amazon.titan-embed-image-v1"

# LLM configuration (optional — defaults shown)
llm_temperature = 0.7
llm_max_tokens  = 2000
```

#### Bedrock model configuration

Three separate settings control which models are used — they serve different purposes:

| Variable                              | Purpose                              | Description                                                                                                                                                                                                       |
|---------------------------------------|--------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `embedding_model`                     | **Embedding** — document and query vectorization | Bedrock model ID passed as `EMBEDDING_MODEL` to both `s3-ingestion` and `query-document` Lambdas. Default: `amazon.titan-embed-image-v1`. Must stay consistent for the lifetime of the vector store — changing it requires full re-ingestion of all documents. |
| `bedrock_model_inference_profile_arn` | **Runtime** — what the Lambda calls  | ARN of a Bedrock inference profile. A cross-region inference profile automatically routes requests to available regions for resilience. The Lambda passes this as `modelId` to the Bedrock Converse API. Find it in AWS Bedrock → Inference and assessment → Inference profiles. |
| `bedrock_foundation_model_arns`       | **IAM** — what AWS permits           | List of foundation model ARNs granted `bedrock:InvokeModel` in the Lambda's IAM policy. When a cross-region inference profile routes a request, Bedrock invokes the underlying foundation model in a specific region — IAM must explicitly allow that. The default `arn:aws:bedrock:*::foundation-model/*` permits any model in any region, which is what makes swapping LLMs a one-variable change. Restrict to specific ARNs in production. |

**Example: switching from Claude to Llama 3**

```hcl
# 1. Point to a Llama 3 inference profile
bedrock_model_inference_profile_arn = "arn:aws:bedrock:eu-central-1:123456789012:inference-profile/eu.meta.llama3-70b-instruct-v1:0"

# 2. Allow the underlying Llama 3 foundation model ARNs (or leave as wildcard)
bedrock_foundation_model_arns = [
  "arn:aws:bedrock:eu-central-1::foundation-model/meta.llama3-70b-instruct-v1:0",
  "arn:aws:bedrock:eu-west-1::foundation-model/meta.llama3-70b-instruct-v1:0"
]
```

No code changes required — the Lambda uses the Bedrock Converse API which has a unified interface across all supported models.

#### Embedding model options

Common choices for `embedding_model`:

| Model ID                          | Type        | Dimensions | Notes                                                  |
|-----------------------------------|-------------|------------|--------------------------------------------------------|
| `amazon.titan-embed-image-v1`     | Multimodal  | 1024       | Default. Supports text and image inputs.               |
| `amazon.titan-embed-text-v1`      | Text only   | 1536       | Text-only, higher dimensionality.                      |
| `amazon.titan-embed-text-v2:0`    | Text only   | 1024       | Latest text model, more cost-efficient.                |

> **Important:** The vector dimension must match the `embedding vector(N)` column in the `document_chunks` table. The table is created on first cold start — if you change the model after initial deployment, drop and recreate the table and re-ingest all documents.

#### LLM generation parameters

| Variable          | Default | Description                                                                                                    |
|-------------------|---------|----------------------------------------------------------------------------------------------------------------|
| `llm_temperature` | `0.7`   | Controls response randomness. `0.0` = deterministic/factual, `1.0` = more creative. Lower values are safer for Q&A use cases. |
| `llm_max_tokens`  | `2000`  | Maximum number of tokens in the model's response. Increase for longer answers, decrease to reduce Bedrock costs. |

### 3. Deploy Secrets Layer

```bash
cd terraform/layers/secrets
terraform init
terraform apply -var-file="../../environments/staging.tfvars"
```

### 4. Deploy Cognito Layer

```bash
cd terraform/layers/cognito
terraform init
terraform apply -target="module.cognito_base" -var-file="../../environments/staging.tfvars"
terraform apply -target="module.cognito_clients" -var-file="../../environments/staging.tfvars"
```

After deployment, configure Google OAuth:
1. Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials
2. Create OAuth 2.0 credentials
3. Add the Cognito callback URL from the Terraform output as an authorized redirect URI
4. Store the Google Client ID and Secret in Secrets Manager (key configured in `secret_store_name`)

### 5. Deploy Backend Layer

The backend layer includes Lambda functions (Python + TypeScript), API Gateway, RDS PostgreSQL with pgvector, and the VPC with private subnets.

#### Build Lambda packages locally (or use GitHub Actions)

Python Lambdas must be built inside an Amazon Linux container to match the Lambda runtime:

```bash
# S3 Ingestion Lambda
cd terraform/layers/backend/src/lambda_functions/s3_ingestion
rm -rf build && mkdir build
docker run --rm --user "$(id -u):$(id -g)" --entrypoint "" \
  -v "$PWD:/var/task" public.ecr.aws/sam/build-python3.11 \
  bash -c "pip install -r requirements.txt --only-binary numpy -t build/"
cp *.py build/
cd build && zip -r ../lambda_s3_ingestion.zip .

# Query Document Lambda
cd ../../query_document
rm -rf build && mkdir build
docker run --rm --user "$(id -u):$(id -g)" --entrypoint "" \
  -v "$PWD:/var/task" public.ecr.aws/sam/build-python3.11 \
  bash -c "pip install -r requirements.txt --only-binary numpy -t build/"
cp *.py build/
cd build && zip -r ../lambda_query_document.zip .
```

Upload the zips to S3:

```bash
aws s3 cp lambda_s3_ingestion.zip s3://docu-chat-ai-lambda-s3-ingestion/staging/s3-ingestion.zip
aws s3 cp lambda_query_document.zip s3://docu-chat-ai-lambda-s3-query-document/staging/s3-query-document.zip
```

#### Deploy

```bash
cd terraform/layers/backend
terraform init -upgrade
terraform apply -var-file="../../environments/staging.tfvars"
```

This creates:
- Private VPC with 2 subnets, security groups, and VPC endpoints
- RDS PostgreSQL instance (db.t4g.micro, encrypted, not publicly accessible)
- RDS credentials stored in Secrets Manager
- Lambda functions with VPC access (s3-ingestion, query-document)
- Lambda functions for file upload/listing (upload, get-files, process-upload)
- API Gateway with Cognito JWT authorizer
- SNS topic for file processing fan-out
- DynamoDB table for file metadata

> **Note:** The `pgvector` extension is created automatically on the first Lambda cold start. No manual DB setup required.

### 6. Deploy Frontend Layer

```bash
cd terraform/layers/frontend
terraform init -upgrade
terraform apply -var-file="../../environments/staging.tfvars"
```

This creates:
- S3 bucket for static hosting
- CloudFront distribution with OAC
- Route53 DNS records

### 7. Build and Deploy Frontend App

Get the required values from Terraform outputs:

```bash
cd terraform/layers/cognito && terraform output
cd terraform/layers/backend && terraform output
```

Build the frontend:

```bash
cd frontend/docu-chat-ai
export VITE_AWS_COGNITO_USER_POOL_API_ENDPOINT=<cognito_user_pool_endpoint>
export VITE_AWS_HOSTED_COGNITO_LOGIN_DOMAIN=https://<cognito_domain>
export VITE_AWS_COGNITO_CLIENT_ID=<client_id>
export VITE_AWS_COGNITO_REDIRECT_URI=https://staging.your-domain.com
export VITE_API_GW_BACKEND_ENDPOINT=https://staging.your-domain.com/api
npm ci
npm run build
```

Deploy to S3 and invalidate CloudFront:

```bash
aws s3 sync dist/ s3://staging-docu-chat-ai-static-web-app-bucket/ --delete
aws cloudfront create-invalidation --distribution-id <distribution_id> --paths "/*"
```

### 8. Test

1. Navigate to `https://staging.your-domain.com`
2. Sign in with Google
3. Upload a document (supported formats: `.pdf`, `.txt`, `.md`, `.docx`)
4. Wait a few seconds for ingestion (check CloudWatch logs for the `s3-ingestion` Lambda)
5. Ask a question about the document in the chat

## CI/CD with GitHub Actions

The repository includes GitHub Actions workflows for automated deployment. Required secrets per environment:

| Secret                                | Description                            |
|---------------------------------------|----------------------------------------|
| `AWS_REGION`                          | AWS region (e.g. `eu-central-1`)       |
| `AWS_GITHUB_DEPLOY_ROLE_ARN`          | IAM role ARN for OIDC-based deployment |
| `BACKEND_CERTIFICATE_ARN`             | ACM certificate ARN for API domain     |
| `FRONTEND_CERTIFICATE_ARN`            | ACM certificate ARN for CloudFront     |
| `COGNITO_USER_POOL_API_ENDPOINT`      | Cognito User Pool endpoint             |
| `COGNITO_CLIENT_ID`                   | Cognito app client ID                  |
| `SECRET_STORE_NAME`                   | Secrets Manager secret name            |
| `ALERT_EMAIL`                         | Email for SNS notifications            |
| `BEDROCK_MODEL_INFERENCE_PROFILE_ARN` | Bedrock inference profile ARN          |

Workflows:
- `deploy-backend-to-staging.yml` — deploys secrets, cognito, and backend layers in sequence
- `deploy-frontend-to-staging.yml` — deploys frontend layer and React app
- `destroy-staging-env.yml` — tears down all layers in reverse order

## Verification Checklist

- [ ] Frontend loads at CloudFront URL
- [ ] Google sign-in works
- [ ] File upload returns presigned URL and file appears in the list
- [ ] CloudWatch logs for `s3-ingestion` show `Document ingestion completed successfully`
- [ ] Chat endpoint responds with a grounded answer
- [ ] Bedrock API calls succeed (check Lambda logs)

## Troubleshooting

### Lambda cannot connect to RDS

- Verify Lambda security group allows outbound on port 5432
- Verify RDS security group allows inbound from Lambda security group on port 5432
- Both must be in the same VPC

### pgvector extension error on cold start

The `CREATE EXTENSION IF NOT EXISTS vector` runs automatically at Lambda init. If it fails, check that the RDS user (`pgvector_admin`) has `SUPERUSER` or `rds_superuser` privileges.

### Lambda timeout on first invocation

Cold start includes DB connection + extension check. Increase Lambda timeout to 120s if needed.

### Subnet/SG deletion stuck during destroy

Lambda VPC ENIs can take up to 45 minutes to be released by AWS. The destroy pipeline includes an automatic ENI cleanup step. If running manually:

```bash
# Find and delete available ENIs in the VPC
aws ec2 describe-network-interfaces \
  --filters "Name=vpc-id,Values=<vpc-id>" "Name=status,Values=available" \
  --query "NetworkInterfaces[*].NetworkInterfaceId" --output text | \
  xargs -I {} aws ec2 delete-network-interface --network-interface-id {}
```

### Secrets Manager conflict on redeploy

If a secret is scheduled for deletion (7-day window in prod, 0 in staging), force-delete it before redeploying:

```bash
aws secretsmanager delete-secret \
  --secret-id "staging/docu-chat-ai/rds-pgvector" \
  --force-delete-without-recovery
```

### CloudFront OAC already exists

If the OAC exists in AWS but not in Terraform state, the deploy pipeline deletes it automatically before apply. To do it manually:

```bash
OAC_ID=$(aws cloudfront list-origin-access-controls \
  --query "OriginAccessControlList.Items[?Name=='staging-s3-oac'].Id" --output text)
ETAG=$(aws cloudfront get-origin-access-control --id "$OAC_ID" --query ETag --output text)
aws cloudfront delete-origin-access-control --id "$OAC_ID" --if-match "$ETAG"
```

### Bedrock throttling

Request a service quota increase in AWS Service Quotas, or switch to Claude Haiku for lower-cost use cases.

### CORS errors

Verify API Gateway CORS configuration includes your CloudFront domain and that the `Authorization` header is allowed.

## Monitoring

Key CloudWatch metrics to watch:

- **Lambda errors/duration** — per function
- **API Gateway 4xx/5xx** — authentication and server errors
- **RDS connections** — monitor for connection pool exhaustion
- **Bedrock API calls** — track usage and costs

Useful log tails:

```bash
aws logs tail /aws/lambda/staging-docu-chat-ai-s3-ingestion --follow
aws logs tail /aws/lambda/staging-docu-chat-ai-query-document --follow
```

## Costs

Estimated monthly costs (staging / low usage):

| Service                                                 | Cost                           |
|---------------------------------------------------------|--------------------------------|
| RDS PostgreSQL db.t4g.micro                             | ~$13/month                     |
| VPC Interface Endpoints (Bedrock, Secrets Manager, SNS) | ~$30-45/month                  |
| Lambda                                                  | ~$5-10 (1M requests free tier) |
| Bedrock — Titan Embeddings                              | $0.0001/1K tokens              |
| Bedrock — Claude 4.6 Sonnet                             | $0.003/1K input tokens         |
| S3 + CloudFront                                         | ~$1-5                          |
| DynamoDB                                                | ~$1-2 (on-demand)              |
| **Total**                                               | **~$55-80/month**              |

**Cost tips:**
- Use `db.t4g.micro` for staging (burstable, cheapest RDS tier)
- VPC Interface Endpoints are the largest fixed cost — consider removing non-critical ones for dev environments
- Switch to Claude Haiku for cost-sensitive use cases

## Cleanup

To destroy all resources (staging):

```bash
# Destroy in reverse order
cd terraform/layers/frontend && terraform destroy -auto-approve
cd ../backend && terraform destroy -auto-approve
cd ../cognito && terraform destroy -auto-approve -target=module.cognito_clients
cd ../cognito && terraform destroy -auto-approve -target=module.cognito_base
cd ../secrets && terraform destroy -auto-approve
```

Or use the `destroy-staging-env.yml` GitHub Actions workflow.

**Warning:** This deletes all data including uploaded documents and indexed vectors.