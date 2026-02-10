# GitHub Actions CI/CD Setup Guide

This guide explains how to configure GitHub Actions for the LLMOps workshop project.

## 🔧 Prerequisites

1. Azure subscription with contributor access
2. GitHub repository with Actions enabled
3. Azure CLI installed locally (for initial setup)

## 📋 Workflows Overview

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| **CI - Validate PR** | Pull requests | Lint, test, validate Bicep |
| **CD - Deploy to Azure** | Push to main | Deploy infra + app to Azure |
| **LLMOps - Evaluation** | PRs with prompt/RAG changes | Quality evaluation gates |

## 🔐 Required GitHub Secrets

Navigate to **Settings → Secrets and variables → Actions** and add:

### AZURE_CREDENTIALS (Required)
Service principal credentials for Azure access.

```bash
# Create service principal
az ad sp create-for-rbac \
  --name "github-llmops-sp" \
  --role contributor \
  --scopes /subscriptions/{subscription-id}/resourceGroups/rg-llmops-demo \
  --sdk-auth
```

Copy the entire JSON output and paste as the secret value:
```json
{
  "clientId": "xxx",
  "clientSecret": "xxx",
  "subscriptionId": "xxx",
  "tenantId": "xxx"
}
```

### AZURE_SUBSCRIPTION_ID (Required)
Your Azure subscription ID.

```bash
az account show --query id -o tsv
```

### AZURE_PRINCIPAL_ID (Required for RBAC)
Object ID of the service principal for RBAC assignments.

```bash
az ad sp show --id {clientId-from-above} --query id -o tsv
```

### AZURE_OPENAI_ENDPOINT (Required for Evaluation)
Azure OpenAI endpoint URL.

```
https://aoai-llmops-eastus.openai.azure.com/
```

### AZURE_OPENAI_DEPLOYMENT (Optional)
Model deployment name (defaults to `gpt-4o`).

### AZURE_SEARCH_ENDPOINT (Optional)
Azure AI Search endpoint for RAG.

## 🚀 Setting Up Workflows

### Step 1: Create Service Principal

```bash
# Login to Azure
az login

# Create SP with required permissions
az ad sp create-for-rbac \
  --name "github-llmops-sp" \
  --role contributor \
  --scopes /subscriptions/1d53bfb3-a84c-4eb4-8c79-f29dc8424b6a/resourceGroups/rg-llmops-demo \
  --sdk-auth > azure-credentials.json

# Get the object ID for RBAC
SP_ID=$(az ad sp show --id $(jq -r .clientId azure-credentials.json) --query id -o tsv)
echo "AZURE_PRINCIPAL_ID: $SP_ID"
```

### Step 2: Grant Additional RBAC Roles

The service principal needs these roles for evaluation and deployment:

```bash
# Cognitive Services OpenAI User (for evaluation)
az role assignment create \
  --role "Cognitive Services OpenAI User" \
  --assignee-object-id $SP_ID \
  --assignee-principal-type ServicePrincipal \
  --scope /subscriptions/1d53bfb3-a84c-4eb4-8c79-f29dc8424b6a/resourceGroups/rg-llmops-demo

# Search Index Data Reader (for RAG)
az role assignment create \
  --role "Search Index Data Reader" \
  --assignee-object-id $SP_ID \
  --assignee-principal-type ServicePrincipal \
  --scope /subscriptions/1d53bfb3-a84c-4eb4-8c79-f29dc8424b6a/resourceGroups/rg-llmops-demo
```

### Step 3: Add Secrets to GitHub

1. Go to your repository on GitHub
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add each secret:

| Secret Name | Value |
|-------------|-------|
| `AZURE_CREDENTIALS` | Contents of `azure-credentials.json` |
| `AZURE_SUBSCRIPTION_ID` | `1d53bfb3-a84c-4eb4-8c79-f29dc8424b6a` |
| `AZURE_PRINCIPAL_ID` | Service principal object ID |
| `AZURE_OPENAI_ENDPOINT` | `https://aoai-llmops-eastus.openai.azure.com/` |

### Step 4: Test the Workflows

1. **Test CI**: Create a new branch, make a change, and open a PR
2. **Test Evaluation**: Modify a file in `01-rag-chatbot/` or `04-frontend/app.py`
3. **Test CD**: Merge a PR to `main` or use manual dispatch

## 📊 Workflow Details

### CI Pipeline (ci.yml)

Runs on every PR to validate code quality:

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│    Lint     │    │   Security   │    │    Test     │
│  (Ruff,     │───▶│   (Bandit,   │───▶│  (pytest)   │
│   Black)    │    │   Safety)    │    │             │
└─────────────┘    └──────────────┘    └─────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │  Validate Bicep Infra  │
              └────────────────────────┘
```

### CD Pipeline (cd-deploy.yml)

Deploys infrastructure and application:

```
┌─────────────┐    ┌─────────────────┐    ┌──────────────┐
│    Setup    │───▶│ Deploy Bicep    │───▶│ Deploy App   │
│ (determine  │    │ Infrastructure  │    │ (App Service)│
│   env)      │    └─────────────────┘    └──────────────┘
└─────────────┘                                   │
                                                  ▼
                                    ┌────────────────────┐
                                    │  Configure RBAC    │
                                    │ (Managed Identity) │
                                    └────────────────────┘
```

### LLMOps Evaluation (llmops-evaluation.yml)

Runs quality gates on prompt/RAG changes:

```
┌────────────────────┐    ┌───────────────────┐
│  Run Evaluation    │───▶│ Content Safety    │
│  (Groundedness,    │    │ Tests             │
│   Fluency)         │    │                   │
└────────────────────┘    └───────────────────┘
         │                         │
         ▼                         ▼
┌────────────────────────────────────────────┐
│            Quality Gates Check             │
│  • Groundedness ≥ 3.0                      │
│  • Fluency ≥ 3.0                           │
│  • Content Safety Tests Pass               │
└────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│         Comment Results on PR              │
└────────────────────────────────────────────┘
```

## 🌍 Environments

Configure GitHub Environments for deployment protection:

1. Go to **Settings** → **Environments**
2. Create environments: `dev`, `staging`, `prod`
3. Add protection rules for `prod`:
   - Required reviewers
   - Wait timer (optional)

## 🔄 Manual Deployment

Trigger deployment manually:

1. Go to **Actions** tab
2. Select **CD - Deploy to Azure**
3. Click **Run workflow**
4. Choose environment and options

## 🛠️ Troubleshooting

### Authentication Errors
- Verify `AZURE_CREDENTIALS` secret is valid JSON
- Check service principal hasn't expired
- Ensure required RBAC roles are assigned

### Evaluation Failures
- Check `AZURE_OPENAI_ENDPOINT` is correct
- Verify evaluation data exists in `02-evaluation/data/`
- Review rate limits (Azure OpenAI TPM)

### Deployment Failures
- Check resource group exists
- Verify App Service plan SKU is available in region
- Review Azure activity logs for detailed errors

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Azure Login Action](https://github.com/Azure/login)
- [Azure AI Evaluation SDK](https://learn.microsoft.com/azure/ai-studio/how-to/evaluate-sdk)
- [Bicep Documentation](https://learn.microsoft.com/azure/azure-resource-manager/bicep/)
