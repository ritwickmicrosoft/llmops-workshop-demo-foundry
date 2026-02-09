# LLMOps Workshop - Azure AI Foundry

[![Azure AI Foundry](https://img.shields.io/badge/Azure%20AI-Foundry-blue)](https://ai.azure.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

End-to-end LLMOps workshop using Azure AI Foundry to build a RAG-enabled chatbot with vector search and RBAC authentication.

## 🎯 Workshop Overview

Build a complete RAG (Retrieval-Augmented Generation) chatbot for "Wall-E Electronics":

| Module | Topic | Duration |
|--------|-------|----------|
| 1 | Environment Setup | 10 min |
| 2 | Deploy Azure Infrastructure | 25 min |
| 3 | Create Vector Index | 15 min |
| 4 | Run RAG Chatbot | 10 min |
| 5 | Test & Explore | 20 min |

**Total Duration:** ~90 minutes

## 🔐 Authentication

This workshop uses **RBAC (Role-Based Access Control)** — **no API keys required**.

Your Azure CLI credentials are used automatically via `DefaultAzureCredential`:
- `Cognitive Services OpenAI User` — Call Azure OpenAI APIs
- `Search Index Data Contributor` — Read/write search indices
- `Search Service Contributor` — Manage search service

## 📋 Prerequisites

- Azure subscription with Contributor access
- [Azure CLI](https://docs.microsoft.com/cli/azure/install-azure-cli) v2.50+
- [Python 3.10+](https://www.python.org/downloads/)
- [VS Code](https://code.visualstudio.com/) with Python extension

## 🚀 Quick Start

### 1. Clone and Setup

```powershell
# Clone the repository
git clone <repository-url>
cd llmops-workshop

# Create Python virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Login to Azure
az login
```

### 2. Deploy Azure Resources

```powershell
# Set variables
$env:AZURE_RESOURCE_GROUP = "rg-llmops-demo"
$env:AZURE_LOCATION = "eastus"

# Create resource group
az group create --name $env:AZURE_RESOURCE_GROUP --location $env:AZURE_LOCATION

# Create Azure OpenAI
az cognitiveservices account create `
  --name "aoai-llmops-demo" `
  --resource-group $env:AZURE_RESOURCE_GROUP `
  --location $env:AZURE_LOCATION `
  --kind OpenAI `
  --sku S0 `
  --custom-domain "aoai-llmops-demo"

# Deploy models
az cognitiveservices account deployment create `
  --name "aoai-llmops-demo" `
  --resource-group $env:AZURE_RESOURCE_GROUP `
  --deployment-name "gpt-4o" `
  --model-name "gpt-4o" `
  --model-version "2024-11-20" `
  --model-format OpenAI `
  --sku-capacity 10 `
  --sku-name Standard

az cognitiveservices account deployment create `
  --name "aoai-llmops-demo" `
  --resource-group $env:AZURE_RESOURCE_GROUP `
  --deployment-name "text-embedding-3-large" `
  --model-name "text-embedding-3-large" `
  --model-version "1" `
  --model-format OpenAI `
  --sku-capacity 10 `
  --sku-name Standard

# Create Azure AI Search
az search service create `
  --name "search-llmops-demo" `
  --resource-group $env:AZURE_RESOURCE_GROUP `
  --location $env:AZURE_LOCATION `
  --sku Basic

# Assign RBAC roles (wait 2-3 min after for propagation)
$myId = (az ad signed-in-user show --query id -o tsv)
az role assignment create --assignee $myId --role "Cognitive Services OpenAI User" `
  --scope $(az cognitiveservices account show --name aoai-llmops-demo --resource-group $env:AZURE_RESOURCE_GROUP --query id -o tsv)
az role assignment create --assignee $myId --role "Search Index Data Contributor" `
  --scope $(az search service show --name search-llmops-demo --resource-group $env:AZURE_RESOURCE_GROUP --query id -o tsv)
```

### 3. Create Vector Index

```powershell
# Update .env with your resource endpoints
Copy-Item .env.example .env
# Edit .env with your endpoints

# Create search index with sample documents
cd 01-rag-chatbot
python create_search_index.py
```

### 4. Run Chatbot

```powershell
cd ../04-frontend
python app.py
# Open http://localhost:5000
```

### 5. Open Workshop Playbook

Open [`LLMOps_Workshop_Playbook.html`](https://htmlpreview.github.io/?https://github.com/ritwickmicrosoft/llmops-workshop-demo/blob/main/LLMOps_Workshop_Playbook.html) in your browser for detailed step-by-step instructions.

## 📁 Project Structure

```
llmops-workshop/
├── data/                           # Sample documents (txt, md, pdf)
│   ├── laptop-pro-15.txt           # Product specs
│   ├── smartwatch-x200.txt         # Product specs
│   ├── nc500-headphones.txt        # Product specs
│   ├── tablet-s10.txt              # Product specs
│   ├── return-policy.md            # Policy document
│   ├── warranty-policy.md          # Policy document
│   ├── shipping-policy.md          # Policy document
│   ├── troubleshooting-guide.md    # Support document
│   └── faq.pdf                     # PDF document
├── 01-rag-chatbot/                 # RAG Chatbot Module
│   ├── create_search_index.py      # Reads data/ folder, vectorizes, indexes
│   └── rag-flow/                   # Prompt Flow definition (optional)
├── 02-evaluation/                  # Evaluation Module
│   ├── eval_dataset.jsonl          # Test dataset (Q&A pairs)
│   └── run_evaluation.py           # Run quality evaluation
├── 03-content-safety/              # Content Safety Module
│   ├── content_filter_config.json  # Filter configuration
│   └── test_content_safety.py      # Test content filters
├── 04-frontend/                    # Web Chat Interface
│   ├── app.py                      # Flask backend (RBAC)
│   ├── index.html                  # Dark-themed chat UI
│   └── requirements.txt            # Frontend dependencies
├── infra/                          # Infrastructure as Code
│   ├── main.bicep                  # Main Bicep template
│   └── modules/core.bicep          # Core resources
├── .env.example                    # Environment template
├── requirements.txt                # Python dependencies
├── LLMOps_Workshop_Playbook.html   # Interactive step-by-step guide
└── README.md                       # This file
```

## 🛠️ Azure Resources

| Resource | Type | Purpose |
|----------|------|---------|
| Azure AI Foundry | AIServices | Unified AI platform |
| Azure OpenAI | OpenAI | LLM (gpt-4o) + embeddings |
| Azure AI Search | Search | Vector store for RAG |

## 📄 Sample Documents

The `data/` folder contains 9 Wall-E Electronics documents in multiple formats:

| Format | Files | Description |
|--------|-------|-------------|
| `.txt` | 4 files | Product specifications (Laptop, Watch, Headphones, Tablet) |
| `.md` | 4 files | Policies & support (Returns, Warranty, Shipping, Troubleshooting) |
| `.pdf` | 1 file | FAQ document |

The `create_search_index.py` script automatically:
1. Reads all files from `data/` folder
2. Extracts text from .txt, .md, and .pdf files
3. Generates vector embeddings using Azure OpenAI
4. Uploads to Azure AI Search with semantic and vector search

## 🔍 RAG Flow

```
User Question → Embed (text-embedding-3-large) → Vector Search (AI Search)
                                                        ↓
                                              Top 3 Documents
                                                        ↓
                    System Prompt + Context + Question → GPT-4o → Answer
```

## 🧹 Cleanup

Delete all resources when done:

```powershell
az group delete --name rg-llmops-demo --yes --no-wait
```

## 📚 Resources

- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-studio/)
- [Azure OpenAI Service](https://learn.microsoft.com/azure/ai-services/openai/)
- [Azure AI Search Vector Search](https://learn.microsoft.com/azure/search/vector-search-overview)

## 📄 License

MIT License

---

**LLMOps Workshop — February 2026**
