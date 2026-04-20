# Deployment Guide

This infrastructure is deployed via **GitHub Actions** and has been tested through it. The workflows handle Lambda builds, Terraform applies, and frontend deployment automatically.

---

## Prerequisites

Before triggering the workflows, ensure the following are set up in your AWS account:

1. **AWS Account** with administrator access
2. **Domain name** (optional, but recommended)
3. **Bedrock Model Access** enabled

### Enable Bedrock Model Access

1. Navigate to AWS Bedrock console
2. Go to "Model access" in the left sidebar
3. Request access to:
   - **Amazon Titan Multimodal Embeddings G1** (`amazon.titan-embed-image-v1`, default) — or any other Bedrock embedding model you set via `embedding_model`
   - **Anthropic Claude 4.6 Sonnet** (recommended for chat). Refer to [Claude LLMs documentation](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)

Access is usually granted within minutes.

---

## Terraform Layers

The infrastructure is split into four independent Terraform layers deployed in order by the workflows:

| Layer      | Path                        | Description                      |
|------------|-----------------------------|----------------------------------|
| `secrets`  | `terraform/layers/secrets`  | API keys and application secrets |
| `cognito`  | `terraform/layers/cognito`  | Cognito User Pool + Google IdP   |
| `backend`  | `terraform/layers/backend`  | Lambda, API Gateway, RDS, VPC    |
| `frontend` | `terraform/layers/frontend` | S3, CloudFront, Route53          |

---

## Terraform Variables

Create `terraform/environments/staging.tfvars` from the example:

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
# The default wildcard allows any model and supports LLM portability.
# Lock this down to specific ARNs in production for least-privilege.
bedrock_foundation_model_arns = ["arn:aws:bedrock:*::foundation-model/*"]

# RDS instance size
db_instance_class    = "db.t4g.micro"
availability_zones   = ["eu-central-1a", "eu-central-1b"]
max_search_results   = 5

# Embedding model (optional — default shown)
# Must stay consistent for the lifetime of the vector store — changing it requires full re-ingestion.
embedding_model = "amazon.titan-embed-image-v1"

# LLM configuration (optional — defaults shown)
llm_temperature = 0.7
llm_max_tokens  = 2000
```

### Bedrock model configuration

| Variable                              | Purpose                              | Description                                                                                                                                                                                                       |
|---------------------------------------|--------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `embedding_model`                     | **Embedding** — document and query vectorization | Bedrock model ID passed to both `s3-ingestion` and `query-document` Lambdas. Default: `amazon.titan-embed-image-v1`. Must stay consistent — changing it requires full re-ingestion. |
| `bedrock_model_inference_profile_arn` | **Runtime** — what the Lambda calls  | ARN of a Bedrock inference profile. A cross-region inference profile routes requests automatically for resilience. Find it in AWS Bedrock → Inference and assessment → Inference profiles. |
| `bedrock_foundation_model_arns`       | **IAM** — what AWS permits           | Foundation model ARNs granted `bedrock:InvokeModel`. Required because cross-region profiles route to underlying models — IAM must allow those calls. The default wildcard supports easy model switching. Restrict in production. |

**Example: switching from Claude to Llama 3**

```hcl
bedrock_model_inference_profile_arn = "arn:aws:bedrock:eu-central-1:123456789012:inference-profile/eu.meta.llama3-70b-instruct-v1:0"
bedrock_foundation_model_arns = [
  "arn:aws:bedrock:eu-central-1::foundation-model/meta.llama3-70b-instruct-v1:0",
  "arn:aws:bedrock:eu-west-1::foundation-model/meta.llama3-70b-instruct-v1:0"
]
```

No code changes required — the Lambda uses the Bedrock Converse API which has a unified interface across all supported models.

### Embedding model options

| Model ID                       | Type       | Dimensions | Notes                                    |
|--------------------------------|------------|------------|------------------------------------------|
| `amazon.titan-embed-image-v1`  | Multimodal | 1024       | Default. Supports text and image inputs. |
| `amazon.titan-embed-text-v1`   | Text only  | 1536       | Text-only, higher dimensionality.        |
| `amazon.titan-embed-text-v2:0` | Text only  | 1024       | Latest text model, more cost-efficient.  |

> **Important:** The vector dimension must match the `embedding vector(N)` column in the `document_chunks` table. If you change the model after initial deployment, drop and recreate the table and re-ingest all documents.

### LLM generation parameters

| Variable          | Default | Description                                                                                                                   |
|-------------------|---------|-------------------------------------------------------------------------------------------------------------------------------|
| `llm_temperature` | `0.7`   | Controls response randomness. `0.0` = deterministic/factual, `1.0` = more creative. Lower values are safer for Q&A use cases. |
| `llm_max_tokens`  | `2000`  | Maximum number of tokens in the model's response. Increase for longer answers, decrease to reduce Bedrock costs.              |

---

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

### One-time: configure Google OAuth after first Cognito deploy

After the first run of `deploy-backend-to-staging.yml`:

1. Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials
2. Create OAuth 2.0 credentials
3. Add the Cognito callback URL from the Terraform output as an authorized redirect URI
4. Store the Google Client ID and Secret in Secrets Manager (key configured in `secret_store_name`)

---

## Verification Checklist

- [ ] Frontend loads at CloudFront URL
- [ ] Google sign-in works
- [ ] File upload returns presigned URL and file appears in the list
- [ ] CloudWatch logs for `s3-ingestion` show `Document ingestion completed successfully`
- [ ] Chat endpoint responds with a grounded answer
- [ ] Bedrock API calls succeed (check Lambda logs)

---

## Costs

Estimated monthly costs (staging / low usage):

| Service                                                 | Cost                           |
|---------------------------------------------------------|--------------------------------|
| RDS PostgreSQL db.t4g.micro                             | ~$22/month                     |
| VPC Interface Endpoints (Bedrock, Secrets Manager, SNS) | ~$30-45/month                  |
| Lambda                                                  | ~$5-10 (1M requests free tier) |
| Bedrock — Titan Multimodal Embeddings                   | $0.0008/1K tokens              |
| Bedrock — Claude 4.6 Sonnet                             | $0.003/1K input tokens         |
| S3 + CloudFront                                         | ~$1-5                          |
| DynamoDB                                                | ~$1-2 (on-demand)              |
| **Total**                                               | **~$65-90/month**              |

**Cost tips:**
- Use `db.t4g.micro` for staging (burstable, cheapest RDS tier)
- VPC Interface Endpoints are the largest fixed cost — consider removing non-critical ones for dev environments
- Switch to Claude Haiku for cost-sensitive use cases

---

## Cleanup

Use the `destroy-staging-env.yml` GitHub Actions workflow to tear down all layers in reverse order.

> **Warning:** This deletes all data including uploaded documents and indexed vectors.